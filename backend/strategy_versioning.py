import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from factor_lab.strategy import build_ml_factor_signal_func
from strategy_registry import STRATEGY_REGISTRY, StrategySpec


VALID_VERSION_STATUSES = {
    "draft",
    "research_pass",
    "shadow",
    "approved",
    "active",
    "retired",
    "rejected",
}
FACTOR_LAB_CANDIDATE_FACTORS = {"ml_factor_ranker", "ml_factor_filter"}
SHADOW_MIN_OBSERVATION_DAYS = 1


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json_dumps(value: object) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _json_loads(value: Optional[str], fallback):
    if not value:
        return fallback
    try:
        payload = json.loads(value)
    except Exception:
        return fallback
    return payload if payload is not None else fallback


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip())
    return cleaned.strip("-") or "unknown"


def _read_json(path: Path) -> Dict[str, object]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _file_sha256(path: Path) -> Optional[str]:
    if not path.exists() or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_fingerprint(artifact_ref: str) -> Dict[str, object]:
    root = Path(artifact_ref)
    files = {}
    for name in ("latest_manifest.json", "latest_scores.csv", "latest_model.joblib"):
        digest = _file_sha256(root / name)
        if digest:
            files[name] = digest
    joined = "|".join(f"{name}:{digest}" for name, digest in sorted(files.items()))
    return {
        "artifact_hash": hashlib.sha256(joined.encode("utf-8")).hexdigest() if joined else "",
        "files": files,
    }


def _metric_value(metrics: object, key: str, default: float = 0.0) -> float:
    if isinstance(metrics, list):
        for item in metrics:
            if isinstance(item, dict) and item.get("key") == key:
                return _safe_float(item.get("value"), default)
    return default


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        number = float(value)
    except Exception:
        return default
    if number != number or number in (float("inf"), float("-inf")):
        return default
    return number


def _leading_factor(result: Dict[str, object], candidate_factor: str) -> Dict[str, object]:
    comparisons = result.get("strategy_backtests")
    if isinstance(comparisons, dict):
        selected = comparisons.get(candidate_factor)
        if isinstance(selected, dict):
            return selected
        best_key = result.get("backtest_compare", {})
        if isinstance(best_key, dict):
            selected = comparisons.get(best_key.get("best_total_return_factor"))
            if isinstance(selected, dict):
                return selected
    return {}


def extract_factor_lab_version_metrics(
    result: Dict[str, object],
    *,
    strategy_id: str,
    candidate_factor: str,
    artifact_ref: str,
) -> Dict[str, object]:
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    leading = _leading_factor(result, candidate_factor)
    with_cost = leading.get("with_cost", {}) if isinstance(leading, dict) else {}
    with_cost_summary = with_cost.get("summary", {}) if isinstance(with_cost, dict) else {}
    cost_drag = leading.get("cost_drag", {}) if isinstance(leading, dict) else {}
    walk_forward = summary.get("walk_forward", {}) if isinstance(summary, dict) else {}
    self_iteration = result.get("self_iteration") if isinstance(result.get("self_iteration"), dict) else {}
    stress_gate = self_iteration.get("stress_gate", {}) if isinstance(self_iteration, dict) else {}
    research_iteration = result.get("research_iteration") if isinstance(result.get("research_iteration"), dict) else {}
    fp = artifact_fingerprint(artifact_ref)

    return {
        "strategy_id": strategy_id,
        "candidate_factor": candidate_factor,
        "source_run_id": str(summary.get("run_id") or ""),
        "config_hash": str(_read_json(Path(artifact_ref) / "latest_manifest.json").get("config_hash") or summary.get("config_hash") or ""),
        "artifact_ref": artifact_ref,
        "artifact_hash": fp["artifact_hash"],
        "artifact_files": fp["files"],
        "score_source": summary.get("score_source"),
        "walk_forward_coverage": _safe_float(walk_forward.get("coverage_ratio")),
        "test_rank_ic": _metric_value(result.get("model_metrics"), "test_rank_ic"),
        "with_cost_total_return": _safe_float(with_cost.get("total_return")),
        "annual_return": _safe_float(with_cost_summary.get("annual_return")),
        "max_drawdown_abs": abs(_safe_float(with_cost_summary.get("max_drawdown"))),
        "cost_drag": _safe_float(cost_drag.get("total_return_diff")),
        "cost_pct_initial": _safe_float(cost_drag.get("cost_pct_initial")),
        "stress_gate_available": bool(stress_gate.get("available")),
        "stress_gate_passed": bool(stress_gate.get("passed")),
        "stress_gate_message": stress_gate.get("message"),
        "tested_candidate_factors": int(research_iteration.get("tested_candidate_factors") or 0) if isinstance(research_iteration, dict) else 0,
        "promoted_candidate_factors": int(research_iteration.get("promoted_candidate_factors") or 0) if isinstance(research_iteration, dict) else 0,
        "parent_strategy_name": STRATEGY_REGISTRY.get(strategy_id).name if strategy_id in STRATEGY_REGISTRY else strategy_id,
    }


def evaluate_version_gates(metrics: Dict[str, object], shadow_days: int = 0) -> Dict[str, object]:
    failures: List[str] = []
    research_failures: List[str] = []

    oos_rank_ic_positive = _safe_float(metrics.get("test_rank_ic")) > 0
    total_return_positive = _safe_float(metrics.get("with_cost_total_return")) > 0
    max_drawdown_ok = _safe_float(metrics.get("max_drawdown_abs")) <= 0.25
    cost_drag_ok = _safe_float(metrics.get("cost_drag")) <= 0.05
    stress_passed = bool(metrics.get("stress_gate_available")) and bool(metrics.get("stress_gate_passed"))
    shadow_ok = shadow_days >= SHADOW_MIN_OBSERVATION_DAYS

    if not oos_rank_ic_positive:
        research_failures.append("测试 RankIC 未转正")
    if not total_return_positive:
        research_failures.append("含成本收益未转正")
    if not max_drawdown_ok:
        research_failures.append("最大回撤超过 25%")
    if not cost_drag_ok:
        research_failures.append("交易成本拖累超过 5%")

    failures.extend(research_failures)
    if not stress_passed:
        failures.append("压力测评未通过或尚未运行")
    if not shadow_ok:
        failures.append(f"影子观察少于 {SHADOW_MIN_OBSERVATION_DAYS} 个交易日")

    return {
        "oos_rank_ic_positive": oos_rank_ic_positive,
        "with_cost_return_positive": total_return_positive,
        "max_drawdown_ok": max_drawdown_ok,
        "cost_drag_ok": cost_drag_ok,
        "stress_test_passed": stress_passed,
        "shadow_min_observation_passed": shadow_ok,
        "shadow_observation_days": shadow_days,
        "research_gate_passed": not research_failures,
        "approval_gate_passed": not failures,
        "failures": failures,
        "research_failures": research_failures,
    }


class StrategyVersionStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.ensure_tables()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_tables(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_versions (
                    version_id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    parent_version_id TEXT,
                    source_run_id TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    artifact_ref TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    approved_at TEXT,
                    approved_by TEXT,
                    approval_note TEXT,
                    metrics_json TEXT NOT NULL,
                    gates_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_active_versions (
                    strategy_id TEXT PRIMARY KEY,
                    active_version_id TEXT NOT NULL,
                    previous_version_id TEXT,
                    switched_at TEXT NOT NULL,
                    switched_by TEXT,
                    rollback_reason TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_shadow_ledger (
                    version_id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    shadow_strategy_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    observation_days INTEGER NOT NULL DEFAULT 0,
                    latest_observation_date TEXT,
                    baseline_strategy_id TEXT,
                    metrics_json TEXT NOT NULL DEFAULT '{}',
                    note TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_shadow_observations (
                    version_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    total_value REAL,
                    cash REAL,
                    selected_symbols TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (version_id, date)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_version_iterations (
                    iteration_id TEXT PRIMARY KEY,
                    parent_version_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL,
                    source_run_id TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    artifact_ref TEXT NOT NULL,
                    artifact_hash TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    created_by TEXT,
                    objective_json TEXT NOT NULL,
                    next_run_config_json TEXT NOT NULL,
                    actions_json TEXT NOT NULL,
                    result_version_id TEXT,
                    note TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    strategy_id TEXT PRIMARY KEY,
                    strategy_name TEXT,
                    cash REAL,
                    total_value REAL,
                    start_value REAL,
                    last_update TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_versions_strategy ON strategy_versions(strategy_id, created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_version_iterations_parent ON strategy_version_iterations(parent_version_id, created_at)")
            conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, object]:
        payload = dict(row)
        payload["metrics"] = _json_loads(payload.pop("metrics_json", None), {})
        payload["gates"] = _json_loads(payload.pop("gates_json", None), {})
        payload["active"] = self.get_active_version_id(str(payload["strategy_id"])) == payload["version_id"]
        shadow = self.get_shadow_ledger(str(payload["version_id"]))
        if shadow:
            payload["shadow"] = shadow
        return payload

    def get_version(self, version_id: str) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM strategy_versions WHERE version_id = ?", (version_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list_versions(self, strategy_id: str) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM strategy_versions WHERE strategy_id = ? ORDER BY created_at DESC",
                (strategy_id,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_recent_versions(self, limit: int = 20) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM strategy_versions ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_factor_lab_artifact_refs(self) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT version_id, strategy_id, source_run_id, artifact_ref, status, created_at
                FROM strategy_versions
                WHERE artifact_ref IS NOT NULL AND artifact_ref != ''
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_active_version_id(self, strategy_id: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT active_version_id FROM strategy_active_versions WHERE strategy_id = ?",
                (strategy_id,),
            ).fetchone()
        return str(row["active_version_id"]) if row else None

    def get_shadow_ledger(self, version_id: str) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM strategy_shadow_ledger WHERE version_id = ?",
                (version_id,),
            ).fetchone()
        if not row:
            return None
        payload = dict(row)
        payload["metrics"] = _json_loads(payload.pop("metrics_json", None), {})
        return payload

    def _iteration_row_to_dict(self, row: sqlite3.Row) -> Dict[str, object]:
        payload = dict(row)
        payload["objective"] = _json_loads(payload.pop("objective_json", None), {})
        payload["next_run_config"] = _json_loads(payload.pop("next_run_config_json", None), {})
        payload["actions"] = _json_loads(payload.pop("actions_json", None), [])
        return payload

    def get_latest_iteration(self, parent_version_id: str) -> Optional[Dict[str, object]]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM strategy_version_iterations
                WHERE parent_version_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (parent_version_id,),
            ).fetchone()
        return self._iteration_row_to_dict(row) if row else None

    def list_iterations(self, parent_version_id: str) -> List[Dict[str, object]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM strategy_version_iterations
                WHERE parent_version_id = ?
                ORDER BY created_at DESC
                """,
                (parent_version_id,),
            ).fetchall()
        return [self._iteration_row_to_dict(row) for row in rows]

    def create_candidate_iteration_plan(
        self,
        version_id: str,
        *,
        created_by: str = "system",
        note: str = "",
    ) -> Dict[str, object]:
        version = self.get_version(version_id)
        if not version:
            raise ValueError("候选版本不存在。")
        if version["status"] in {"retired", "rejected"}:
            raise ValueError("已退役或已拒绝的版本不能继续迭代。")

        metrics = version.get("metrics") if isinstance(version.get("metrics"), dict) else {}
        gates = version.get("gates") if isinstance(version.get("gates"), dict) else {}
        failures = [str(item) for item in gates.get("failures", [])] if isinstance(gates.get("failures"), list) else []
        research_failures = (
            [str(item) for item in gates.get("research_failures", [])]
            if isinstance(gates.get("research_failures"), list)
            else []
        )
        actions: List[Dict[str, object]] = []

        if gates.get("oos_rank_ic_positive") is False:
            actions.append(
                {
                    "type": "feature_reweighting",
                    "label": "重训并重新约束因子权重",
                    "rationale": "测试 RankIC 未转正，下一轮应限制低稳定性因子并优先验证可解释信号。",
                    "blocking": True,
                }
            )
        if gates.get("with_cost_return_positive") is False:
            actions.append(
                {
                    "type": "return_after_cost_refinement",
                    "label": "优化扣成本收益",
                    "rationale": "候选组合扣交易成本后收益不足，下一轮应降低交易频率或提高入选阈值。",
                    "blocking": True,
                }
            )
        if gates.get("max_drawdown_ok") is False:
            actions.append(
                {
                    "type": "drawdown_guard_refinement",
                    "label": "加入回撤保护约束",
                    "rationale": "最大回撤未通过门禁，下一轮需要验证止损、仓位或市场状态过滤。",
                    "blocking": True,
                }
            )
        if gates.get("cost_drag_ok") is False:
            actions.append(
                {
                    "type": "cost_aware_refinement",
                    "label": "加入换手与成本惩罚",
                    "rationale": "交易成本拖累超阈值，下一轮需要显式惩罚高换手候选。",
                    "blocking": True,
                }
            )
        if gates.get("stress_test_passed") is not True:
            actions.append(
                {
                    "type": "run_stress_test",
                    "label": "补跑三行情景压力测评",
                    "rationale": "压力测评未通过或尚未运行，不能直接审批纳入。",
                    "blocking": True,
                }
            )

        shadow_days = int(gates.get("shadow_observation_days") or 0)
        if gates.get("shadow_min_observation_passed") is not True:
            actions.append(
                {
                    "type": "continue_shadow_observation",
                    "label": "继续影子观察",
                    "rationale": f"当前影子观察 {shadow_days} 天，至少需要 {SHADOW_MIN_OBSERVATION_DAYS} 个交易日。",
                    "blocking": True,
                    "required_days": SHADOW_MIN_OBSERVATION_DAYS,
                    "current_days": shadow_days,
                }
            )
        if not actions:
            actions.append(
                {
                    "type": "validation_refresh",
                    "label": "刷新样本外验证",
                    "rationale": "当前门禁没有硬阻塞，下一轮应固定 artifact 重新验证稳定性，而不是无锚点重开策略。",
                    "blocking": False,
                }
            )

        candidate_factor = str(metrics.get("candidate_factor") or "ml_factor_ranker")
        artifact_hash = str(metrics.get("artifact_hash") or artifact_fingerprint(str(version["artifact_ref"])).get("artifact_hash") or "")
        objective = {
            "summary": "围绕当前候选版本继续打磨，不开无锚点新策略，也不自动覆盖父策略。",
            "primary_blockers": failures,
            "research_failures": research_failures,
            "target_metrics": {
                "test_rank_ic": metrics.get("test_rank_ic"),
                "with_cost_total_return": metrics.get("with_cost_total_return"),
                "max_drawdown_abs": metrics.get("max_drawdown_abs"),
                "cost_drag": metrics.get("cost_drag"),
                "shadow_observation_days": shadow_days,
            },
        }
        next_run_config = {
            "mode": "candidate_anchored_refinement",
            "parent_version_id": version_id,
            "strategy_id": version["strategy_id"],
            "source_run_id": version["source_run_id"],
            "candidate_factor": candidate_factor,
            "config_hash": version["config_hash"],
            "artifact_ref": version["artifact_ref"],
            "locked_artifact_hash": artifact_hash,
            "constraints": [
                "不能覆盖父策略活动版本",
                "不能把 latest_* 当作生产真相源",
                "新验证结果必须生成新的 run_id 与候选 version_id",
            ],
            "suggested_actions": actions,
        }
        created_at = _now()
        iteration_id = f"iter@{_slug(version_id)}.{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO strategy_version_iterations (
                    iteration_id, parent_version_id, strategy_id, source_run_id, config_hash,
                    artifact_ref, artifact_hash, mode, status, created_at, created_by,
                    objective_json, next_run_config_json, actions_json, result_version_id, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    iteration_id,
                    version_id,
                    version["strategy_id"],
                    version["source_run_id"],
                    version["config_hash"],
                    version["artifact_ref"],
                    artifact_hash,
                    "candidate_anchored_refinement",
                    "planned",
                    created_at,
                    created_by,
                    _json_dumps(objective),
                    _json_dumps(next_run_config),
                    _json_dumps(actions),
                    None,
                    note,
                ),
            )
            conn.commit()
        iteration = self.get_latest_iteration(version_id)
        if not iteration:
            raise RuntimeError("候选迭代计划创建失败。")
        return iteration

    def create_factor_lab_candidate(
        self,
        result: Dict[str, object],
        *,
        strategy_id: str = "ai_ml",
        candidate_factor: str = "ml_factor_ranker",
        created_by: str = "system",
        note: str = "",
    ) -> Dict[str, object]:
        if strategy_id not in STRATEGY_REGISTRY:
            raise ValueError(f"未知父策略: {strategy_id}")
        if candidate_factor not in FACTOR_LAB_CANDIDATE_FACTORS:
            raise ValueError(f"Factor Lab 候选只支持: {', '.join(sorted(FACTOR_LAB_CANDIDATE_FACTORS))}")

        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), dict) else {}
        run_id = str(summary.get("run_id") or "")
        artifact_ref = str(artifacts.get("run_dir") or "")
        if not artifact_ref:
            raise ValueError("当前报告缺少不可变 run artifact，请先重新运行 Factor Lab。")
        artifact_dir = Path(artifact_ref)
        if not artifact_dir.exists():
            raise ValueError(f"不可变 artifact 目录不存在: {artifact_ref}")

        manifest = _read_json(artifact_dir / "latest_manifest.json")
        source_run_id = str(manifest.get("run_id") or run_id or artifact_dir.name)
        config_hash = str(manifest.get("config_hash") or summary.get("config_hash") or "")
        if not source_run_id or not config_hash:
            raise ValueError("artifact 缺少 run_id/config_hash，拒绝生成候选版本。")

        version_id = f"{_slug(strategy_id)}@{_slug(source_run_id)}.{_slug(candidate_factor)}"
        metrics = extract_factor_lab_version_metrics(
            result,
            strategy_id=strategy_id,
            candidate_factor=candidate_factor,
            artifact_ref=artifact_ref,
        )
        metrics["created_by"] = created_by
        metrics["creation_note"] = note
        gates = evaluate_version_gates(metrics, shadow_days=0)
        status = "research_pass" if gates["research_gate_passed"] else "draft"

        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO strategy_versions (
                    version_id, strategy_id, parent_version_id, source_run_id, config_hash, artifact_ref,
                    status, created_at, metrics_json, gates_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    version_id,
                    strategy_id,
                    None,
                    source_run_id,
                    config_hash,
                    artifact_ref,
                    status,
                    _now(),
                    _json_dumps(metrics),
                    _json_dumps(gates),
                ),
            )
            conn.commit()
        version = self.get_version(version_id)
        if not version:
            raise RuntimeError("候选版本创建失败。")
        return version

    def sync_factor_lab_run_evidence(self, result: Dict[str, object]) -> List[Dict[str, object]]:
        summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
        run_id = str(summary.get("run_id") or "")
        if not run_id:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM strategy_versions WHERE source_run_id = ?",
                (run_id,),
            ).fetchall()
            updated_ids = []
            for row in rows:
                version = self._row_to_dict(row)
                metrics = dict(version.get("metrics") or {})
                candidate_factor = str(metrics.get("candidate_factor") or "ml_factor_ranker")
                artifact_ref = str(version.get("artifact_ref") or metrics.get("artifact_ref") or "")
                if artifact_ref:
                    refreshed = extract_factor_lab_version_metrics(
                        result,
                        strategy_id=str(version["strategy_id"]),
                        candidate_factor=candidate_factor,
                        artifact_ref=artifact_ref,
                    )
                    metrics.update(refreshed)
                shadow_days = int((version.get("shadow") or {}).get("observation_days") or 0)
                gates = evaluate_version_gates(metrics, shadow_days=shadow_days)
                conn.execute(
                    "UPDATE strategy_versions SET metrics_json = ?, gates_json = ? WHERE version_id = ?",
                    (_json_dumps(metrics), _json_dumps(gates), version["version_id"]),
                )
                updated_ids.append(version["version_id"])
            conn.commit()
        return [self.get_version(version_id) for version_id in updated_ids if self.get_version(version_id)]

    def start_shadow(self, version_id: str, *, started_by: str = "system", note: str = "") -> Dict[str, object]:
        version = self.get_version(version_id)
        if not version:
            raise ValueError("候选版本不存在。")
        if version["status"] not in {"research_pass", "shadow", "approved"}:
            raise ValueError("只有 research_pass/approved 版本可以进入影子观察。")
        shadow_strategy_id = version_id
        base = STRATEGY_REGISTRY.get(str(version["strategy_id"]))
        account_name = f"Shadow {base.name if base else version['strategy_id']} {version_id}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO accounts (
                    strategy_id, strategy_name, cash, total_value, start_value, last_update
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (shadow_strategy_id, account_name, 1000000.0, 1000000.0, 1000000.0, None),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO strategy_shadow_ledger (
                    version_id, strategy_id, shadow_strategy_id, started_at, status,
                    observation_days, latest_observation_date, baseline_strategy_id, metrics_json, note
                ) VALUES (?, ?, ?, COALESCE((SELECT started_at FROM strategy_shadow_ledger WHERE version_id = ?), ?), ?, 
                    COALESCE((SELECT observation_days FROM strategy_shadow_ledger WHERE version_id = ?), 0),
                    (SELECT latest_observation_date FROM strategy_shadow_ledger WHERE version_id = ?),
                    ?, COALESCE((SELECT metrics_json FROM strategy_shadow_ledger WHERE version_id = ?), '{}'), ?)
                """,
                (
                    version_id,
                    version["strategy_id"],
                    shadow_strategy_id,
                    version_id,
                    _now(),
                    "running",
                    version_id,
                    version_id,
                    version["strategy_id"],
                    version_id,
                    note or f"{started_by} 启动影子观察",
                ),
            )
            if version["status"] == "research_pass":
                metrics = version["metrics"]
                gates = evaluate_version_gates(metrics, shadow_days=int(version.get("shadow", {}).get("observation_days", 0)))
                conn.execute(
                    "UPDATE strategy_versions SET status = ?, gates_json = ? WHERE version_id = ?",
                    ("shadow", _json_dumps(gates), version_id),
                )
            conn.commit()
        return self.get_version(version_id) or version

    def record_shadow_observation(
        self,
        version_id: str,
        *,
        date: str,
        total_value: float,
        cash: float,
        selected_symbols: Optional[List[str]] = None,
    ) -> None:
        if not self.get_version(version_id):
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO strategy_shadow_observations (
                    version_id, date, total_value, cash, selected_symbols, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (version_id, date, total_value, cash, _json_dumps(selected_symbols or []), _now()),
            )
            row = conn.execute(
                "SELECT COUNT(*), MAX(date) FROM strategy_shadow_observations WHERE version_id = ?",
                (version_id,),
            ).fetchone()
            days = int(row[0] or 0)
            latest_date = row[1]
            conn.execute(
                """
                UPDATE strategy_shadow_ledger
                SET observation_days = ?, latest_observation_date = ?
                WHERE version_id = ?
                """,
                (days, latest_date, version_id),
            )
            version = conn.execute("SELECT metrics_json FROM strategy_versions WHERE version_id = ?", (version_id,)).fetchone()
            if version:
                metrics = _json_loads(version["metrics_json"], {})
                gates = evaluate_version_gates(metrics, shadow_days=days)
                conn.execute(
                    "UPDATE strategy_versions SET gates_json = ? WHERE version_id = ?",
                    (_json_dumps(gates), version_id),
                )
            conn.commit()

    def approve(self, version_id: str, *, approved_by: str = "system", note: str = "") -> Dict[str, object]:
        version = self.get_version(version_id)
        if not version:
            raise ValueError("候选版本不存在。")
        if version["status"] != "shadow":
            raise ValueError("只有 shadow 状态可以审批。")
        shadow_days = int((version.get("shadow") or {}).get("observation_days") or 0)
        gates = evaluate_version_gates(version["metrics"], shadow_days=shadow_days)
        if not gates["approval_gate_passed"]:
            raise ValueError("审批门禁未通过：" + "；".join(gates["failures"]))
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE strategy_versions
                SET status = ?, approved_at = ?, approved_by = ?, approval_note = ?, gates_json = ?
                WHERE version_id = ?
                """,
                ("approved", _now(), approved_by, note, _json_dumps(gates), version_id),
            )
            conn.commit()
        return self.get_version(version_id) or version

    def activate(self, strategy_id: str, version_id: str, *, switched_by: str = "system", note: str = "") -> Dict[str, object]:
        version = self.get_version(version_id)
        if not version:
            raise ValueError("候选版本不存在。")
        if version["strategy_id"] != strategy_id:
            raise ValueError("候选版本与目标策略不匹配。")
        if version["status"] not in {"approved", "active"}:
            raise ValueError("只有 approved 版本可以激活。")
        previous = self.get_active_version_id(strategy_id)
        with self._connect() as conn:
            if previous and previous != version_id:
                conn.execute("UPDATE strategy_versions SET status = ? WHERE version_id = ?", ("retired", previous))
            conn.execute("UPDATE strategy_versions SET status = ? WHERE version_id = ?", ("active", version_id))
            conn.execute(
                """
                INSERT OR REPLACE INTO strategy_active_versions (
                    strategy_id, active_version_id, previous_version_id, switched_at, switched_by, rollback_reason
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (strategy_id, version_id, previous, _now(), switched_by, note),
            )
            conn.commit()
        return {
            "strategy_id": strategy_id,
            "active_version_id": version_id,
            "previous_version_id": previous,
            "version": self.get_version(version_id),
        }

    def rollback(self, strategy_id: str, *, switched_by: str = "system", reason: str = "") -> Dict[str, object]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT active_version_id, previous_version_id FROM strategy_active_versions WHERE strategy_id = ?",
                (strategy_id,),
            ).fetchone()
            if not row:
                raise ValueError("当前策略没有已激活的 Factor Lab 版本。")
            current = row["active_version_id"]
            previous = row["previous_version_id"]
            conn.execute("UPDATE strategy_versions SET status = ? WHERE version_id = ?", ("retired", current))
            if previous:
                conn.execute("UPDATE strategy_versions SET status = ? WHERE version_id = ?", ("active", previous))
                conn.execute(
                    """
                    UPDATE strategy_active_versions
                    SET active_version_id = ?, previous_version_id = NULL, switched_at = ?, switched_by = ?, rollback_reason = ?
                    WHERE strategy_id = ?
                    """,
                    (previous, _now(), switched_by, reason, strategy_id),
                )
            else:
                conn.execute("DELETE FROM strategy_active_versions WHERE strategy_id = ?", (strategy_id,))
            conn.commit()
        return {
            "strategy_id": strategy_id,
            "rolled_back_version_id": current,
            "active_version_id": previous,
            "rollback_reason": reason,
        }

    def resolve_strategy_spec(self, strategy_id: str) -> Optional[StrategySpec]:
        version_id = self.get_active_version_id(strategy_id) or strategy_id
        version = self.get_version(version_id)
        if version:
            return self._version_to_strategy_spec(version, requested_key=strategy_id)
        return STRATEGY_REGISTRY.get(strategy_id)

    def _version_to_strategy_spec(self, version: Dict[str, object], *, requested_key: str) -> StrategySpec:
        base = STRATEGY_REGISTRY.get(str(version["strategy_id"]))
        metrics = version.get("metrics") if isinstance(version.get("metrics"), dict) else {}
        candidate_factor = str(metrics.get("candidate_factor") or "ml_factor_ranker")
        top_n = 5 if candidate_factor == "ml_factor_filter" else 3
        min_score = 0.60 if candidate_factor == "ml_factor_filter" else 0.0
        return StrategySpec(
            key=requested_key,
            name=f"{base.name if base else version['strategy_id']} / Factor Lab {version['version_id']}",
            func=build_ml_factor_signal_func(str(version["artifact_ref"]), top_n=top_n, min_score=min_score),
            pool=base.pool if base else "core",
            category="Factor Lab Version",
            signal_type="ranking",
            holding_policy=base.holding_policy if base else "hold_while_selected",
            default_max_hold_days=base.default_max_hold_days if base else None,
            default_take_profit=base.default_take_profit if base else None,
            execution_mode=base.execution_mode if base else "next_open_rebalance",
            requires_artifact=True,
        )
