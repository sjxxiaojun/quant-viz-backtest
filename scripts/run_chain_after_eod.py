from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any


BACKEND = Path("/Users/gdxj/quant-viz-backtest/backend")
DB = BACKEND / "virtual_trading.db"
BASE_URL = "http://127.0.0.1:8080"
TARGET_RUN_ID = sys.argv[1] if len(sys.argv) > 1 else ""


def log(message: str) -> None:
    print(f"{datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def active_eod_runs() -> list[dict[str, Any]]:
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        if TARGET_RUN_ID:
            rows = conn.execute(
                """
                SELECT run_id, status, target_date, started_at, finished_at
                FROM automation_runs
                WHERE run_id = ? AND status = 'running'
                """,
                (TARGET_RUN_ID,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT run_id, status, target_date, started_at, finished_at
                FROM automation_runs
                WHERE job_type = 'eod_update' AND status = 'running'
                ORDER BY started_at DESC, id DESC
                """
            ).fetchall()
    return [dict(row) for row in rows]


def eod_result() -> dict[str, Any]:
    with sqlite3.connect(DB) as conn:
        conn.row_factory = sqlite3.Row
        if TARGET_RUN_ID:
            row = conn.execute("SELECT * FROM automation_runs WHERE run_id = ?", (TARGET_RUN_ID,)).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM automation_runs
                WHERE job_type = 'eod_update'
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
    return dict(row) if row else {}


def record_message(title: str, body: str, *, status: str = "success", level: str = "info", details: dict[str, Any] | None = None) -> None:
    sys.path.insert(0, str(BACKEND))
    from automation_store import AutomationStore

    store = AutomationStore(DB)
    store.record_ai_work_message(
        work_id=TARGET_RUN_ID or "eod-chain-watchdog",
        work_type="eod_chain",
        trigger="watchdog",
        target_date=None,
        action_type="post_eod_chain",
        status=status,
        level=level,
        title=title,
        body=body,
        details=details or {},
    )


def post_json(path: str, body: dict[str, Any] | None = None, timeout: int = 600) -> dict[str, Any]:
    cmd = ["curl", "-sS", "--max-time", str(timeout), "-X", "POST", f"{BASE_URL}{path}"]
    if body is not None:
        cmd.extend(["-H", "Content-Type: application/json", "-d", json.dumps(body)])
    raw = subprocess.check_output(cmd, text=True)
    return json.loads(raw) if raw.strip() else {}


def get_status() -> dict[str, Any]:
    raw = subprocess.check_output(["curl", "-sS", "--max-time", "30", f"{BASE_URL}/api/automation/status"], text=True)
    return json.loads(raw)


def main() -> None:
    log(f"post-eod chain watchdog started target={TARGET_RUN_ID or 'any'}")
    while active_eod_runs():
        time.sleep(30)

    result = eod_result()
    status = get_status()
    freshness = status.get("data_freshness") or {}
    if freshness.get("status") == "blocked":
        record_message(
            "收盘后链路未继续",
            f"EOD 任务 {result.get('run_id')} 结束，但数据新鲜度仍为 blocked，未触发模拟盘和 AI cycle。",
            status="blocked",
            level="warning",
            details={"eod_result": result, "freshness": freshness},
        )
        return

    record_message(
        "收盘后链路开始",
        f"EOD 任务 {result.get('run_id')} 已结束，数据新鲜度 {freshness.get('score')}%，开始追赶模拟盘并运行 AI cycle。",
        status="running",
        details={"eod_result": result, "freshness": freshness},
    )
    virtual_trade = post_json("/api/automation/jobs/virtual-trade", timeout=600)
    ai_cycle = post_json("/api/automation/jobs/ai-cycle", timeout=900)
    record_message(
        "收盘后链路完成",
        f"模拟盘结果：{virtual_trade.get('status')}；AI cycle 结果：{ai_cycle.get('status')}。",
        details={"virtual_trade": virtual_trade, "ai_cycle": ai_cycle},
    )
    log("post-eod chain completed")


if __name__ == "__main__":
    main()
