from __future__ import annotations

import os
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


PROJECT = Path("/Users/gdxj/quant-viz-backtest")
BACKEND = PROJECT / "backend"
DB = BACKEND / "virtual_trading.db"
OLD_PID = int(os.getenv("QUANT_RESTART_OLD_PID", "28686"))
PORT = int(os.getenv("QUANT_RESTART_PORT", "8080"))
LOG = Path(os.getenv("QUANT_RESTART_LOG", "/tmp/quant_backend_restart_after_eod.log"))
PROGRESS_SECONDS = int(os.getenv("QUANT_RESTART_PROGRESS_SECONDS", "600"))
PYTHON_BIN = os.getenv(
    "QUANT_RESTART_PYTHON",
    "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python",
)


def log(message: str) -> None:
    print(f"{datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def running_eod_runs() -> list[dict[str, object]]:
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT run_id, status, target_date, started_at, finished_at
            FROM automation_runs
            WHERE job_type = 'eod_update' AND status = 'running'
            ORDER BY started_at DESC, id DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def record_message(title: str, body: str, *, status: str = "success", level: str = "info") -> None:
    sys.path.insert(0, str(BACKEND))
    from automation_store import AutomationStore

    store = AutomationStore(DB)
    store.record_ai_work_message(
        work_id="backend-restart-after-eod",
        work_type="system_restart",
        trigger="watchdog",
        target_date=None,
        action_type="backend_restart",
        status=status,
        level=level,
        title=title,
        body=body,
        details={"port": PORT, "old_pid": OLD_PID},
    )


def count_fresh_files(root: Path, target_date: str) -> tuple[int, int]:
    import pandas as pd

    total = 0
    fresh = 0
    for path in root.glob("*_full_history.parquet"):
        total += 1
        try:
            df = pd.read_parquet(path, columns=["date"])
            max_date = pd.to_datetime(df["date"], errors="coerce").dropna().max()
            if pd.notna(max_date) and str(max_date.date()) >= target_date:
                fresh += 1
        except Exception:
            pass
    return fresh, total


def record_progress(target_date: str) -> None:
    root = Path("/Users/gdxj/quant_data_lake")
    a_fresh, a_total = count_fresh_files(root, target_date)
    etf_fresh, etf_total = count_fresh_files(root / "etf", target_date)
    record_message(
        "数据湖补数进行中",
        (
            f"真实 EOD 补数仍在推进：A股已更新 {a_fresh}/{a_total} 到 {target_date}，"
            f"ETF {etf_fresh}/{etf_total}。补数完成前，模拟盘和 AI cycle 会继续等待。"
        ),
        status="running",
    )
    log(f"progress a_share={a_fresh}/{a_total} etf={etf_fresh}/{etf_total}")


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def extract_quant_env(pid: int) -> dict[str, str]:
    env: dict[str, str] = {}
    try:
        output = subprocess.check_output(["ps", "eww", "-p", str(pid), "-o", "command="], text=True)
    except Exception as exc:
        log(f"failed to read old process env: {exc}")
        return env
    for key, value in re.findall(r"\b(QUANT_[A-Z0-9_]+)=([^\s]+)", output):
        env[key] = value
    log(f"captured quant env keys: {sorted(env)}")
    return env


def wait_for_port_up(timeout: int = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(PORT):
            try:
                subprocess.check_output(
                    ["curl", "-sS", "--max-time", "5", f"http://127.0.0.1:{PORT}/api/automation/status"]
                )
                return True
            except Exception:
                pass
        time.sleep(2)
    return False


def restart_backend() -> None:
    quant_env = extract_quant_env(OLD_PID)
    if process_alive(OLD_PID):
        log(f"sending SIGTERM to old backend pid={OLD_PID}")
        os.kill(OLD_PID, signal.SIGTERM)
        deadline = time.time() + 25
        while time.time() < deadline and process_alive(OLD_PID):
            time.sleep(1)
        if process_alive(OLD_PID):
            log(f"old backend pid={OLD_PID} still alive; sending SIGKILL")
            os.kill(OLD_PID, signal.SIGKILL)
            time.sleep(2)

    deadline = time.time() + 30
    while time.time() < deadline and port_open(PORT):
        time.sleep(1)

    env = os.environ.copy()
    env.update(quant_env)
    log("starting refreshed backend on 127.0.0.1:8080")
    with LOG.open("a", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            [PYTHON_BIN, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT)],
            cwd=str(BACKEND),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    log(f"new backend pid={proc.pid}")
    if not wait_for_port_up():
        record_message("后端重启失败", "EOD 补数完成后尝试重启 8080，但健康检查未通过。", status="failed", level="error")
        raise SystemExit(3)
    record_message("后端已重启", f"EOD 补数结束后已重启 8080 后端，新进程 pid={proc.pid}，自动化新代码已上线。")
    log("backend restart completed")


def main() -> None:
    log("watchdog started")
    last_progress_at = 0.0
    while True:
        running = running_eod_runs()
        log(f"running_eod={running}")
        if not running:
            restart_backend()
            return
        if PROGRESS_SECONDS > 0 and time.time() - last_progress_at >= PROGRESS_SECONDS:
            try:
                target_date = str(running[0].get("target_date") or datetime.now().date())
                record_progress(target_date)
            except Exception as exc:
                log(f"failed to record progress: {exc}")
            last_progress_at = time.time()
        time.sleep(30)


if __name__ == "__main__":
    main()
