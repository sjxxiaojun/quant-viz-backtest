from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _json_loads(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


class AutomationStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._lock = threading.RLock()
        self.ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_tables(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS automation_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT UNIQUE NOT NULL,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    target_date TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    summary_json TEXT,
                    error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS automation_state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    decision_id TEXT UNIQUE NOT NULL,
                    actor TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    summary TEXT,
                    confidence REAL,
                    actions_json TEXT,
                    result_json TEXT,
                    error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_work_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    work_id TEXT UNIQUE NOT NULL,
                    work_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    target_date TEXT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    title TEXT,
                    summary TEXT,
                    work_items_json TEXT,
                    actions_json TEXT,
                    result_json TEXT,
                    error TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_work_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT UNIQUE NOT NULL,
                    work_id TEXT,
                    work_type TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    target_date TEXT,
                    action_type TEXT,
                    status TEXT NOT NULL,
                    level TEXT NOT NULL,
                    title TEXT,
                    body TEXT,
                    created_at TEXT NOT NULL,
                    details_json TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS market_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT UNIQUE NOT NULL,
                    captured_at TEXT NOT NULL,
                    market_session TEXT,
                    row_count INTEGER NOT NULL,
                    source TEXT,
                    rows_json TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_automation_runs_type_time ON automation_runs(job_type, started_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_automation_runs_status ON automation_runs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_decisions_time ON ai_decisions(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_work_logs_type_time ON ai_work_logs(work_type, started_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_work_logs_status ON ai_work_logs(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_work_messages_time ON ai_work_messages(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_work_messages_work ON ai_work_messages(work_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_market_snapshots_time ON market_snapshots(captured_at)")
            conn.commit()

    def start_run(self, job_type: str, trigger: str, target_date: Optional[str] = None) -> str:
        run_id = f"{job_type}-{uuid.uuid4().hex[:12]}"
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO automation_runs (
                    run_id, job_type, status, trigger, target_date, started_at, summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, job_type, "running", trigger, target_date, _now_iso(), "{}"),
            )
            conn.commit()
        return run_id

    def finish_run(
        self,
        run_id: str,
        status: str,
        *,
        summary: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        finished_at = _now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE automation_runs
                SET status = ?, finished_at = ?, summary_json = ?, error = ?
                WHERE run_id = ?
                """,
                (status, finished_at, _json_dumps(summary or {}), error, run_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM automation_runs WHERE run_id = ?", (run_id,)).fetchone()
        return self._run_row_to_dict(row) if row else {}

    def list_runs(self, job_type: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 20), 200))
        with self._lock, self._connect() as conn:
            if job_type:
                rows = conn.execute(
                    """
                    SELECT * FROM automation_runs
                    WHERE job_type = ?
                    ORDER BY started_at DESC, id DESC
                    LIMIT ?
                    """,
                    (job_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM automation_runs
                    ORDER BY started_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [self._run_row_to_dict(row) for row in rows]

    def expire_stale_runs(
        self,
        *,
        max_age_minutes: int = 120,
        job_timeouts: Optional[Dict[str, int]] = None,
    ) -> List[Dict[str, Any]]:
        max_age_minutes = max(5, int(max_age_minutes or 120))
        now = datetime.now()
        finished_at = _now_iso()
        expired: List[Dict[str, Any]] = []
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM automation_runs
                WHERE status = 'running'
                ORDER BY started_at ASC, id ASC
                """,
            ).fetchall()
            for row in rows:
                timeout_minutes = max(5, int((job_timeouts or {}).get(row["job_type"], max_age_minutes)))
                try:
                    started_at = datetime.fromisoformat(row["started_at"])
                except Exception:
                    started_at = now - timedelta(minutes=timeout_minutes + 1)
                if started_at >= now - timedelta(minutes=timeout_minutes):
                    continue
                summary = _json_loads(row["summary_json"], {})
                if not isinstance(summary, dict):
                    summary = {}
                summary.update({"timeout": True, "timeout_minutes": timeout_minutes})
                error = f"任务超过 {timeout_minutes} 分钟未结束，已自动标记超时。"
                conn.execute(
                    """
                    UPDATE automation_runs
                    SET status = 'failed', finished_at = ?, summary_json = ?, error = ?
                    WHERE run_id = ?
                    """,
                    (finished_at, _json_dumps(summary), error, row["run_id"]),
                )
                data = self._run_row_to_dict(row)
                data["status"] = "failed"
                data["finished_at"] = finished_at
                data["summary"] = summary
                data["error"] = error
                expired.append(data)
            conn.commit()
        return expired

    def latest_success(self, job_type: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM automation_runs
                WHERE job_type = ? AND status = 'success'
                ORDER BY started_at DESC, id DESC
                LIMIT 1
                """,
                (job_type,),
            ).fetchone()
        return self._run_row_to_dict(row) if row else None

    def get_state(self, key: str, fallback: Any = None) -> Any:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value_json FROM automation_state WHERE key = ?", (key,)).fetchone()
        return _json_loads(row["value_json"], fallback) if row else fallback

    def set_state(self, key: str, value: Any) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO automation_state (key, value_json, updated_at)
                VALUES (?, ?, ?)
                """,
                (key, _json_dumps(value), _now_iso()),
            )
            conn.commit()

    def record_market_snapshot(
        self,
        rows: List[Dict[str, Any]],
        *,
        market_session: str,
        source: str,
        captured_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        snapshot_id = f"snapshot-{uuid.uuid4().hex[:12]}"
        captured_at = captured_at or _now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO market_snapshots (
                    snapshot_id, captured_at, market_session, row_count, source, rows_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (snapshot_id, captured_at, market_session, len(rows), source, _json_dumps(rows)),
            )
            conn.commit()
        return {
            "snapshot_id": snapshot_id,
            "captured_at": captured_at,
            "market_session": market_session,
            "row_count": len(rows),
            "source": source,
        }

    def latest_snapshots(self, limit: int = 5) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 5), 50))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT snapshot_id, captured_at, market_session, row_count, source
                FROM market_snapshots
                ORDER BY captured_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_snapshot(self, *, include_rows: bool = False) -> Optional[Dict[str, Any]]:
        columns = "snapshot_id, captured_at, market_session, row_count, source"
        if include_rows:
            columns = f"{columns}, rows_json"
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"""
                SELECT {columns}
                FROM market_snapshots
                ORDER BY captured_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        if include_rows:
            data["rows"] = _json_loads(data.pop("rows_json", None), [])
        return data

    def record_ai_decision(
        self,
        *,
        actor: str,
        source: str,
        status: str,
        summary: str = "",
        confidence: Optional[float] = None,
        actions: Optional[List[Dict[str, Any]]] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        decision_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        decision_id = decision_id or f"decision-{uuid.uuid4().hex[:12]}"
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_decisions (
                    decision_id, actor, source, status, created_at, summary, confidence,
                    actions_json, result_json, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    actor,
                    source,
                    status,
                    _now_iso(),
                    summary,
                    confidence,
                    _json_dumps(actions or []),
                    _json_dumps(result or {}),
                    error,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM ai_decisions WHERE decision_id = ?", (decision_id,)).fetchone()
        return self._decision_row_to_dict(row) if row else {}

    def list_ai_decisions(self, limit: int = 20) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 20), 200))
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ai_decisions
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._decision_row_to_dict(row) for row in rows]

    def start_ai_work(
        self,
        work_type: str,
        trigger: str,
        *,
        target_date: Optional[str] = None,
        title: str = "",
    ) -> str:
        work_id = f"aiwork-{uuid.uuid4().hex[:12]}"
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_work_logs (
                    work_id, work_type, status, trigger, target_date, started_at, title,
                    work_items_json, actions_json, result_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    work_id,
                    work_type,
                    "running",
                    trigger,
                    target_date,
                    _now_iso(),
                    title,
                    "[]",
                    "[]",
                    "{}",
                ),
            )
            conn.commit()
        return work_id

    def finish_ai_work(
        self,
        work_id: str,
        status: str,
        *,
        title: str = "",
        summary: str = "",
        work_items: Optional[List[Dict[str, Any]]] = None,
        actions: Optional[List[Dict[str, Any]]] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        finished_at = _now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE ai_work_logs
                SET status = ?, finished_at = ?, title = COALESCE(NULLIF(?, ''), title),
                    summary = ?, work_items_json = ?, actions_json = ?, result_json = ?, error = ?
                WHERE work_id = ?
                """,
                (
                    status,
                    finished_at,
                    title,
                    summary,
                    _json_dumps(work_items or []),
                    _json_dumps(actions or []),
                    _json_dumps(result or {}),
                    error,
                    work_id,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM ai_work_logs WHERE work_id = ?", (work_id,)).fetchone()
        return self._work_log_row_to_dict(row) if row else {}

    def list_ai_work_logs(self, work_type: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 20), 200))
        with self._lock, self._connect() as conn:
            if work_type:
                rows = conn.execute(
                    """
                    SELECT * FROM ai_work_logs
                    WHERE work_type = ?
                    ORDER BY started_at DESC, id DESC
                    LIMIT ?
                    """,
                    (work_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM ai_work_logs
                    ORDER BY started_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [self._work_log_row_to_dict(row) for row in rows]

    def expire_stale_ai_work_logs(
        self,
        *,
        max_age_minutes: int = 120,
        work_timeouts: Optional[Dict[str, int]] = None,
    ) -> List[Dict[str, Any]]:
        max_age_minutes = max(5, int(max_age_minutes or 120))
        now = datetime.now()
        finished_at = _now_iso()
        expired: List[Dict[str, Any]] = []
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ai_work_logs
                WHERE status = 'running'
                ORDER BY started_at ASC, id ASC
                """,
            ).fetchall()
            for row in rows:
                timeout_minutes = max(5, int((work_timeouts or {}).get(row["work_type"], max_age_minutes)))
                try:
                    started_at = datetime.fromisoformat(row["started_at"])
                except Exception:
                    started_at = now - timedelta(minutes=timeout_minutes + 1)
                if started_at >= now - timedelta(minutes=timeout_minutes):
                    continue
                result = _json_loads(row["result_json"], {})
                if not isinstance(result, dict):
                    result = {}
                result.update({"timeout": True, "timeout_minutes": timeout_minutes})
                error = f"AI 托管任务超过 {timeout_minutes} 分钟未结束，已自动标记超时。"
                conn.execute(
                    """
                    UPDATE ai_work_logs
                    SET status = 'failed', finished_at = ?, result_json = ?, error = ?
                    WHERE work_id = ?
                    """,
                    (finished_at, _json_dumps(result), error, row["work_id"]),
                )
                data = self._work_log_row_to_dict(row)
                data["status"] = "failed"
                data["finished_at"] = finished_at
                data["result"] = result
                data["error"] = error
                expired.append(data)
            conn.commit()
        return expired

    def record_ai_work_message(
        self,
        *,
        work_type: str,
        trigger: str,
        status: str,
        title: str,
        body: str,
        work_id: Optional[str] = None,
        target_date: Optional[str] = None,
        action_type: Optional[str] = None,
        level: str = "info",
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        message_id = f"aimsg-{uuid.uuid4().hex[:12]}"
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_work_messages (
                    message_id, work_id, work_type, trigger, target_date, action_type,
                    status, level, title, body, created_at, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    work_id,
                    work_type,
                    trigger,
                    target_date,
                    action_type,
                    status,
                    level,
                    title,
                    body,
                    _now_iso(),
                    _json_dumps(details or {}),
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM ai_work_messages WHERE message_id = ?", (message_id,)).fetchone()
        return self._work_message_row_to_dict(row) if row else {}

    def list_ai_work_messages(self, work_type: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 50), 300))
        with self._lock, self._connect() as conn:
            if work_type:
                rows = conn.execute(
                    """
                    SELECT * FROM ai_work_messages
                    WHERE work_type = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (work_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM ai_work_messages
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [self._work_message_row_to_dict(row) for row in rows]

    @staticmethod
    def _run_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["summary"] = _json_loads(data.pop("summary_json", None), {})
        return data

    @staticmethod
    def _decision_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["actions"] = _json_loads(data.pop("actions_json", None), [])
        data["result"] = _json_loads(data.pop("result_json", None), {})
        return data

    @staticmethod
    def _work_log_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["work_items"] = _json_loads(data.pop("work_items_json", None), [])
        data["actions"] = _json_loads(data.pop("actions_json", None), [])
        data["result"] = _json_loads(data.pop("result_json", None), {})
        return data

    @staticmethod
    def _work_message_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["details"] = _json_loads(data.pop("details_json", None), {})
        return data
