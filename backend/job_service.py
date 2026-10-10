"""Durable local queue with two bounded subprocess slots and explicit cancellation."""
from __future__ import annotations
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

TERMINAL = {"succeeded", "failed", "canceled", "interrupted"}


class JobStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS research_jobs (job_id TEXT PRIMARY KEY, kind TEXT, status TEXT, request TEXT, result TEXT, error TEXT, stage TEXT, created_at REAL, updated_at REAL)")

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def create(self, kind, request):
        job_id = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            count = conn.execute("SELECT COUNT(*) FROM research_jobs WHERE status IN ('queued','running')").fetchone()[0]
            if count >= 20:
                raise ValueError("任务队列已满（20），请等待或取消旧任务。")
            now = time.time()
            conn.execute("INSERT INTO research_jobs VALUES (?,?,?,?,?,?,?,?,?)", (job_id, kind, "queued", json.dumps(request), None, None, "等待计算", now, now))
        return job_id

    def get(self, job_id, include_result=True):
        with self.connect() as conn:
            columns = "*" if include_result else "job_id,kind,status,request,NULL AS result,error,stage,created_at,updated_at"
            row = conn.execute(f"SELECT {columns} FROM research_jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        value = dict(row)
        value["request"] = json.loads(value["request"])
        value["result"] = json.loads(value["result"]) if value["result"] else None
        return value

    def update(self, job_id, **updates):
        allowed = {"status", "stage", "result", "error"}
        updates = {k: (json.dumps(v, default=str, allow_nan=False) if k == "result" else v) for k, v in updates.items() if k in allowed}
        updates["updated_at"] = time.time()
        with self.connect() as conn:
            conn.execute("UPDATE research_jobs SET " + ",".join(f"{k}=?" for k in updates) + " WHERE job_id=? AND status NOT IN ('succeeded','failed','canceled','interrupted')", (*updates.values(), job_id))

    def claim(self):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT job_id FROM research_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row:
                conn.execute("UPDATE research_jobs SET status='running',stage='准备数据',updated_at=? WHERE job_id=?", (time.time(), row[0]))
                return row[0]
        return None

    def list(self, kind=None, limit=50):
        with self.connect() as conn:
            rows = conn.execute("SELECT job_id FROM research_jobs " + ("WHERE kind=? " if kind else "") + "ORDER BY created_at DESC LIMIT ?", ((kind, limit) if kind else (limit,))).fetchall()
        return [{k: v for k, v in self.get(row[0], include_result=False).items() if k != "result"} for row in rows]

    def recover(self):
        with self.connect() as conn:
            conn.execute("UPDATE research_jobs SET status='interrupted',stage='服务重启中断',error='计算进程中断，可重新提交',updated_at=? WHERE status='running'", (time.time(),))


class JobQueue:
    def __init__(self, store, worker_script=None):
        self.store = store
        self.worker_script = Path(worker_script or Path(__file__).with_name("job_worker.py"))
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.threads = []

    def start(self):
        with self.lock:
            if self.threads:
                return
            self.store.recover()
            self.stop_event.clear()
            self.threads = [threading.Thread(target=self._loop, daemon=True) for _ in range(2)]
            for thread in self.threads:
                thread.start()

    def stop(self):
        self.stop_event.set()
        for thread in self.threads:
            thread.join(timeout=5)
        self.threads = []

    def submit(self, kind, request):
        self.start()
        return self.store.create(kind, request)

    def _loop(self):
        while not self.stop_event.is_set():
            job_id = self.store.claim()
            if not job_id:
                self.stop_event.wait(.2)
                continue
            env = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "QUANT_JOB_ID": job_id, "QUANT_JOB_DB": str(self.store.path), "PYTHONPATH": str(Path(__file__).parent) + os.pathsep + os.environ.get("PYTHONPATH", "")}
            log_path = self.store.path.parent / "job_workers.log"
            with log_path.open("a") as log:
                process = subprocess.Popen([sys.executable, str(self.worker_script), str(self.store.path), job_id], env=env, stdout=log, stderr=log)
            while process.poll() is None:
                job = self.store.get(job_id, include_result=False)
                if self.stop_event.is_set() or job["status"] == "canceled":
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    if self.stop_event.is_set():
                        self.store.update(job_id, status="interrupted", error="服务关闭中断")
                    break
                self.stop_event.wait(.2)
            if self.store.get(job_id, include_result=False)["status"] == "running":
                self.store.update(job_id, status="failed", error=f"计算进程退出（{process.returncode}），请查看后台日志。")


def report_stage(stage):
    if os.getenv("QUANT_JOB_ID") and os.getenv("QUANT_JOB_DB"):
        JobStore(os.environ["QUANT_JOB_DB"]).update(os.environ["QUANT_JOB_ID"], stage=stage)
