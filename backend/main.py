import copy
import inspect
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ai_automation import AIAutomationService, allowed_action_catalog
from automation_store import AutomationStore
from data_manager import CACHE_EDGE_TOLERANCE_DAYS, DataFetchError, DataManager, PoolDataFetchError
from data_lake_update_service import DataLakeUpdateService
from engine import BacktestEngine, CostModel
import sqlite3
from position_manager import PositionManager
from scheduler_service import AutomationOrchestrator, LightweightScheduler
from strategy_registry import STRATEGY_REGISTRY, get_strategy_spec
from strategy_versioning import StrategyVersionStore, artifact_fingerprint
from virtual_trading_manager import VirtualTradingManager
from strategies.sector_strategy import run_power_energy_strategy

DB_PATH = Path(__file__).with_name("virtual_trading.db")


app = FastAPI()

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "QUANT_API_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GeminiQuantAPI")

data_manager = DataManager()
vt_manager = VirtualTradingManager(DB_PATH, data_manager)
strategy_version_store = StrategyVersionStore(DB_PATH)
automation_store = AutomationStore(DB_PATH)
data_lake_service = DataLakeUpdateService(data_manager)
ai_automation_service = AIAutomationService(automation_store)

pool_path = Path(__file__).with_name("pools.json")
with pool_path.open("r", encoding="utf-8") as f:
    POOLS = json.load(f)

STOCK_POOL = POOLS.get("core", [])
ETF_POOL = POOLS.get("etf", [])
BLACKHORSE_POOL = POOLS.get("blackhorse", [])
POWER_ENERGY_POOL = POOLS.get("power_energy", [])
A_SHARE_POOL_NAMES = {"core", "blackhorse", "power_energy"}
FACTOR_LAB_WARMUP_DAYS = 260
BACKTEST_WARMUP_DAYS = 150
BACKTEST_MAX_CONCURRENT = 2
BACKTEST_MAX_SYMBOLS = 500
BACKTEST_MAX_DAYS = 260 * 5
BACKTEST_MAX_ROWS = 1_000_000
BACKTEST_MAX_COMPARE_STRATEGIES = 4
BACKTEST_MAX_COMPARE_ROWS = BACKTEST_MAX_ROWS
FACTOR_LAB_MAX_SYMBOLS = 500
FACTOR_LAB_DEFAULT_ALL_SAMPLE = BACKTEST_MAX_SYMBOLS
FACTOR_LAB_KEEP_RECENT_RUNS = 5
BACKTEST_SEMAPHORE = threading.BoundedSemaphore(BACKTEST_MAX_CONCURRENT)
FACTOR_LAB_SEMAPHORE = threading.BoundedSemaphore(1)
FACTOR_LAB_ARTIFACT_LOCK = threading.RLock()
VIRTUAL_TRADE_EXECUTE_LOCK = threading.Lock()
FACTOR_LAB_REPORT_DIR = Path(__file__).resolve().parent.parent / "results" / "quant-factor-mining" / "reports" / "factor_lab"
FACTOR_LAB_TRACKED_ARTIFACTS = ("latest_scores.csv", "latest_model.joblib", "latest_manifest.json")
MARKET_WARMUP_THREAD = None
BACKTEST_JOBS_LOCK = threading.Lock()
BACKTEST_JOBS: Dict[str, Dict[str, object]] = {}
BACKTEST_JOB_TTL_SECONDS = 60 * 60  # 1 hour
COMPARE_JOBS_LOCK = threading.Lock()
COMPARE_JOBS: Dict[str, Dict[str, object]] = {}
COMPARE_JOB_TTL_SECONDS = 60 * 60  # 1 hour
FACTOR_LAB_USER_VIEW_META = {
    "ml_factor_ranker": {
        "name_cn": "排序策略",
        "description_cn": "按综合因子分数从高到低挑出当天最强的一组股票，偏向抓住相对更强的机会。",
        "focus_points": [
            "优先看综合因子得分排名，强调谁更靠前。",
            "更关注收益弹性，通常触发更频繁，对换手和成本更敏感。",
        ],
        "suitable_for": [
            "想先看综合收益和弹性的人。",
            "能接受一定波动，希望从大池子里挑前排标的的人。",
        ],
    },
    "ml_factor_filter": {
        "name_cn": "筛选策略",
        "description_cn": "先用较高阈值过滤出高置信度股票，再做更克制的入场，偏向少做但做得更稳。",
        "focus_points": [
            "更看重信号纯度和过滤门槛，不追求每天都出手。",
            "通常触发频率更低，但更强调命中质量和回撤控制。",
        ],
        "suitable_for": [
            "更在意少出手、只看高置信度机会的人。",
            "希望先看稳健度，再看收益空间的人。",
        ],
    },
}


def _execute_virtual_trade_locked() -> Dict[str, object]:
    if not VIRTUAL_TRADE_EXECUTE_LOCK.acquire(blocking=False):
        raise RuntimeError("virtual trading simulation is already running")
    try:
        return vt_manager.execute_daily()
    finally:
        VIRTUAL_TRADE_EXECUTE_LOCK.release()


def _number_or_none(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            cleaned = value.replace("%", "").replace(",", "").strip()
            if cleaned in {"", "-", "--", "nan", "None"}:
                return None
            value = cleaned
        parsed = float(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _quote_symbol_from_row(row: Dict[str, object]) -> str:
    raw = row.get("代码") or row.get("stock_code") or row.get("symbol") or row.get("code")
    text = str(raw or "").strip()
    if "." in text:
        text = text.split(".")[-1]
    return text.zfill(6) if text.isdigit() and len(text) < 6 else text


def _snapshot_price_from_row(row: Dict[str, object]) -> Optional[float]:
    for key in ("最新价", "current_price", "price", "close", "收盘", "最新"):
        price = _number_or_none(row.get(key))
        if price is not None:
            return price
    return None


def _latest_snapshot_quote_payload() -> Dict[str, object]:
    snapshot = automation_store.latest_snapshot(include_rows=True)
    if not snapshot:
        return {"snapshot": None, "price_map": {}, "top_movers": []}

    rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
    price_map: Dict[str, float] = {}
    top_movers: List[Dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = _quote_symbol_from_row(row)
        price = _snapshot_price_from_row(row)
        if symbol and price is not None:
            price_map[symbol] = price
        if len(top_movers) < 8:
            top_movers.append(
                {
                    "symbol": symbol,
                    "name": row.get("名称") or row.get("stock_name") or row.get("name") or symbol,
                    "price": price,
                    "pct_chg": row.get("涨跌幅") or row.get("pct_chg") or row.get("change_pct"),
                }
            )

    snapshot_meta = {key: value for key, value in snapshot.items() if key != "rows"}
    return {"snapshot": snapshot_meta, "price_map": price_map, "top_movers": top_movers}


def _virtual_accounts_with_intraday_snapshot() -> List[Dict[str, object]]:
    payload = _latest_snapshot_quote_payload()
    price_map = payload.get("price_map")
    snapshot = payload.get("snapshot")
    if isinstance(price_map, dict) and price_map and isinstance(snapshot, dict):
        return vt_manager.get_accounts(price_overrides=price_map, valuation_meta=snapshot)
    return vt_manager.get_accounts()


def _intraday_snapshot_context(accounts: Optional[List[Dict[str, object]]] = None) -> Dict[str, object]:
    payload = _latest_snapshot_quote_payload()
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        return {"available": False, "message": "暂无盘中快照。"}
    accounts = accounts if accounts is not None else _virtual_accounts_with_intraday_snapshot()
    total_positions = sum(int(account.get("snapshot_total_positions") or 0) for account in accounts)
    priced_positions = sum(int(account.get("snapshot_price_count") or 0) for account in accounts)
    accounts_marked = sum(1 for account in accounts if account.get("valuation_source") == "intraday_snapshot")
    coverage = priced_positions / total_positions if total_positions > 0 else 0.0
    return {
        "available": True,
        "snapshot_id": snapshot.get("snapshot_id"),
        "captured_at": snapshot.get("captured_at"),
        "market_session": snapshot.get("market_session"),
        "row_count": snapshot.get("row_count"),
        "source": snapshot.get("source"),
        "price_count": len(payload.get("price_map") or {}),
        "top_movers": payload.get("top_movers") or [],
        "valuation": {
            "accounts_marked": accounts_marked,
            "positions_priced": priced_positions,
            "positions_total": total_positions,
            "coverage": coverage,
            "source": "intraday_snapshot" if accounts_marked else "snapshot_without_position_overlap",
        },
    }


def _generate_ai_report_payload(params: Dict[str, object]) -> Dict[str, object]:
    mode = str(params.get("mode") or "daily_report") if isinstance(params, dict) else "daily_report"
    accounts = _virtual_accounts_with_intraday_snapshot()
    intraday_snapshot = _intraday_snapshot_context(accounts)
    valuation = intraday_snapshot.get("valuation") if isinstance(intraday_snapshot.get("valuation"), dict) else {}
    if intraday_snapshot.get("available"):
        message = (
            f"{mode} 已记录。最新盘中快照 {intraday_snapshot.get('captured_at')}，"
            f"覆盖持仓 {valuation.get('positions_priced', 0)}/{valuation.get('positions_total', 0)}，"
            f"用于模拟盘盘中估值展示。"
        )
    else:
        message = f"{mode} 已记录。当前没有可用盘中快照，模拟盘仍按最近收盘价估值。"
    return {
        "status": "recorded",
        "mode": mode,
        "message": message,
        "data_freshness": data_lake_service.data_freshness(max_scan=300),
        "intraday_snapshot": intraday_snapshot,
        "top_accounts": accounts[:5],
    }


def _build_ai_context() -> Dict[str, object]:
    try:
        latest_factor_lab = load_latest_factor_lab_result()
        factor_summary = latest_factor_lab.get("summary", {}) if isinstance(latest_factor_lab, dict) else {}
    except Exception as exc:
        factor_summary = {"status": "unavailable", "error": str(exc)}
    virtual_accounts = _virtual_accounts_with_intraday_snapshot()
    intraday_snapshot = _intraday_snapshot_context(virtual_accounts)
    return {
        "system": {
            "engine_version": "Gemini Quant Pro V4.6 (Lake Routed)",
            "market_status": data_manager.get_market_status(),
            "local_a_share_files": len(data_manager.list_local_codes("a_share")),
            "local_etf_files": len(data_manager.list_local_codes("etf")),
        },
        "data_freshness": data_lake_service.data_freshness(max_scan=300),
        "virtual_trading": {
            "accounts": virtual_accounts,
            "recent_trades": vt_manager.get_trade_log(limit=20, offset=0),
            "valuation_note": "账户 total_value/return_rate 会在有盘中快照覆盖持仓时使用 intraday_snapshot 临时盯市；历史 K 线和 daily_stats 不被污染。",
        },
        "intraday_snapshot": intraday_snapshot,
        "strategy_versions": strategy_version_store.list_recent_versions(limit=10),
        "factor_lab": {
            "artifact_status": get_factor_lab_artifact_status(),
            "summary": factor_summary,
        },
        "automation": {
            "recent_runs": automation_store.list_runs(limit=10),
            "recent_snapshots": automation_store.latest_snapshots(limit=5),
            "recent_ai_decisions": automation_store.list_ai_decisions(limit=5),
            "recent_ai_work_logs": automation_store.list_ai_work_logs(limit=5),
            "recent_ai_work_messages": automation_store.list_ai_work_messages(limit=10),
        },
        "guardrails": {
            "scope": "virtual_trading_and_factor_lab_only",
            "forbidden": ["real_trade", "broker_order", "delete_data", "write_code", "bypass_guardrails"],
            "allowed_actions": allowed_action_catalog(),
        },
    }


automation_orchestrator = AutomationOrchestrator(
    store=automation_store,
    data_manager=data_manager,
    data_lake_service=data_lake_service,
    ai_service=ai_automation_service,
    virtual_trade_runner=_execute_virtual_trade_locked,
    context_builder=_build_ai_context,
)
automation_scheduler = LightweightScheduler(automation_orchestrator)


def _factor_lab_availability_cutoff(end_date: Optional[str]) -> Optional[str]:
    if not end_date:
        return None
    try:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        return None
    return (end_dt - timedelta(days=CACHE_EDGE_TOLERANCE_DAYS)).strftime("%Y-%m-%d")


def _factor_lab_warmup_start(start_date: Optional[str]) -> Optional[str]:
    if not start_date:
        return None
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError:
        return None
    return (start_dt - timedelta(days=FACTOR_LAB_WARMUP_DAYS)).strftime("%Y-%m-%d")


def _unique_factor_lab_symbols(frame: Optional[pd.DataFrame]) -> List[str]:
    if frame is None or frame.empty or "stock_code" not in frame.columns:
        return []
    symbols = frame["stock_code"].dropna().map(normalize_symbol).dropna().unique().tolist()
    return sorted(symbol for symbol in symbols if symbol)


def load_latest_result(*args, **kwargs):
    from factor_lab.pipeline import load_latest_result as _load_latest_result

    return _load_latest_result(*args, **kwargs)


def run_factor_lab(df, config, write_latest_summary=False):
    from factor_lab.pipeline import run_factor_lab as _run_factor_lab

    return _run_factor_lab(df, config, write_latest_summary=write_latest_summary)


def load_latest_factor_lab_result():
    return load_latest_result()


def build_factor_lab_config(**kwargs):
    from factor_lab.pipeline import FactorLabConfig

    return FactorLabConfig(**kwargs)


def execute_factor_lab_pipeline(df, config, write_latest_summary=False):
    return run_factor_lab(df, config, write_latest_summary=write_latest_summary)


def build_factor_lab_self_iteration(result: Dict[str, object], report_dir: Path = FACTOR_LAB_REPORT_DIR):
    from factor_lab.self_iteration import build_self_iteration_report

    return build_self_iteration_report(result, report_dir / "self_iteration")


def run_factor_lab_stress_pipeline(df, config, report_dir: Path = FACTOR_LAB_REPORT_DIR):
    from factor_lab.stress_test import run_factor_lab_stress_test

    return run_factor_lab_stress_test(df, config, report_dir / "stress_test")


def load_latest_factor_lab_stress_result(report_dir: Path = FACTOR_LAB_REPORT_DIR):
    from factor_lab.stress_test import load_latest_stress_test

    return load_latest_stress_test(report_dir / "stress_test")


def _latest_overview_symbols() -> List[str]:
    return dedupe_symbols(STOCK_POOL + ETF_POOL + BLACKHORSE_POOL + POWER_ENERGY_POOL)


def _warm_latest_market_cache():
    try:
        data_manager.get_latest_market_overview(_latest_overview_symbols(), limit=10)
        warmed = data_manager.warm_cached_frames(ETF_POOL)
        logger.info(f"ETF cached frame warmup completed: {warmed}/{len(ETF_POOL)}")
    except Exception as exc:
        logger.warning(f"Latest market cache warmup failed: {exc}")


@app.on_event("startup")
def start_latest_market_warmup():
    global MARKET_WARMUP_THREAD
    _configure_ai_handlers()
    if MARKET_WARMUP_THREAD is not None and MARKET_WARMUP_THREAD.is_alive():
        pass
    else:
        MARKET_WARMUP_THREAD = threading.Thread(target=_warm_latest_market_cache, daemon=True)
        MARKET_WARMUP_THREAD.start()
    if not os.getenv("PYTEST_CURRENT_TEST"):
        automation_scheduler.start()


@app.on_event("shutdown")
def stop_automation_scheduler():
    automation_scheduler.stop()


class BacktestRequest(BaseModel):
    start_date: str
    end_date: str
    initial_capital: float = Field(gt=0, le=1_000_000_000)
    stocks: Optional[List[str]] = None
    max_symbols: Optional[int] = Field(default=None, ge=1, le=BACKTEST_MAX_SYMBOLS)
    factor: str = "bottom_fishing"
    pool: str = "auto"

    max_positions: int = Field(default=5, ge=1, le=50)
    weight_mode: str = "equal"
    max_hold_days: Optional[int] = Field(default=None, ge=1, le=260)

    stop_loss: float = Field(default=-0.08, gt=-1.0, lt=0.0)
    take_profit: Optional[float] = Field(default=None, gt=0.0, le=10.0)
    circuit_breaker: float = Field(default=-0.15, gt=-1.0, lt=0.0)
    commission_rate: float = Field(default=0.0003, ge=0.0, le=0.1)
    stamp_tax_rate: float = Field(default=0.001, ge=0.0, le=0.1)
    slippage_rate: float = Field(default=0.0003, ge=0.0, le=0.1)
    commission_min: float = Field(default=5.0, ge=0.0, le=1000.0)
    allow_mock: bool = False


class BacktestJobSubmitResponse(BaseModel):
    job_id: str


class BacktestJobStatusResponse(BaseModel):
    job_id: str
    status: str
    created_at: float
    updated_at: float
    error: Optional[str] = None


def _cleanup_backtest_jobs(now: Optional[float] = None) -> None:
    ts = now if now is not None else time.time()
    with BACKTEST_JOBS_LOCK:
        expired = [
            job_id
            for job_id, job in BACKTEST_JOBS.items()
            if ts - float(job.get("updated_at", job.get("created_at", ts))) > BACKTEST_JOB_TTL_SECONDS
        ]
        for job_id in expired:
            BACKTEST_JOBS.pop(job_id, None)


def _create_backtest_job(req: BacktestRequest) -> str:
    job_id = uuid.uuid4().hex
    ts = time.time()
    with BACKTEST_JOBS_LOCK:
        BACKTEST_JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "created_at": ts,
            "updated_at": ts,
            "error": None,
            "result": None,
            "request": req.model_dump(),
        }
    return job_id


def _set_backtest_job(job_id: str, **updates: object) -> None:
    ts = time.time()
    with BACKTEST_JOBS_LOCK:
        job = BACKTEST_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updated_at"] = ts


def _get_backtest_job(job_id: str) -> Optional[Dict[str, object]]:
    with BACKTEST_JOBS_LOCK:
        job = BACKTEST_JOBS.get(job_id)
        return dict(job) if job else None


def _run_backtest_job(job_id: str) -> None:
    job = _get_backtest_job(job_id)
    if not job:
        return
    try:
        _set_backtest_job(job_id, status="running")
        req_data = job.get("request") or {}
        req = BacktestRequest(**req_data)
        result = execute_backtest(req, allow_mock=bool(req.allow_mock))
        _set_backtest_job(job_id, status="succeeded", result=result)
    except Exception as exc:
        _set_backtest_job(job_id, status="failed", error=str(exc))


def _cleanup_compare_jobs(now: Optional[float] = None) -> None:
    ts = now if now is not None else time.time()
    with COMPARE_JOBS_LOCK:
        expired = [
            job_id
            for job_id, job in COMPARE_JOBS.items()
            if ts - float(job.get("updated_at", job.get("created_at", ts))) > COMPARE_JOB_TTL_SECONDS
        ]
        for job_id in expired:
            COMPARE_JOBS.pop(job_id, None)


def _create_compare_job(req: "CompareRequest") -> str:
    job_id = uuid.uuid4().hex
    ts = time.time()
    with COMPARE_JOBS_LOCK:
        COMPARE_JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "created_at": ts,
            "updated_at": ts,
            "error": None,
            "result": None,
            "request": req.model_dump(),
        }
    return job_id


def _set_compare_job(job_id: str, **updates: object) -> None:
    ts = time.time()
    with COMPARE_JOBS_LOCK:
        job = COMPARE_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updated_at"] = ts


def _get_compare_job(job_id: str) -> Optional[Dict[str, object]]:
    with COMPARE_JOBS_LOCK:
        job = COMPARE_JOBS.get(job_id)
        return dict(job) if job else None


def _run_compare_job(job_id: str) -> None:
    job = _get_compare_job(job_id)
    if not job:
        return
    try:
        _set_compare_job(job_id, status="running")
        req_data = job.get("request") or {}
        req = CompareRequest(**req_data)
        result = execute_compare_request(req)
        _set_compare_job(job_id, status="succeeded", result=result)
    except Exception as exc:
        _set_compare_job(job_id, status="failed", error=str(exc))


class CompareRequest(BaseModel):
    strategies: List[str]
    start_date: str
    end_date: str
    initial_capital: float = Field(gt=0, le=1_000_000_000)
    stocks: Optional[List[str]] = None
    max_symbols: Optional[int] = Field(default=None, ge=1, le=BACKTEST_MAX_SYMBOLS)
    pool: str = "auto"
    max_positions: int = Field(default=5, ge=1, le=50)
    weight_mode: str = "equal"
    max_hold_days: Optional[int] = Field(default=None, ge=1, le=260)
    stop_loss: float = Field(default=-0.08, gt=-1.0, lt=0.0)
    take_profit: Optional[float] = Field(default=None, gt=0.0, le=10.0)
    circuit_breaker: float = Field(default=-0.15, gt=-1.0, lt=0.0)
    commission_rate: float = Field(default=0.0003, ge=0.0, le=0.1)
    stamp_tax_rate: float = Field(default=0.001, ge=0.0, le=0.1)
    slippage_rate: float = Field(default=0.0003, ge=0.0, le=0.1)
    commission_min: float = Field(default=5.0, ge=0.0, le=1000.0)
    allow_mock: bool = False


class FactorLabRunRequest(BaseModel):
    start_date: str
    end_date: str
    pool: str = "core"
    label: str = "next_5d_ret"
    top_n: int = Field(default=5, ge=1, le=50)
    max_symbols: Optional[int] = Field(default=None, ge=1, le=FACTOR_LAB_MAX_SYMBOLS)
    initial_capital: float = Field(default=1000000.0, gt=0, le=1_000_000_000)
    stop_loss: float = Field(default=-0.08, gt=-1.0, lt=0.0)
    circuit_breaker: float = Field(default=-0.15, gt=-1.0, lt=0.0)
    commission_rate: float = Field(default=0.0003, ge=0.0, le=0.1)
    stamp_tax_rate: float = Field(default=0.001, ge=0.0, le=0.1)
    slippage_rate: float = Field(default=0.0003, ge=0.0, le=0.1)
    commission_min: float = Field(default=5.0, ge=0.0, le=1000.0)


class FactorLabBacktestRequest(BacktestRequest):
    factor: str = "ml_factor_ranker"
    label: str = "next_5d_ret"
    top_n: int = Field(default=5, ge=1, le=50)


class FactorLabStressTestRequest(BaseModel):
    pool: str = "core"
    max_symbols: int = Field(default=300, ge=3, le=FACTOR_LAB_MAX_SYMBOLS)
    top_n: int = Field(default=5, ge=1, le=50)
    initial_capital: float = Field(default=1000000.0, gt=0, le=1_000_000_000)
    factors: List[str] = Field(default_factory=lambda: ["ml_factor_ranker"])
    horizon_days: int = Field(default=252, ge=20, le=260)
    paths_per_scenario: int = Field(default=2, ge=1, le=200)
    seed: int = 42
    scenarios: List[str] = Field(default_factory=lambda: ["bull", "bear", "sideways"])
    anchor_date: Optional[str] = None
    lookback_days: int = Field(default=260, ge=90, le=520)
    commission_rate: float = Field(default=0.0003, ge=0.0, le=0.1)
    stamp_tax_rate: float = Field(default=0.001, ge=0.0, le=0.1)
    slippage_rate: float = Field(default=0.0003, ge=0.0, le=0.1)
    stop_loss: float = Field(default=-0.08, gt=-1.0, lt=0.0)
    circuit_breaker: float = Field(default=-0.15, gt=-1.0, lt=0.0)


class FactorLabPromoteRequest(BaseModel):
    strategy_id: str = "ai_ml"
    candidate_factor: str = "ml_factor_ranker"
    created_by: str = "local_user"
    note: str = ""


class FactorLabArtifactCleanupRequest(BaseModel):
    keep_recent_runs: int = Field(default=FACTOR_LAB_KEEP_RECENT_RUNS, ge=1, le=50)
    dry_run: bool = False
    delete_training_sample: bool = False


class StrategyVersionActionRequest(BaseModel):
    user: str = "local_user"
    note: str = ""


class StrategyVersionIterateRequest(BaseModel):
    user: str = "local_user"
    note: str = ""


class StrategyActivateVersionRequest(BaseModel):
    version_id: str
    user: str = "local_user"
    note: str = ""


class StrategyRollbackRequest(BaseModel):
    user: str = "local_user"
    reason: str = ""


class AutomationSnapshotRequest(BaseModel):
    limit: int = Field(default=6000, ge=1, le=8000)


class AutomationEodUpdateRequest(BaseModel):
    target_date: Optional[str] = None
    dry_run: bool = False
    buffer_days: int = Field(default=7, ge=1, le=60)
    workers_a_share: int = Field(default=6, ge=1, le=16)
    workers_etf: int = Field(default=4, ge=1, le=12)
    retry: int = Field(default=3, ge=1, le=5)
    task_timeout: int = Field(default=90, ge=10, le=600)
    limit_a_share: int = Field(default=0, ge=0, le=10000)
    limit_etf: int = Field(default=0, ge=0, le=2000)
    skip_a_share: bool = False
    skip_etf: bool = False


class AIDecisionAction(BaseModel):
    type: str
    params: Dict[str, object] = Field(default_factory=dict)


class AIDecisionRequest(BaseModel):
    decision_id: Optional[str] = None
    actor: str = "external_ai"
    source: str = "external_ai"
    summary: str = ""
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    actions: List[AIDecisionAction] = Field(default_factory=list)
    dry_run: bool = False


class AutomationAICycleRequest(BaseModel):
    decision: Optional[AIDecisionRequest] = None
    dry_run: bool = False


class AutomationAIManagedWorkRequest(BaseModel):
    work_type: str = "simulation_supervision"
    decision: Optional[AIDecisionRequest] = None
    dry_run: bool = False


def _configure_ai_handlers() -> None:
    automation_orchestrator.set_ai_handlers(
        {
            "run_virtual_trade": lambda params: automation_orchestrator.run_virtual_trade(trigger="ai"),
            "check_data_integrity": lambda params: data_lake_service.data_freshness(
                target_date=params.get("target_date") if isinstance(params, dict) else None,
                max_scan=int(params.get("max_scan") or 500) if isinstance(params, dict) else 500,
            ),
            "trigger_eod_update": lambda params: automation_orchestrator.run_eod_update(
                trigger="ai",
                target_date=params.get("target_date") if isinstance(params, dict) else None,
                dry_run=bool(params.get("dry_run", False)) if isinstance(params, dict) else False,
                limit_a_share=int(params.get("limit_a_share") or 0) if isinstance(params, dict) else 0,
                limit_etf=int(params.get("limit_etf") or 0) if isinstance(params, dict) else 0,
                skip_a_share=bool(params.get("skip_a_share", False)) if isinstance(params, dict) else False,
                skip_etf=bool(params.get("skip_etf", False)) if isinstance(params, dict) else False,
            ),
            "realtime_snapshot": lambda params: automation_orchestrator.run_realtime_snapshot(
                trigger="ai",
                limit=int(params.get("limit") or 200) if isinstance(params, dict) else 200,
            ),
            "run_factor_lab": lambda params: run_factor_lab_api(FactorLabRunRequest(**params)),
            "run_factor_lab_backtest": lambda params: run_factor_lab_backtest(FactorLabBacktestRequest(**params)),
            "run_factor_lab_stress_test": lambda params: run_factor_lab_stress_test_api(FactorLabStressTestRequest(**params)),
            "promote_factor_lab_candidate": lambda params: promote_factor_lab_candidate(
                str(params["run_id"]),
                FactorLabPromoteRequest(
                    strategy_id=str(params.get("strategy_id") or "ai_ml"),
                    candidate_factor=str(params.get("candidate_factor") or "ml_factor_ranker"),
                    created_by=str(params.get("created_by") or params.get("user") or "ai"),
                    note=str(params.get("note") or "AI promoted Factor Lab candidate"),
                ),
            ),
            "start_shadow_observation": lambda params: {
                "version": strategy_version_store.start_shadow(
                    str(params["version_id"]),
                    started_by=str(params.get("user") or "ai"),
                    note=str(params.get("note") or "AI requested shadow observation"),
                )
            },
            "approve_strategy_version": lambda params: {
                "version": strategy_version_store.approve(
                    str(params["version_id"]),
                    approved_by=str(params.get("user") or "ai"),
                    note=str(params.get("note") or "AI requested approval"),
                )
            },
            "activate_strategy_version": lambda params: strategy_version_store.activate(
                str(params["strategy_id"]),
                str(params["version_id"]),
                switched_by=str(params.get("user") or "ai"),
                note=str(params.get("note") or "AI requested activation"),
            ),
            "generate_daily_report": lambda params: _generate_ai_report_payload(params if isinstance(params, dict) else {}),
        }
    )


def normalize_symbol(symbol: str) -> str:
    text = str(symbol or "").strip()
    return text.zfill(6) if text.isdigit() and len(text) < 6 else text


def dedupe_symbols(symbols: List[str]) -> List[str]:
    seen = set()
    ordered = []
    for symbol in symbols:
        code = normalize_symbol(symbol)
        if not code or code in seen:
            continue
        seen.add(code)
        ordered.append(code)
    return ordered


def get_strategy_pool_name(factor: str, requested_pool: str) -> str:
    info = strategy_version_store.resolve_strategy_spec(factor)
    if info:
        return info.pool
    return "etf" if requested_pool == "etf" else "core"


def get_asset_class_from_strategy(factor: str, requested_pool: str) -> str:
    return "etf" if get_strategy_pool_name(factor, requested_pool) == "etf" else "a_share"


def resolve_effective_pool(requested_pool: str, factor: str) -> dict:
    strategy_pool = get_strategy_pool_name(factor, requested_pool)
    asset_class = "etf" if strategy_pool == "etf" else "a_share"

    if asset_class == "etf":
        effective_pool = "all" if requested_pool == "all" else "etf"
    else:
        if requested_pool in {"core", "blackhorse", "all"}:
            effective_pool = requested_pool
        else:
            effective_pool = strategy_pool

    return {
        "strategy_pool": strategy_pool,
        "asset_class": asset_class,
        "effective_pool": effective_pool,
    }


def validate_custom_symbols(symbols: List[str], asset_class: str) -> List[str]:
    normalized = dedupe_symbols(symbols)
    invalid = []
    for code in normalized:
        is_etf = data_manager.is_etf_symbol(code)
        if asset_class == "etf" and not is_etf:
            invalid.append(code)
        if asset_class == "a_share" and is_etf:
            invalid.append(code)
    if invalid:
        expected = "ETF" if asset_class == "etf" else "A股"
        raise HTTPException(
            status_code=400,
            detail=f"自选代码与策略数据池不匹配，当前策略只允许 {expected} 标的: {', '.join(invalid[:10])}",
        )
    return normalized


def get_symbols_for_pool(pool_name: str, asset_class: str) -> List[str]:
    if asset_class == "etf":
        if pool_name == "all":
            return data_manager.list_local_codes("etf") or ETF_POOL
        return ETF_POOL

    if pool_name == "all":
        local_codes = data_manager.list_local_codes("a_share")
        if local_codes:
            return local_codes
        return dedupe_symbols(STOCK_POOL + BLACKHORSE_POOL + POWER_ENERGY_POOL)

    if pool_name == "blackhorse":
        return BLACKHORSE_POOL
    if pool_name == "power_energy":
        return POWER_ENERGY_POOL
    return STOCK_POOL


def resolve_symbols(
    req: BacktestRequest,
    min_end_date: Optional[str] = None,
    min_start_date: Optional[str] = None,
) -> tuple[List[str], dict]:
    pool_ctx = resolve_effective_pool(req.pool, req.factor)
    requested_max_symbols = req.max_symbols if req.max_symbols is not None and req.max_symbols > 0 else None
    pool_ctx["requested_max_symbols"] = requested_max_symbols
    pool_ctx["budget_truncated"] = False

    if requested_max_symbols is not None and requested_max_symbols > BACKTEST_MAX_SYMBOLS:
        raise HTTPException(
            status_code=413,
            detail=f"max_symbols={requested_max_symbols} 超过单次回测上限 {BACKTEST_MAX_SYMBOLS}。请缩小样本或拆分任务。",
        )

    if req.stocks:
        symbols = validate_custom_symbols(req.stocks, pool_ctx["asset_class"])
        pool_ctx["symbols_before_budget"] = len(symbols)
        pool_ctx["selection_method"] = "explicit_stocks"
        if len(symbols) > BACKTEST_MAX_SYMBOLS:
            raise HTTPException(
                status_code=413,
                detail=f"回测股票数 {len(symbols)} 超过单次上限 {BACKTEST_MAX_SYMBOLS}，请缩小自选股票列表。",
            )
    else:
        if pool_ctx["effective_pool"] == "all" and pool_ctx["asset_class"] == "a_share":
            all_symbols = dedupe_symbols(get_symbols_for_pool("all", "a_share"))
            sample_limit = requested_max_symbols or BACKTEST_MAX_SYMBOLS
            selected_symbols = data_manager.select_local_a_share_symbols(
                sample_limit,
                min_end_date=min_end_date,
                min_start_date=min_start_date,
                allow_late_start=True,
            )
            symbols = dedupe_symbols(selected_symbols or all_symbols[:sample_limit])[:sample_limit]
            selection_metadata = data_manager.get_last_symbol_selection_metadata()
            pool_ctx.update(
                {
                    **selection_metadata,
                    "symbols_before_budget": len(all_symbols),
                    "selection_method": "full_market_backtest_prescreen_v2",
                    "method_cn": "全A轻量预筛：历史覆盖 + 流动性优先",
                    "local_universe_size": len(all_symbols),
                    "prescreen_universe_size": len(all_symbols),
                    "requested_max_symbols": sample_limit,
                    "budget_truncated": len(all_symbols) > len(symbols),
                    "is_budget_sample": len(all_symbols) > len(symbols),
                    "deep_scored_all_symbols": False,
                    "availability_cutoff": min_end_date,
                    "history_coverage_start": min_start_date,
                    "allow_late_start": True,
                    "sample_source_note": (
                        f"本次先从本地 {len(all_symbols)} 只 A 股做轻量预筛，"
                        f"选出 {len(symbols)} 只进入深度回测。"
                    ),
                }
            )
        else:
            symbols = dedupe_symbols(get_symbols_for_pool(pool_ctx["effective_pool"], pool_ctx["asset_class"]))
            pool_ctx["symbols_before_budget"] = len(symbols)

    if not req.stocks and requested_max_symbols is not None and pool_ctx.get("selection_method") != "full_market_backtest_prescreen_v2":
        if len(symbols) > requested_max_symbols:
            symbols = symbols[:requested_max_symbols]
            pool_ctx["budget_truncated"] = True

    if len(symbols) > BACKTEST_MAX_SYMBOLS:
        hint = "pool=all 需要传 max_symbols 或显式 stocks" if pool_ctx["effective_pool"] == "all" and not req.stocks else "请缩小股票池"
        raise HTTPException(
            status_code=413,
            detail=f"回测股票数 {len(symbols)} 超过单次上限 {BACKTEST_MAX_SYMBOLS}，{hint}。",
        )

    pool_ctx["symbols_count"] = len(symbols)
    return symbols, pool_ctx


def prepare_backtest_universe(req: BacktestRequest) -> tuple[List[str], dict, str]:
    try:
        start_dt = datetime.strptime(req.start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(req.end_date, "%Y-%m-%d")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"日期格式错误: {e}")

    if end_dt < start_dt:
        raise HTTPException(status_code=400, detail="结束日期不能早于开始日期。")

    requested_days = (end_dt - start_dt).days + 1
    if requested_days > BACKTEST_MAX_DAYS:
        raise HTTPException(
            status_code=413,
            detail=f"回测跨度 {requested_days} 天超过单次上限 {BACKTEST_MAX_DAYS} 天，请缩短区间或拆分运行。",
        )

    warmup_start = (start_dt - timedelta(days=BACKTEST_WARMUP_DAYS)).strftime("%Y-%m-%d")
    current_pool, pool_ctx = resolve_symbols(
        req,
        min_end_date=req.end_date,
        min_start_date=warmup_start,
    )

    estimated_rows = len(current_pool) * (requested_days + BACKTEST_WARMUP_DAYS)
    if estimated_rows > BACKTEST_MAX_ROWS:
        raise HTTPException(
            status_code=413,
            detail=f"预计处理 {estimated_rows:,} 行行情，超过单次预算 {BACKTEST_MAX_ROWS:,} 行。请降低 max_symbols 或缩短日期。",
        )

    pool_ctx["requested_days"] = requested_days
    pool_ctx["warmup_days"] = BACKTEST_WARMUP_DAYS
    pool_ctx["estimated_rows"] = estimated_rows
    return current_pool, pool_ctx, warmup_start


def resolve_factor_lab_symbols(
    pool_name: str,
    max_symbols: Optional[int],
    end_date: Optional[str] = None,
    start_date: Optional[str] = None,
) -> List[str]:
    normalized_pool = pool_name if pool_name != "auto" else "core"
    if normalized_pool == "etf":
        raise HTTPException(status_code=400, detail="Factor Lab 当前 MVP 仅支持 A股股票池。")

    requested_max = int(max_symbols) if max_symbols is not None and max_symbols > 0 else None
    if requested_max is not None and requested_max > FACTOR_LAB_MAX_SYMBOLS:
        raise HTTPException(
            status_code=413,
            detail=f"Factor Lab 单次最多处理 {FACTOR_LAB_MAX_SYMBOLS} 只股票，请降低 max_symbols 或拆分运行。",
        )

    if normalized_pool == "all":
        sample_size = requested_max or FACTOR_LAB_DEFAULT_ALL_SAMPLE
        availability_cutoff = _factor_lab_availability_cutoff(end_date)
        warmup_start = _factor_lab_warmup_start(start_date)
        symbols = (
            data_manager.select_local_a_share_symbols(
                sample_size,
                min_end_date=availability_cutoff,
                min_start_date=warmup_start,
            )
            or dedupe_symbols(get_symbols_for_pool("all", "a_share"))[:sample_size]
        )
        return symbols[:sample_size]

    symbols = dedupe_symbols(get_symbols_for_pool(normalized_pool, "a_share"))
    if requested_max is not None:
        symbols = symbols[:requested_max]
    if len(symbols) > FACTOR_LAB_MAX_SYMBOLS:
        raise HTTPException(
            status_code=413,
            detail=f"Factor Lab 股票数 {len(symbols)} 超过单次上限 {FACTOR_LAB_MAX_SYMBOLS}，请传 max_symbols 缩小样本。",
        )
    return symbols


def build_factor_lab_universe_metadata(
    pool_name: str,
    symbols: List[str],
    max_symbols: Optional[int],
    end_date: Optional[str] = None,
    start_date: Optional[str] = None,
    actual_symbols: Optional[List[str]] = None,
) -> Dict[str, object]:
    normalized_pool = pool_name if pool_name != "auto" else "core"
    local_count = data_manager.get_local_code_count("a_share")
    if normalized_pool == "all":
        sample_size = int(max_symbols or FACTOR_LAB_DEFAULT_ALL_SAMPLE)
        availability_cutoff = _factor_lab_availability_cutoff(end_date)
        warmup_start = _factor_lab_warmup_start(start_date)
        actual_symbol_count = len(actual_symbols or [])
        if actual_symbol_count:
            expected_symbols = set(symbols)
            observed_symbols = set(actual_symbols or [])
            if expected_symbols and observed_symbols and not observed_symbols.issubset(expected_symbols):
                return {
                    "universe": f"A股全市场历史研究样本（{actual_symbol_count}/{local_count}）",
                    "sample_source_note": (
                        f"这份报告来自已生成的历史研究样本，共 {actual_symbol_count} 只。"
                        f"重新运行后，系统会从本地 {local_count} 只 A 股按数据可用性和成交额做轻量预筛，"
                        f"再选 {sample_size} 只进入深度因子实验。历史报告不是对 5000 只股票逐只深度回测后的最终排名。"
                    ),
                    "universe_selection": {
                        "requested_pool": pool_name,
                        "selection_method": "saved_factor_lab_sample",
                        "method_cn": "已生成报告中的历史研究样本",
                        "local_universe_size": local_count,
                        "prescreen_universe_size": local_count,
                        "requested_max_symbols": sample_size,
                        "selected_symbols": actual_symbol_count,
                        "deep_research_symbols": actual_symbol_count,
                        "is_budget_sample": True,
                        "deep_scored_all_symbols": False,
                        "availability_cutoff": availability_cutoff,
                        "history_coverage_start": warmup_start,
                        "legacy_result": True,
                        "rerun_selection_method": "full_market_liquidity_prescreen",
                        "sample_refresh_rule": "重新运行后启用全市场轻量预筛；同一数据湖、同一日期窗口和同一样本上限下结果稳定。",
                    },
                }
        return {
            "universe": f"A股全市场轻量预筛样本（{len(symbols)}/{local_count}）",
            "sample_source_note": (
                f"本次先从本地 {local_count} 只 A 股按历史覆盖、成交额流动性、动量/波动风格分层做轻量预筛，选出 "
                f"{len(symbols)} 只研究样本进入深度因子实验，再在这 {len(symbols)} 只里评分选前排标的。"
                "它不是买入指令，也不是对 5000 只股票逐只深度回测后的最终排名。"
            ),
            "universe_selection": {
                "requested_pool": pool_name,
                "selection_method": "full_market_research_prescreen_v2",
                "method_cn": "全市场研究样本：历史覆盖 + 流动性优先 + 动量/波动风格分层",
                "local_universe_size": local_count,
                "prescreen_universe_size": local_count,
                "requested_max_symbols": sample_size,
                "selected_symbols": len(symbols),
                "deep_research_symbols": len(symbols),
                "is_budget_sample": True,
                "deep_scored_all_symbols": False,
                "availability_cutoff": availability_cutoff,
                "history_coverage_start": warmup_start,
                **data_manager.get_last_symbol_selection_metadata(),
                "sample_refresh_rule": data_manager.get_last_symbol_selection_metadata().get(
                    "sample_refresh_rule",
                    "同一数据湖、同一日期窗口和同一样本上限下结果稳定；数据更新或日期窗口变化时会重新预筛。",
                ),
            },
        }

    return {
        "universe": f"{normalized_pool} 固定股票池（{len(symbols)} 只）",
        "sample_source_note": f"本次使用系统内置 {normalized_pool} 股票池，共 {len(symbols)} 只标的，不代表买入推荐。",
        "universe_selection": {
            "requested_pool": pool_name,
            "selection_method": "predefined_pool",
            "method_cn": "系统内置固定股票池",
            "local_universe_size": local_count,
            "requested_max_symbols": max_symbols,
            "selected_symbols": len(symbols),
            "is_budget_sample": False,
        },
    }


def factor_lab_error_response(
    status_code: int,
    detail: str,
    error_code: str,
    *,
    run_readiness: Optional[Dict[str, object]] = None,
):
    payload = {
        "detail": detail,
        "error_code": error_code,
        "run_readiness": run_readiness,
    }
    return JSONResponse(status_code=status_code, content=payload)


def snapshot_factor_lab_artifacts(report_dir: Path = FACTOR_LAB_REPORT_DIR) -> Dict[str, object]:
    report_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = Path(tempfile.mkdtemp(prefix="factor-lab-artifacts-"))
    backups = {}
    for name in FACTOR_LAB_TRACKED_ARTIFACTS:
        target = report_dir / name
        if target.exists():
            backup = backup_dir / name
            shutil.copy2(target, backup)
            backups[str(target)] = str(backup)
        else:
            backups[str(target)] = None
    return {
        "backup_dir": str(backup_dir),
        "files": backups,
    }


def restore_factor_lab_artifacts(snapshot: Optional[Dict[str, object]]) -> None:
    if not snapshot:
        return
    files = snapshot.get("files", {})
    for target_str, backup_str in files.items():
        target = Path(target_str)
        if backup_str:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup_str, target)
        elif target.exists():
            target.unlink()
    backup_dir = snapshot.get("backup_dir")
    if backup_dir:
        shutil.rmtree(backup_dir, ignore_errors=True)


def clear_factor_lab_artifact_snapshot(snapshot: Optional[Dict[str, object]]) -> None:
    if not snapshot:
        return
    backup_dir = snapshot.get("backup_dir")
    if backup_dir:
        shutil.rmtree(backup_dir, ignore_errors=True)


def materialize_factor_lab_run_archive(result: Dict[str, object], report_dir: Path = FACTOR_LAB_REPORT_DIR) -> Dict[str, object]:
    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}
    run_id = str(summary.get("run_id") or "").strip()
    if not run_id:
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        result.setdefault("summary", {})["run_id"] = run_id

    run_dir = report_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    copied = {}
    for name in FACTOR_LAB_TRACKED_ARTIFACTS:
        source = report_dir / name
        if source.exists():
            target = run_dir / name
            shutil.copy2(source, target)
            copied[name] = str(target)

    fingerprint = artifact_fingerprint(str(run_dir))
    archive_manifest = {
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_report_dir": str(report_dir),
        "artifact_hash": fingerprint["artifact_hash"],
        "files": fingerprint["files"],
    }
    with (run_dir / "version_manifest.json").open("w", encoding="utf-8") as f:
        json.dump(archive_manifest, f, ensure_ascii=False, indent=2)

    artifacts = result.setdefault("artifacts", {})
    if isinstance(artifacts, dict):
        artifacts["run_dir"] = str(run_dir)
        artifacts["artifact_hash"] = fingerprint["artifact_hash"]
        artifacts["version_manifest_json"] = str(run_dir / "version_manifest.json")
        artifacts["immutable_files"] = copied
    summary_path = run_dir / "latest_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    copied["latest_summary.json"] = str(summary_path)
    if isinstance(artifacts, dict):
        artifacts["immutable_files"] = copied
    return result


def _path_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for filename in files:
            try:
                total += (Path(root) / filename).stat().st_size
            except OSError:
                continue
    return total


def _read_factor_lab_summary(report_dir: Path) -> Dict[str, object]:
    path = report_dir / "latest_summary.json"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _factor_lab_run_sort_key(run_dir: Path):
    try:
        mtime = run_dir.stat().st_mtime
    except OSError:
        mtime = 0
    return (mtime, run_dir.name)


def cleanup_factor_lab_artifacts(
    *,
    report_dir: Path = FACTOR_LAB_REPORT_DIR,
    keep_recent_runs: int = FACTOR_LAB_KEEP_RECENT_RUNS,
    dry_run: bool = False,
    delete_training_sample: bool = False,
) -> Dict[str, object]:
    report_dir = Path(report_dir)
    runs_dir = report_dir / "runs"
    summary = _read_factor_lab_summary(report_dir)
    current_run_id = str((summary.get("summary") or {}).get("run_id") or "") if isinstance(summary.get("summary"), dict) else ""
    protected_refs = []
    protected_run_names = set()
    protected_statuses = {"draft", "research_pass", "shadow", "approved", "active"}

    if current_run_id:
        protected_run_names.add(current_run_id)
        protected_refs.append(
            {
                "run_id": current_run_id,
                "reason": "current_latest",
                "artifact_ref": str(runs_dir / current_run_id),
            }
        )

    for ref in strategy_version_store.list_factor_lab_artifact_refs():
        status = str(ref.get("status") or "")
        if status not in protected_statuses:
            continue
        artifact_ref = Path(str(ref.get("artifact_ref") or ""))
        if not artifact_ref.name:
            continue
        try:
            artifact_ref.relative_to(runs_dir)
        except ValueError:
            continue
        protected_run_names.add(artifact_ref.name)
        protected_refs.append(
            {
                "run_id": artifact_ref.name,
                "reason": f"strategy_version:{status}",
                "version_id": ref.get("version_id"),
                "artifact_ref": str(artifact_ref),
            }
        )

    run_dirs = [path for path in runs_dir.iterdir() if path.is_dir()] if runs_dir.exists() else []
    recent_run_names = {path.name for path in sorted(run_dirs, key=_factor_lab_run_sort_key, reverse=True)[:keep_recent_runs]}
    retained_runs = []
    deleted_runs = []
    freed_bytes = 0

    for run_dir in sorted(run_dirs, key=_factor_lab_run_sort_key, reverse=True):
        size = _path_size_bytes(run_dir)
        reasons = []
        if run_dir.name in protected_run_names:
            reasons.append("protected")
        if run_dir.name in recent_run_names:
            reasons.append("recent")
        entry = {
            "run_id": run_dir.name,
            "path": str(run_dir),
            "size_bytes": size,
        }
        if reasons:
            retained_runs.append({**entry, "reasons": reasons})
            continue
        deleted_runs.append(entry)
        freed_bytes += size
        if not dry_run:
            shutil.rmtree(run_dir, ignore_errors=False)

    deleted_files = []
    training_sample = report_dir / "training_sample_scored.csv"
    if delete_training_sample and training_sample.exists() and training_sample.is_file():
        size = _path_size_bytes(training_sample)
        deleted_files.append(
            {
                "path": str(training_sample),
                "size_bytes": size,
                "reason": "training_sample_scored_latest_only",
            }
        )
        freed_bytes += size
        if not dry_run:
            training_sample.unlink()

    return {
        "report_dir": str(report_dir),
        "runs_dir": str(runs_dir),
        "dry_run": dry_run,
        "keep_recent_runs": keep_recent_runs,
        "delete_training_sample": delete_training_sample,
        "protected_refs": protected_refs,
        "retained_runs": retained_runs,
        "deleted_runs": deleted_runs,
        "deleted_files": deleted_files,
        "freed_bytes": 0 if dry_run else freed_bytes,
        "potential_freed_bytes": freed_bytes,
    }


def load_factor_lab_result_by_run_id(run_id: str) -> Dict[str, object]:
    current = load_latest_factor_lab_result()
    if isinstance(current, dict):
        summary = current.get("summary", {}) if isinstance(current.get("summary"), dict) else {}
        if str(summary.get("run_id") or "") == run_id:
            return current
    path = FACTOR_LAB_REPORT_DIR / "runs" / run_id / "latest_summary.json"
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        if isinstance(payload, dict):
            return payload
    raise HTTPException(status_code=404, detail=f"未找到 Factor Lab run: {run_id}")


def attach_factor_lab_lifecycle(result: Dict[str, object]) -> Dict[str, object]:
    if not isinstance(result, dict):
        return result
    summary = result.get("summary", {}) if isinstance(result.get("summary"), dict) else {}
    run_id = str(summary.get("run_id") or "")
    strategy_id = "ai_ml"
    versions = strategy_version_store.list_versions(strategy_id)
    current_versions = [
        version for version in versions
        if str(version.get("source_run_id") or "") == run_id
    ] if run_id else []
    active_version_id = strategy_version_store.get_active_version_id(strategy_id)
    promotion = result.get("self_iteration", {})
    decision = promotion.get("promotion_decision", {}) if isinstance(promotion, dict) else {}
    artifacts = result.get("artifacts", {}) if isinstance(result.get("artifacts"), dict) else {}
    has_run_archive = bool(artifacts.get("run_dir") or artifacts.get("report_dir"))
    active_version = next((version for version in versions if version.get("version_id") == active_version_id), None)
    primary_version = current_versions[0] if current_versions else active_version
    latest_iteration = strategy_version_store.get_latest_iteration(str(primary_version["version_id"])) if primary_version else None

    if active_version_id:
        status = "active"
        next_action = "当前已有 Factor Lab 版本接管父策略；继续观察虚拟交易对账，必要时回滚。"
    elif current_versions:
        latest_status = str(current_versions[0].get("status") or "draft")
        status = latest_status
        if latest_status == "research_pass":
            next_action = "研究层通过，可启动影子观察。"
        elif latest_status == "shadow":
            next_action = "等待影子观察账本累积交易日，再做审批。"
        elif latest_status == "approved":
            next_action = "审批已通过，可切换活动版本。"
        else:
            next_action = "候选版本已保存，等待下一轮验证或人工处理。"
    elif has_run_archive and decision.get("status") in {"research_pass", "shadow"}:
        status = "ready_to_promote"
        next_action = "可把本轮结果提升为 ai_ml 的候选策略版本。"
    else:
        status = "research_only"
        next_action = str(decision.get("next_action") or "继续运行研究、压力测评或等待更多样本。")
    if latest_iteration and status not in {"active", "approved"}:
        next_action = f"{next_action} 已生成定向迭代计划，可按阻塞项继续打磨当前候选。"

    result["strategy_lifecycle"] = {
        "status": status,
        "parent_strategy_id": strategy_id,
        "parent_strategy_name": STRATEGY_REGISTRY.get(strategy_id).name if strategy_id in STRATEGY_REGISTRY else strategy_id,
        "active_version_id": active_version_id,
        "current_run_id": run_id,
        "current_run_versions": current_versions,
        "recent_versions": versions[:8],
        "latest_iteration": latest_iteration,
        "next_action": next_action,
        "decision": decision,
    }
    return result


def _format_date(dt: Optional[datetime]) -> Optional[str]:
    return dt.strftime("%Y-%m-%d") if dt is not None else None


def build_factor_lab_run_readiness(req: FactorLabRunRequest, symbols: List[str]) -> Dict[str, object]:
    requested_start = datetime.strptime(req.start_date, "%Y-%m-%d")
    requested_end = datetime.strptime(req.end_date, "%Y-%m-%d")
    effective_warmup_start = requested_start - timedelta(days=FACTOR_LAB_WARMUP_DAYS)

    cache_starts: List[datetime] = []
    cache_ends: List[datetime] = []
    has_full_common_cache = True
    for symbol in symbols:
        cache_start, cache_end = data_manager.get_cached_window(symbol)
        if not cache_start or not cache_end:
            has_full_common_cache = False
            continue
        cache_starts.append(datetime.strptime(cache_start, "%Y-%m-%d"))
        cache_ends.append(datetime.strptime(cache_end, "%Y-%m-%d"))

    cache_window_start = max(cache_starts) if has_full_common_cache and cache_starts else None
    cache_window_end = min(cache_ends) if has_full_common_cache and cache_ends else None
    if cache_window_start and cache_window_end and cache_window_start > cache_window_end:
        cache_window_start = None
        cache_window_end = None

    tolerance = timedelta(days=CACHE_EDGE_TOLERANCE_DAYS)
    start_gap = cache_window_start is None or cache_window_start > effective_warmup_start + tolerance
    end_gap = cache_window_end is None or cache_window_end < requested_end - tolerance
    needs_backfill = start_gap or end_gap

    missing_start_dt: Optional[datetime] = None
    missing_end_dt: Optional[datetime] = None
    if needs_backfill:
        if start_gap and not end_gap and cache_window_start is not None:
            missing_start_dt = effective_warmup_start
            missing_end_dt = min(requested_end, cache_window_start - timedelta(days=1))
        elif end_gap and not start_gap and cache_window_end is not None:
            missing_start_dt = max(effective_warmup_start, cache_window_end + timedelta(days=1))
            missing_end_dt = requested_end
        else:
            missing_start_dt = effective_warmup_start
            missing_end_dt = requested_end
        if missing_start_dt and missing_end_dt and missing_start_dt > missing_end_dt:
            missing_start_dt = None
            missing_end_dt = None
            needs_backfill = False

    cache_window_start_str = _format_date(cache_window_start)
    cache_window_end_str = _format_date(cache_window_end)
    missing_start_str = _format_date(missing_start_dt)
    missing_end_str = _format_date(missing_end_dt)
    if not needs_backfill:
        warning_message = None
    elif cache_window_start_str and cache_window_end_str:
        warning_message = (
            f"当前本地缓存的公共覆盖区间为 {cache_window_start_str} 至 {cache_window_end_str}，"
            f"运行前需补数 {missing_start_str} 至 {missing_end_str}，涉及 {len(symbols)} 只股票。"
        )
    else:
        warning_message = (
            f"所选股票池尚未形成可直接运行的公共缓存覆盖区间，"
            f"运行前需补数 {missing_start_str} 至 {missing_end_str}，涉及 {len(symbols)} 只股票。"
        )

    return {
        "requested_start_date": req.start_date,
        "requested_end_date": req.end_date,
        "effective_warmup_start": _format_date(effective_warmup_start),
        "cache_window_start": cache_window_start_str,
        "cache_window_end": cache_window_end_str,
        "missing_start": missing_start_str,
        "missing_end": missing_end_str,
        "needs_backfill": needs_backfill,
        "warning_message": warning_message,
        "checked_symbols": symbols,
    }


def _display_signal_symbol(row: Dict[str, object]) -> str:
    stock_name = str(row.get("stock_name") or "").strip()
    stock_code = str(row.get("stock_code") or "").strip()
    if stock_name and stock_name != stock_code:
        return stock_name
    return stock_code or stock_name


def build_factor_lab_strategy_user_view(
    factor: str,
    signal_frame,
    comparison: Dict[str, object],
) -> Dict[str, object]:
    meta = FACTOR_LAB_USER_VIEW_META.get(
        factor,
        {
            "name_cn": factor,
            "description_cn": "基于当前研究结果生成的策略摘要。",
            "focus_points": [],
            "suitable_for": [],
        },
    )
    with_cost = comparison.get("with_cost", {})
    summary = with_cost.get("summary", {}) if isinstance(with_cost, dict) else {}

    if "signal" in signal_frame.columns:
        signaled = signal_frame[signal_frame["signal"] == 1].copy()
    else:
        signaled = signal_frame.iloc[0:0].copy()
    trigger_days = int(signaled["date"].nunique()) if not signaled.empty and "date" in signaled.columns else 0
    last_signal_date = None
    recent_signal_symbols: List[str] = []
    if not signaled.empty and "date" in signaled.columns:
        last_signal_date = str(signaled["date"].max())
        recent_rows = signaled[signaled["date"] == last_signal_date].copy()
        sort_cols = [column for column in ["daily_rank", "score", "stock_code"] if column in recent_rows.columns]
        ascending = [True, False, True][: len(sort_cols)]
        if sort_cols:
            recent_rows = recent_rows.sort_values(sort_cols, ascending=ascending)
        seen = set()
        for row in recent_rows.to_dict(orient="records"):
            label = _display_signal_symbol(row)
            if not label or label in seen:
                continue
            seen.add(label)
            recent_signal_symbols.append(label)
            if len(recent_signal_symbols) >= 5:
                break

    return {
        "name_cn": meta["name_cn"],
        "description_cn": meta["description_cn"],
        "focus_points": meta["focus_points"],
        "suitable_for": meta["suitable_for"],
        "total_return": float(with_cost.get("total_return", 0.0) or 0.0),
        "annual_return": float(summary.get("annual_return", 0.0) or 0.0),
        "max_drawdown": float(summary.get("max_drawdown", 0.0) or 0.0),
        "win_rate": float(summary.get("win_rate", 0.0) or 0.0),
        "trigger_days": trigger_days,
        "total_trades": int(summary.get("total_trades", 0) or 0),
        "last_signal_date": last_signal_date,
        "recent_signal_symbols": recent_signal_symbols,
        "cost_drag": comparison.get("cost_drag", {}),
    }


def attach_factor_lab_user_views(
    comparisons: Dict[str, Dict],
    market_df,
) -> Dict[str, Dict]:
    for factor, comparison in comparisons.items():
        strategy_spec = STRATEGY_REGISTRY.get(factor)
        if strategy_spec is None:
            continue
        try:
            signal_frame = strategy_spec.func(market_df.copy())
            comparison["user_view"] = build_factor_lab_strategy_user_view(factor, signal_frame, comparison)
        except Exception as exc:
            comparison["user_view_error"] = str(exc)
    return comparisons


def persist_factor_lab_result(result: Dict, report_dir: Optional[str]) -> None:
    if not report_dir:
        return
    path = Path(report_dir) / "latest_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _resolve_factor_lab_report_dir(result: Dict[str, object]) -> Path:
    artifacts = result.get("artifacts", {})
    if isinstance(artifacts, dict):
        report_dir = artifacts.get("report_dir")
        if report_dir:
            return Path(str(report_dir))
    return FACTOR_LAB_REPORT_DIR


def _load_factor_lab_manifest(report_dir: Path = FACTOR_LAB_REPORT_DIR) -> Dict[str, object]:
    path = report_dir / "latest_manifest.json"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def get_factor_lab_artifact_status() -> Dict[str, object]:
    from factor_lab.strategy import get_factor_lab_artifact_readiness

    return get_factor_lab_artifact_readiness(FACTOR_LAB_REPORT_DIR)


def load_factor_lab_artifact_symbols(report_dir: Path = FACTOR_LAB_REPORT_DIR) -> List[str]:
    manifest = _load_factor_lab_manifest(report_dir)
    run_id = str(manifest.get("run_id") or "")
    config_hash = str(manifest.get("config_hash") or "")
    if not run_id or not config_hash:
        return []
    scores_path = report_dir / "latest_scores.csv"
    if not scores_path.exists():
        return []
    try:
        scores = pd.read_csv(scores_path, dtype={"stock_code": str})
    except Exception:
        return []
    required_columns = {"stock_code", "run_id", "config_hash"}
    if scores.empty or not required_columns.issubset(scores.columns):
        return []
    mask = (scores["run_id"].astype(str) == run_id) & (scores["config_hash"].astype(str) == config_hash)
    symbols = scores.loc[mask, "stock_code"].dropna().astype(str).drop_duplicates().tolist()
    return dedupe_symbols(symbols)


def resolve_factor_lab_stress_symbols(
    req: FactorLabStressTestRequest,
    *,
    anchor_date: str,
    lookback_start: str,
    latest_result: Optional[Dict[str, object]] = None,
) -> List[str]:
    """Use the current scoring artifact first so stress tests cover the same candidate universe."""
    report_dir = _resolve_factor_lab_report_dir(latest_result) if isinstance(latest_result, dict) else FACTOR_LAB_REPORT_DIR
    artifact_symbols = load_factor_lab_artifact_symbols(report_dir)
    if artifact_symbols:
        return artifact_symbols[: req.max_symbols]
    return resolve_factor_lab_symbols(req.pool, req.max_symbols, anchor_date, lookback_start)


def validate_factor_lab_backtest_artifacts(req: FactorLabBacktestRequest) -> None:
    from factor_lab.pipeline import _config_hash

    manifest = _load_factor_lab_manifest()
    if not manifest:
        raise HTTPException(status_code=409, detail="缺少 Factor Lab manifest，请先重新运行一次策略体检。")
    expected_config = build_factor_lab_config(
        start_date=req.start_date,
        end_date=req.end_date,
        pool=req.pool,
        label=req.label,
        top_n=req.top_n,
        max_symbols=req.max_symbols,
    )
    expected_hash = _config_hash(expected_config)
    if str(manifest.get("config_hash") or "") != expected_hash:
        raise HTTPException(status_code=409, detail="当前 Factor Lab 分数与回测请求不匹配，请先按当前配置重新体检。")
    if not manifest.get("oos_start_date") or not manifest.get("oos_end_date"):
        raise HTTPException(status_code=409, detail="当前 Factor Lab 分数缺少样本外覆盖，拒绝用于 ML 回测。")
    oos_start = str(manifest["oos_start_date"])
    oos_end = str(manifest["oos_end_date"])
    if oos_start > oos_end or oos_end < req.start_date or oos_start > req.end_date:
        raise HTTPException(status_code=409, detail="当前 Factor Lab 样本外分数没有覆盖回测区间，请缩短区间或重新体检。")


def _build_factor_lab_request_from_summary(summary: Dict[str, object]) -> Optional[FactorLabRunRequest]:
    start_date = summary.get("start_date")
    end_date = summary.get("end_date")
    if not start_date or not end_date:
        return None
    return FactorLabRunRequest(
        start_date=str(start_date),
        end_date=str(end_date),
        pool=str(summary.get("pool") or "core"),
        label=str(summary.get("label") or "next_5d_ret"),
        top_n=int(summary.get("top_n") or 5),
        max_symbols=int(summary["max_symbols"]) if summary.get("max_symbols") is not None else None,
    )


def _load_factor_lab_signal_source(report_dir: Path) -> Optional[pd.DataFrame]:
    candidates = (
        report_dir / "latest_scores.csv",
        report_dir / "training_sample_scored.csv",
    )
    for path in candidates:
        if not path.exists():
            continue
        try:
            frame = pd.read_csv(path, dtype={"stock_code": str})
        except Exception:
            continue
        if frame.empty or "date" not in frame.columns or "stock_code" not in frame.columns:
            continue

        source = frame.copy()
        source["date"] = source["date"].astype(str)
        source["stock_code"] = source["stock_code"].map(normalize_symbol)
        if "stock_name" in source.columns:
            source["stock_name"] = source["stock_name"].fillna("").astype(str)
        else:
            source["stock_name"] = ""
        stock_names = source["stock_name"].str.strip()
        stock_name_codes = stock_names.str.extract(r"^(\d{1,6})$", expand=False).fillna("").str.zfill(6)
        missing_names = (
            (stock_names == "")
            | (stock_names == source["stock_code"])
            | (stock_name_codes == source["stock_code"])
        )
        if missing_names.any():
            name_map = {
                symbol: data_manager.get_stock_name(symbol)
                for symbol in source.loc[missing_names, "stock_code"].dropna().unique().tolist()
            }
            source.loc[missing_names, "stock_name"] = (
                source.loc[missing_names, "stock_code"].map(name_map).fillna(source.loc[missing_names, "stock_code"])
            )

        score_column = None
        for candidate in (
            "score",
            "walk_forward_score",
            "walk_forward_composite_score",
            "composite_score",
            "ml_score",
            "baseline_score",
        ):
            if candidate in source.columns:
                score_column = candidate
                break
        if score_column is None:
            continue

        source["score"] = pd.to_numeric(source[score_column], errors="coerce")
        source = source[source["score"].notna()].copy()
        if source.empty:
            continue

        return source
    return None


def _build_factor_lab_signal_frame_from_scores(factor: str, signal_source: pd.DataFrame) -> pd.DataFrame:
    params = {
        "ml_factor_ranker": {"top_n": 3, "min_score": 0.0},
        "ml_factor_filter": {"top_n": 5, "min_score": 0.60},
    }.get(factor)
    if params is None:
        return signal_source.iloc[0:0].copy()

    signal_frame = signal_source.copy()
    signal_frame["score"] = pd.to_numeric(signal_frame["score"], errors="coerce")
    signal_frame = signal_frame[signal_frame["score"].notna()].copy()
    if signal_frame.empty:
        return signal_frame

    signal_frame["daily_rank"] = signal_frame.groupby("date")["score"].rank(method="first", ascending=False)
    signal_frame["signal"] = (
        (signal_frame["daily_rank"] <= params["top_n"])
        & (signal_frame["score"] >= params["min_score"])
    ).astype(int)
    return signal_frame


def _build_factor_lab_scores_preview(signal_source: pd.DataFrame, top_n: int, limit: int = 100) -> List[Dict[str, object]]:
    if signal_source.empty or "date" not in signal_source.columns:
        return []

    preview = signal_source.copy()
    preview["score"] = pd.to_numeric(preview.get("score"), errors="coerce")
    preview = preview[preview["score"].notna()].copy()
    if preview.empty:
        return []

    if "daily_rank" not in preview.columns or preview["daily_rank"].isna().all():
        preview["daily_rank"] = preview.groupby("date")["score"].rank(method="first", ascending=False)
    else:
        preview["daily_rank"] = pd.to_numeric(preview["daily_rank"], errors="coerce")
    if "signal" not in preview.columns:
        preview["signal"] = (preview["daily_rank"] <= max(1, int(top_n or 1))).astype(int)
    else:
        preview["signal"] = pd.to_numeric(preview["signal"], errors="coerce").fillna(0).astype(int)
    if "score_source" not in preview.columns:
        preview["score_source"] = "score"

    latest_date = preview["date"].max()
    latest = preview[preview["date"] == latest_date].copy()
    latest = latest.sort_values(
        ["signal", "daily_rank", "score", "stock_code"],
        ascending=[False, True, False, True],
    )
    columns = [
        column
        for column in [
            "date",
            "stock_code",
            "stock_name",
            "close",
            "score",
            "daily_rank",
            "signal",
            "is_oos_score",
            "score_source",
        ]
        if column in latest.columns
    ]
    records = latest[columns].head(limit).replace([float("inf"), float("-inf")], pd.NA)
    return records.where(pd.notna(records), None).to_dict(orient="records")


def _infer_factor_lab_summary_from_scores(signal_source: Optional[pd.DataFrame], summary: Dict[str, object]) -> Dict[str, object]:
    if signal_source is None or signal_source.empty:
        return {}

    inferred: Dict[str, object] = {}
    dates = signal_source["date"].dropna().astype(str) if "date" in signal_source.columns else pd.Series(dtype=str)
    if not dates.empty:
        inferred["start_date"] = str(summary.get("start_date") or dates.min())
        inferred["date_start"] = dates.min()
        inferred["date_end"] = dates.max()

    if "label_end_date" in signal_source.columns:
        label_ends = signal_source["label_end_date"].dropna().astype(str)
        if not label_ends.empty:
            inferred["end_date"] = str(summary.get("end_date") or label_ends.max())
    elif not dates.empty:
        inferred["end_date"] = str(summary.get("end_date") or dates.max())

    symbols = int(signal_source["stock_code"].nunique()) if "stock_code" in signal_source.columns else 0
    inferred["symbols"] = symbols
    inferred["total_symbols"] = int(summary.get("total_symbols") or summary.get("max_symbols") or symbols)
    inferred["max_symbols"] = int(summary.get("max_symbols") or symbols or 0) or None
    inferred["pool"] = str(summary.get("pool") or ("all" if symbols > 50 else "core"))
    if inferred["pool"] == "core" and symbols > 50:
        inferred["pool"] = "all"

    inferred["label"] = str(summary.get("label") or "next_5d_ret")
    if "label_horizon" in signal_source.columns and signal_source["label_horizon"].dropna().nunique() == 1:
        horizon = int(signal_source["label_horizon"].dropna().iloc[0])
        inferred["label"] = f"next_{horizon}d_ret"

    top_n = summary.get("top_n")
    if top_n is None and "signal" in signal_source.columns and "daily_rank" in signal_source.columns and not dates.empty:
        latest_date = dates.max()
        latest_signals = signal_source[
            (signal_source["date"].astype(str) == latest_date)
            & (pd.to_numeric(signal_source["signal"], errors="coerce") == 1)
        ]
        if not latest_signals.empty:
            top_n = int(pd.to_numeric(latest_signals["daily_rank"], errors="coerce").max())
    inferred["top_n"] = int(top_n or 5)
    inferred["rows_sample"] = int(len(signal_source))

    if "split" in signal_source.columns:
        split_counts = signal_source.groupby("split").size().to_dict()
        inferred["split_counts"] = {str(key): int(value) for key, value in split_counts.items()}
        inferred["train_samples"] = int(split_counts.get("train", 0))
    if "score_source" in signal_source.columns and not signal_source["score_source"].dropna().empty:
        inferred["score_source"] = str(signal_source["score_source"].dropna().iloc[-1])
    inferred["inference_date"] = str(
        summary.get("inference_date")
        or summary.get("generated_at")
        or datetime.now().isoformat(timespec="seconds")
    )
    inferred["research_note"] = str(
        summary.get("research_note")
        or "本次结果由最新评分文件恢复，展示最近可用样本外评分与研究摘要。"
    )
    return inferred


def _scores_preview_needs_rebuild(preview: object) -> bool:
    if not isinstance(preview, list) or not preview:
        return True
    ranks = []
    code_name_count = 0
    for item in preview[:20]:
        if not isinstance(item, dict):
            continue
        try:
            rank = float(item.get("daily_rank"))
            if pd.notna(rank):
                ranks.append(rank)
        except Exception:
            pass
        stock_code = str(item.get("stock_code") or "")
        stock_name = str(item.get("stock_name") or "")
        if stock_code and stock_name and stock_code == stock_name:
            code_name_count += 1
    if ranks and min(ranks) > 10:
        return True
    return code_name_count >= max(3, len(preview[:20]) // 2)


def upgrade_factor_lab_result_payload(result: Dict[str, object]) -> tuple[Dict[str, object], bool]:
    if not isinstance(result, dict):
        return result, False
    summary = result.get("summary", {})
    if not isinstance(summary, dict) or summary.get("status") == "missing":
        return result, False

    upgraded = copy.deepcopy(result)
    changed = False
    report_dir = _resolve_factor_lab_report_dir(upgraded)
    signal_source_for_upgrade = _load_factor_lab_signal_source(report_dir)
    if (not summary.get("start_date") or not summary.get("end_date")) and (
        upgraded.get("scores_preview") is not None or upgraded.get("artifacts") is not None
    ):
        inferred_summary = _infer_factor_lab_summary_from_scores(signal_source_for_upgrade, summary)
        if inferred_summary:
            upgraded_summary = upgraded.setdefault("summary", {})
            if isinstance(upgraded_summary, dict):
                upgraded_summary.update({key: value for key, value in inferred_summary.items() if value is not None})
                summary = upgraded_summary
                changed = True
    request = _build_factor_lab_request_from_summary(summary)

    if request is not None:
        try:
            symbols = resolve_factor_lab_symbols(request.pool, request.max_symbols, request.end_date, request.start_date)
            universe_metadata = build_factor_lab_universe_metadata(
                request.pool,
                symbols,
                request.max_symbols,
                request.end_date,
                request.start_date,
                actual_symbols=_unique_factor_lab_symbols(signal_source_for_upgrade),
            )
            upgraded_summary = upgraded.setdefault("summary", {})
            if isinstance(upgraded_summary, dict):
                for key, value in universe_metadata.items():
                    if upgraded_summary.get(key) != value:
                        upgraded_summary[key] = value
                        changed = True
        except HTTPException:
            symbols = []
    else:
        symbols = []

    if upgraded.get("run_readiness") is None and request is not None:
        upgraded["run_readiness"] = build_factor_lab_run_readiness(request, symbols)
        changed = True

    strategy_backtests = upgraded.get("strategy_backtests", {})
    if isinstance(strategy_backtests, dict):
        missing_user_view = any(
            isinstance(comparison, dict) and comparison.get("user_view") is None
            for comparison in strategy_backtests.values()
        )
        if missing_user_view:
            signal_source = _load_factor_lab_signal_source(_resolve_factor_lab_report_dir(upgraded))
            if signal_source is not None:
                for factor, comparison in strategy_backtests.items():
                    if not isinstance(comparison, dict) or comparison.get("user_view") is not None:
                        continue
                    signal_frame = _build_factor_lab_signal_frame_from_scores(factor, signal_source)
                    comparison["user_view"] = build_factor_lab_strategy_user_view(factor, signal_frame, comparison)
                    changed = True

    if _scores_preview_needs_rebuild(upgraded.get("scores_preview")):
        signal_source = (
            signal_source_for_upgrade
            if signal_source_for_upgrade is not None
            else _load_factor_lab_signal_source(_resolve_factor_lab_report_dir(upgraded))
        )
        if signal_source is not None:
            top_n = int(summary.get("top_n") or 5)
            preview = _build_factor_lab_scores_preview(signal_source, top_n=top_n, limit=100)
            if preview:
                upgraded["scores_preview"] = preview
                changed = True

    if upgraded.get("stress_test") is None:
        latest_stress_test = load_latest_factor_lab_stress_result(report_dir)
        if latest_stress_test is not None:
            upgraded["stress_test"] = latest_stress_test
            changed = True

    if upgraded.get("self_iteration") is None or changed:
        upgraded["self_iteration"] = build_factor_lab_self_iteration(upgraded, report_dir)
        changed = True

    return upgraded, changed


def make_zero_cost_model() -> CostModel:
    return CostModel(
        commission_rate=0.0,
        commission_min=0.0,
        stamp_tax_rate=0.0,
        slippage_rate=0.0,
        use_order_slicing=False,
    )


def execute_backtest(
    req: BacktestRequest,
    override_cost_model: Optional[CostModel] = None,
    allow_mock: bool = False,
) -> Dict:
    current_pool, pool_ctx, warmup_start = prepare_backtest_universe(req)
    if not BACKTEST_SEMAPHORE.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="当前已有回测任务运行中，请稍后再试。")

    try:
        df, data_sources = data_manager.get_stock_pool_data(
            current_pool,
            warmup_start,
            req.end_date,
            allow_mock=allow_mock,
            allow_late_start=bool(pool_ctx.get("allow_late_start")),
        )
    except (DataFetchError, PoolDataFetchError) as exc:
        BACKTEST_SEMAPHORE.release()
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception:
        BACKTEST_SEMAPHORE.release()
        raise

    try:
        if df.empty:
            raise HTTPException(status_code=400, detail="未获取到行情数据。")
        if len(df) > BACKTEST_MAX_ROWS:
            raise HTTPException(
                status_code=413,
                detail=f"实际加载 {len(df):,} 行行情，超过单次预算 {BACKTEST_MAX_ROWS:,} 行。",
            )

        benchmark_df = None
        benchmark_warning = None
        try:
            benchmark_df, _ = data_manager.get_stock_data(
                "510300",
                req.start_date,
                req.end_date,
                allow_mock=allow_mock,
            )
        except DataFetchError as exc:
            # Do not block strategy backtest if benchmark data is temporarily unavailable.
            benchmark_warning = str(exc)

        strategy_spec = strategy_version_store.resolve_strategy_spec(req.factor)
        if strategy_spec is not None:
            strategy_func = strategy_spec.func
            df = strategy_func(df)
        else:
            def _calc_mom(g):
                g = g.copy()
                g["mom"] = g["close"].pct_change(20)
                g["signal"] = 0
                g.loc[g["mom"] > 0.1, "signal"] = 1
                g.loc[g["mom"] < 0, "signal"] = -1
                return g

            df = df.groupby("stock_code", group_keys=False).apply(_calc_mom)

        resolved_max_hold_days = req.max_hold_days
        resolved_take_profit = req.take_profit
        if strategy_spec is not None:
            if resolved_max_hold_days is None:
                resolved_max_hold_days = strategy_spec.default_max_hold_days
            if resolved_take_profit is None:
                resolved_take_profit = strategy_spec.default_take_profit

        pos_manager = PositionManager(
            max_positions=req.max_positions,
            weight_mode=req.weight_mode,
            max_hold_days=resolved_max_hold_days,
            strategy_spec=strategy_spec,
        )

        engine = None

        signal_by_date = {
            date: group
            for date, group in df.groupby("date", sort=False)
        }
        empty_signals = df.iloc[0:0]

        def signal_func(date, day_data):
            day_signals = signal_by_date.get(date, empty_signals)
            if day_signals.empty:
                return {}
            current_positions = engine.portfolio.positions if engine is not None else None
            return pos_manager.generate_target_weights(
                date,
                day_data,
                day_signals,
                current_positions=current_positions,
            )

        cost_model = override_cost_model or CostModel(
            commission_rate=req.commission_rate,
            commission_min=0.0 if req.commission_rate == 0 else req.commission_min,
            stamp_tax_rate=req.stamp_tax_rate,
            slippage_rate=req.slippage_rate,
        )
        engine_kwargs = {
            "initial_capital": req.initial_capital,
            "cost_model": cost_model,
            "stock_stop_loss": req.stop_loss,
        }
        engine_params = inspect.signature(BacktestEngine.__init__).parameters
        if strategy_spec is not None and "execution_mode" in engine_params:
            engine_kwargs["execution_mode"] = strategy_spec.execution_mode
        if resolved_take_profit is not None:
            if "stock_take_profit" in engine_params:
                engine_kwargs["stock_take_profit"] = resolved_take_profit
            elif "take_profit" in engine_params:
                engine_kwargs["take_profit"] = resolved_take_profit

        engine = BacktestEngine(**engine_kwargs)
        result = engine.run_backtest(df, signal_func, req.start_date, req.end_date, benchmark_data=benchmark_df)
        result["data_sources_used"] = data_sources
        result["data_quality"] = data_manager.get_last_pool_quality()
        result["resolved_pool"] = {
            "requested_pool": req.pool,
            **pool_ctx,
        }
        result["strategy_behavior"] = {
            "factor": req.factor,
            "signal_type": strategy_spec.signal_type if strategy_spec is not None else "custom",
            "holding_policy": strategy_spec.holding_policy if strategy_spec is not None else "custom",
            "resolved_max_hold_days": resolved_max_hold_days,
            "resolved_take_profit": resolved_take_profit,
            "execution_mode": strategy_spec.execution_mode if strategy_spec is not None else "next_open_rebalance",
            "portfolio_circuit_breaker_active": False,
            "deprecated_circuit_breaker_requested": req.circuit_breaker,
            "risk_control_note": "组合熔断已停用；组合回撤仅作为风险指标展示。",
        }
        if benchmark_warning:
            result.setdefault("warnings", []).append(
                {
                    "code": "BENCHMARK_UNAVAILABLE",
                    "message": benchmark_warning,
                }
            )
        trades = result.get("trades")
        if isinstance(trades, list):
            max_trades = 500
            total_trades = len(trades)
            if total_trades > max_trades:
                result["trades_total"] = total_trades
                result["trades_truncated"] = True
                result["trades"] = trades[-max_trades:]
            else:
                result["trades_total"] = total_trades
                result["trades_truncated"] = False
        return result
    finally:
        BACKTEST_SEMAPHORE.release()


def build_factor_lab_backtest_request(
    req: FactorLabRunRequest,
    factor: str,
    symbols: Optional[List[str]] = None,
) -> BacktestRequest:
    scoped_symbols = dedupe_symbols(symbols or []) or None
    return BacktestRequest(
        start_date=req.start_date,
        end_date=req.end_date,
        initial_capital=req.initial_capital,
        stocks=scoped_symbols,
        max_symbols=req.max_symbols,
        factor=factor,
        pool=req.pool,
        max_positions=max(1, req.top_n),
        weight_mode="score",
        stop_loss=req.stop_loss,
        commission_rate=req.commission_rate,
        stamp_tax_rate=req.stamp_tax_rate,
        slippage_rate=req.slippage_rate,
        commission_min=req.commission_min,
    )


def summarize_strategy_backtest(with_cost: Dict, zero_cost: Dict, factor: str) -> Dict:
    return {
        "factor": factor,
        "with_cost": {
            "total_return": float(with_cost.get("total_return", 0.0)),
            "summary": with_cost.get("summary", {}),
            "resolved_pool": with_cost.get("resolved_pool", {}),
        },
        "without_cost": {
            "total_return": float(zero_cost.get("total_return", 0.0)),
            "summary": zero_cost.get("summary", {}),
            "resolved_pool": zero_cost.get("resolved_pool", {}),
        },
        "cost_drag": {
            "total_return_diff": float(zero_cost.get("total_return", 0.0) - with_cost.get("total_return", 0.0)),
            "annual_return_diff": float(
                zero_cost.get("summary", {}).get("annual_return", 0.0)
                - with_cost.get("summary", {}).get("annual_return", 0.0)
            ),
            "cost_pct_initial": float(with_cost.get("summary", {}).get("cost_stats", {}).get("cost_pct_initial", 0.0)),
        },
    }


def run_factor_lab_strategy_comparison(
    req: FactorLabRunRequest,
    factors: List[str],
    *,
    symbols: Optional[List[str]] = None,
    allow_mock: bool = False,
) -> Dict[str, Dict]:
    comparisons = {}
    for factor in factors:
        backtest_req = build_factor_lab_backtest_request(req, factor, symbols=symbols)
        with_cost = execute_backtest(backtest_req, allow_mock=allow_mock)
        zero_cost = execute_backtest(
            backtest_req,
            override_cost_model=make_zero_cost_model(),
            allow_mock=allow_mock,
        )
        comparisons[factor] = summarize_strategy_backtest(with_cost, zero_cost, factor)
        comparisons[factor]["with_cost_result"] = with_cost
    return comparisons


def build_stress_test_config(req: FactorLabStressTestRequest):
    from factor_lab.stress_test import SCENARIO_SPECS, StressTestConfig

    unsupported_factors = [factor for factor in req.factors if factor not in {"ml_factor_ranker", "ml_factor_filter"}]
    if unsupported_factors:
        raise HTTPException(
            status_code=400,
            detail=f"压力测评仅支持 Factor Lab 策略: {', '.join(unsupported_factors)}",
        )
    unsupported_scenarios = [scenario for scenario in req.scenarios if scenario not in SCENARIO_SPECS]
    if unsupported_scenarios:
        raise HTTPException(
            status_code=400,
            detail=f"未知情景: {', '.join(unsupported_scenarios)}",
        )
    if req.horizon_days < 20 or req.horizon_days > 260:
        raise HTTPException(status_code=413, detail="压力测评 horizon_days 必须在 20 到 260 之间。")
    if req.paths_per_scenario < 1 or req.paths_per_scenario > 200:
        raise HTTPException(status_code=413, detail="压力测评 paths_per_scenario 必须在 1 到 200 之间。")
    if req.max_symbols < 3 or req.max_symbols > FACTOR_LAB_MAX_SYMBOLS:
        raise HTTPException(status_code=413, detail=f"压力测评 max_symbols 必须在 3 到 {FACTOR_LAB_MAX_SYMBOLS} 之间。")
    if req.top_n < 1 or req.top_n > 50:
        raise HTTPException(status_code=413, detail="压力测评 top_n 必须在 1 到 50 之间。")
    if req.lookback_days < 90 or req.lookback_days > 520:
        raise HTTPException(status_code=413, detail="压力测评 lookback_days 必须在 90 到 520 之间。")

    return StressTestConfig(
        pool=req.pool,
        max_symbols=req.max_symbols,
        top_n=req.top_n,
        initial_capital=req.initial_capital,
        factors=req.factors,
        horizon_days=req.horizon_days,
        paths_per_scenario=req.paths_per_scenario,
        seed=req.seed,
        scenarios=req.scenarios,
        anchor_date=req.anchor_date,
        lookback_days=req.lookback_days,
        commission_rate=req.commission_rate,
        stamp_tax_rate=req.stamp_tax_rate,
        slippage_rate=req.slippage_rate,
        stop_loss=req.stop_loss,
    )


@app.get("/")
def read_root():
    return {"message": "Gemini Quant Pro API is running on 8080"}


def _health_payload(ready: bool) -> Dict[str, object]:
    cache_dir = data_manager.cache_dir
    etf_cache_dir = data_manager.etf_cache_dir
    db_parent = DB_PATH.parent
    checks = {
        "cache_dir_readable": cache_dir.exists() and cache_dir.is_dir(),
        "etf_cache_dir_readable": etf_cache_dir.exists() and etf_cache_dir.is_dir(),
        "db_parent_writable": db_parent.exists() and db_parent.is_dir(),
        "pools_loaded": bool(STOCK_POOL or ETF_POOL or BLACKHORSE_POOL),
    }
    status = "ready" if all(checks.values()) else "degraded"
    return {
        "service": "quant-viz-backtest",
        "status": status if ready else "ok",
        "ready": all(checks.values()),
        "engine_version": "Gemini Quant Pro V4.6 (Lake Routed)",
        "checks": checks,
    }


@app.get("/healthz")
def healthz():
    return _health_payload(ready=False)


@app.get("/readyz")
def readyz():
    payload = _health_payload(ready=True)
    if not payload["ready"]:
        return JSONResponse(status_code=503, content=payload)
    return payload


def _require_local_request(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="状态变更接口仅允许本机访问。")


def _has_valid_quant_api_key(request: Request) -> bool:
    expected = os.getenv("QUANT_AI_API_KEY", "").strip()
    if not expected:
        return False
    provided = request.headers.get("X-Quant-Api-Key", "").strip()
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        provided = provided or auth.split(" ", 1)[1].strip()
    return bool(provided and provided == expected)


def _require_automation_request(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return
    if _has_valid_quant_api_key(request):
        return
    raise HTTPException(status_code=403, detail="自动化/AI 接口仅允许本机或有效 X-Quant-Api-Key 访问。")


@app.get("/api/market/latest")
def get_latest():
    overview_symbols = _latest_overview_symbols()
    cached = data_manager.get_latest_market_cached()
    if cached is not None:
        return cached
    if MARKET_WARMUP_THREAD is not None and MARKET_WARMUP_THREAD.is_alive():
        return data_manager.get_latest_market_fallback(overview_symbols, limit=10)
    return data_manager.get_latest_market_overview(overview_symbols, limit=10)


@app.get("/api/v1/strategy/power-storage")
def get_power_storage_strategy():
    try:
        result = run_power_energy_strategy()
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        return result
    except Exception as e:
        logger.error(f"Error running power storage strategy: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/system/status")
def get_system_status():
    return {
        "market_status": data_manager.get_market_status(),
        "data_coverage": "2022 - 2026 (实盘级数据湖)",
        "stock_pool": "A股策略 -> A股数据湖, ETF策略 -> ETF 数据湖",
        "engine_version": "Gemini Quant Pro V4.6 (Lake Routed)",
        "local_a_share_files": len(data_manager.list_local_codes("a_share")),
        "local_etf_files": len(data_manager.list_local_codes("etf")),
    }


@app.get("/api/automation/status")
def get_automation_status():
    return automation_orchestrator.status_payload(automation_scheduler)


@app.get("/api/automation/runs")
def get_automation_runs(job_type: Optional[str] = None, limit: int = 20):
    return automation_store.list_runs(job_type=job_type, limit=limit)


@app.post("/api/automation/jobs/realtime-snapshot")
def run_automation_realtime_snapshot(req: AutomationSnapshotRequest, request: Request):
    _require_automation_request(request)
    return automation_orchestrator.run_realtime_snapshot(trigger="manual", limit=req.limit)


@app.post("/api/automation/jobs/eod-update")
def run_automation_eod_update(req: AutomationEodUpdateRequest, request: Request):
    _require_automation_request(request)
    return automation_orchestrator.run_eod_update(
        trigger="manual",
        target_date=req.target_date,
        dry_run=req.dry_run,
        buffer_days=req.buffer_days,
        workers_a_share=req.workers_a_share,
        workers_etf=req.workers_etf,
        retry=req.retry,
        task_timeout=req.task_timeout,
        limit_a_share=req.limit_a_share,
        limit_etf=req.limit_etf,
        skip_a_share=req.skip_a_share,
        skip_etf=req.skip_etf,
    )


@app.post("/api/automation/jobs/virtual-trade")
def run_automation_virtual_trade(request: Request):
    _require_automation_request(request)
    return automation_orchestrator.run_virtual_trade(trigger="manual")


@app.post("/api/automation/jobs/ai-cycle")
def run_automation_ai_cycle(req: AutomationAICycleRequest, request: Request):
    _require_automation_request(request)
    _configure_ai_handlers()
    decision = req.decision.model_dump() if req.decision else None
    return automation_orchestrator.run_ai_cycle(trigger="manual", decision=decision, dry_run=req.dry_run)


@app.post("/api/automation/jobs/ai-managed-work")
def run_automation_ai_managed_work(req: AutomationAIManagedWorkRequest, request: Request):
    _require_automation_request(request)
    _configure_ai_handlers()
    decision = req.decision.model_dump() if req.decision else None
    return automation_orchestrator.run_ai_managed_work(
        work_type=req.work_type,
        trigger="manual",
        decision=decision,
        dry_run=req.dry_run,
    )


@app.get("/api/ai/context")
def get_ai_context(request: Request):
    _require_automation_request(request)
    return _build_ai_context()


@app.get("/api/ai/decisions")
def get_ai_decisions(request: Request, limit: int = 20):
    _require_automation_request(request)
    return automation_store.list_ai_decisions(limit=limit)


@app.get("/api/ai/work-logs")
def get_ai_work_logs(request: Request, work_type: Optional[str] = None, limit: int = 20):
    _require_automation_request(request)
    return automation_store.list_ai_work_logs(work_type=work_type, limit=limit)


@app.get("/api/ai/work-messages")
def get_ai_work_messages(request: Request, work_type: Optional[str] = None, limit: int = 50):
    _require_automation_request(request)
    return automation_store.list_ai_work_messages(work_type=work_type, limit=limit)


@app.post("/api/ai/decisions")
def post_ai_decision(req: AIDecisionRequest, request: Request):
    _require_automation_request(request)
    _configure_ai_handlers()
    payload = req.model_dump()
    work_id = req.decision_id or f"external-ai-{uuid.uuid4().hex[:12]}"

    def record_external_action(result: Dict[str, object]) -> None:
        action_type = str(result.get("type") or result.get("action") or "unknown")
        status = str(result.get("status") or "unknown")
        level = "error" if status in {"failed", "rejected"} else "warn" if status in {"skipped", "partial"} else "info"
        detail = result.get("error") or result.get("reason") or result.get("result") or ""
        ai_automation_service.store.record_ai_work_message(
            work_id=work_id,
            work_type="external_ai_decision",
            trigger="external_api",
            action_type=action_type,
            status=status,
            level=level,
            title=f"外部 AI 动作 / {action_type}",
            body=f"{action_type} / {status}" + (f"：{str(detail)[:240]}" if detail else ""),
            details={"source": req.source, "actor": req.actor, "result": result},
        )

    return ai_automation_service.execute_decision(
        payload,
        handlers=automation_orchestrator.ai_handlers,
        source=req.source,
        dry_run=req.dry_run,
        on_action_result=record_external_action,
    )


@app.get("/api/strategies")
def get_strategies():
    res = {}
    for key, spec in STRATEGY_REGISTRY.items():
        res[key] = {
            "name": spec.name,
            "pool": spec.pool,
            "category": spec.category,
            "asset_class": "etf" if spec.pool == "etf" else "a_share",
            "signal_type": spec.signal_type,
            "holding_policy": spec.holding_policy,
            "default_max_hold_days": spec.default_max_hold_days,
            "default_take_profit": spec.default_take_profit,
            "execution_mode": spec.execution_mode,
            "requires_artifact": spec.requires_artifact,
        }
        if spec.requires_artifact:
            res[key]["artifact_status"] = get_factor_lab_artifact_status()
    return res


@app.post("/api/backtest")
def run_backtest(req: BacktestRequest):
    return execute_backtest(req, allow_mock=req.allow_mock)


@app.post("/api/backtest/jobs", response_model=BacktestJobSubmitResponse)
def submit_backtest_job(req: BacktestRequest):
    _cleanup_backtest_jobs()
    job_id = _create_backtest_job(req)
    thread = threading.Thread(target=_run_backtest_job, args=(job_id,), daemon=True)
    thread.start()
    return BacktestJobSubmitResponse(job_id=job_id)


@app.get("/api/backtest/jobs/{job_id}", response_model=BacktestJobStatusResponse)
def get_backtest_job_status(job_id: str):
    _cleanup_backtest_jobs()
    job = _get_backtest_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="回测任务不存在或已过期。")
    return BacktestJobStatusResponse(
        job_id=job_id,
        status=str(job.get("status", "unknown")),
        created_at=float(job.get("created_at", 0.0)),
        updated_at=float(job.get("updated_at", 0.0)),
        error=str(job.get("error")) if job.get("error") else None,
    )


@app.get("/api/backtest/jobs/{job_id}/result")
def get_backtest_job_result(job_id: str):
    _cleanup_backtest_jobs()
    job = _get_backtest_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="回测任务不存在或已过期。")
    status = str(job.get("status", "unknown"))
    if status in {"queued", "running"}:
        raise HTTPException(status_code=425, detail="回测仍在运行中。")
    if status != "succeeded":
        raise HTTPException(status_code=500, detail=str(job.get("error") or "回测失败"))
    result = job.get("result")
    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="回测结果不可用。")
    return result


def execute_compare_request(req: CompareRequest) -> Dict[str, Dict]:
    if len(req.strategies) > BACKTEST_MAX_COMPARE_STRATEGIES:
        raise HTTPException(
            status_code=400,
            detail=f"策略对比最多支持 {BACKTEST_MAX_COMPARE_STRATEGIES} 个策略，请减少后重试。",
        )
    selected = req.strategies
    asset_classes = {get_asset_class_from_strategy(strategy, req.pool) for strategy in selected}
    if len(asset_classes) > 1:
        raise HTTPException(status_code=400, detail="A股策略和 ETF 策略不能混合对比，请分开运行。")

    backtest_requests = []
    total_estimated_rows = 0
    for strategy in selected:
        br = BacktestRequest(
            start_date=req.start_date,
            end_date=req.end_date,
            initial_capital=req.initial_capital,
            stocks=req.stocks,
            max_symbols=req.max_symbols,
            factor=strategy,
            pool=req.pool,
            max_positions=req.max_positions,
            weight_mode=req.weight_mode,
            max_hold_days=req.max_hold_days,
            stop_loss=req.stop_loss,
            take_profit=req.take_profit,
            commission_rate=req.commission_rate,
            stamp_tax_rate=req.stamp_tax_rate,
            slippage_rate=req.slippage_rate,
            commission_min=req.commission_min,
            allow_mock=req.allow_mock,
        )
        _, pool_ctx, _ = prepare_backtest_universe(br)
        total_estimated_rows += int(pool_ctx.get("estimated_rows", 0))
        if total_estimated_rows > BACKTEST_MAX_COMPARE_ROWS:
            raise HTTPException(
                status_code=413,
                detail=f"策略对比预计处理 {total_estimated_rows:,} 行行情，超过总预算 {BACKTEST_MAX_COMPARE_ROWS:,} 行。请减少策略、股票数或日期区间。",
            )
        backtest_requests.append((strategy, br))

    results = {}
    for strategy, br in backtest_requests:
        try:
            results[strategy] = execute_backtest(br, allow_mock=req.allow_mock)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"策略对比执行失败: {e}")

    return results


@app.post("/api/backtest/compare")
def compare_strategies(req: CompareRequest):
    return execute_compare_request(req)


@app.post("/api/backtest/compare/jobs", response_model=BacktestJobSubmitResponse)
def submit_compare_job(req: CompareRequest):
    _cleanup_compare_jobs()
    job_id = _create_compare_job(req)
    thread = threading.Thread(target=_run_compare_job, args=(job_id,), daemon=True)
    thread.start()
    return BacktestJobSubmitResponse(job_id=job_id)


@app.get("/api/backtest/compare/jobs/{job_id}", response_model=BacktestJobStatusResponse)
def get_compare_job_status(job_id: str):
    _cleanup_compare_jobs()
    job = _get_compare_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="策略对比任务不存在或已过期。")
    return BacktestJobStatusResponse(
        job_id=job_id,
        status=str(job.get("status", "unknown")),
        created_at=float(job.get("created_at", 0.0)),
        updated_at=float(job.get("updated_at", 0.0)),
        error=str(job.get("error")) if job.get("error") else None,
    )


@app.get("/api/backtest/compare/jobs/{job_id}/result")
def get_compare_job_result(job_id: str):
    _cleanup_compare_jobs()
    job = _get_compare_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="策略对比任务不存在或已过期。")
    status = str(job.get("status", "unknown"))
    if status in {"queued", "running"}:
        raise HTTPException(status_code=425, detail="策略对比仍在运行中。")
    if status != "succeeded":
        raise HTTPException(status_code=500, detail=str(job.get("error") or "策略对比失败"))
    result = job.get("result")
    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="策略对比结果不可用。")
    return result


@app.get("/api/factor-lab/results")
def get_factor_lab_results():
    result, _changed = upgrade_factor_lab_result_payload(load_latest_factor_lab_result())
    result["artifact_status"] = get_factor_lab_artifact_status()
    attach_factor_lab_lifecycle(result)
    return result


@app.post("/api/factor-lab/readiness")
def get_factor_lab_readiness(req: FactorLabRunRequest):
    try:
        symbols = resolve_factor_lab_symbols(req.pool, req.max_symbols, req.end_date, req.start_date)
        return {
            "run_readiness": build_factor_lab_run_readiness(req, symbols),
        }
    except HTTPException as exc:
        return factor_lab_error_response(
            exc.status_code,
            str(exc.detail),
            "FACTOR_LAB_INVALID_REQUEST",
        )
    except ValueError as exc:
        return factor_lab_error_response(
            400,
            f"日期格式错误: {exc}",
            "FACTOR_LAB_INVALID_DATE",
        )


@app.get("/api/factor-lab/factors", deprecated=True)
def get_factor_lab_factors():
    result = load_latest_factor_lab_result()
    return {
        "summary": result.get("summary", {}),
        "factor_ranking": result.get("factor_ranking", []),
    }


@app.post("/api/factor-lab/run")
def run_factor_lab_api(req: FactorLabRunRequest):
    if not FACTOR_LAB_SEMAPHORE.acquire(blocking=False):
        return factor_lab_error_response(429, "当前已有 Factor Lab 任务运行中，请稍后再试。", "FACTOR_LAB_BUSY")
    run_readiness = None
    artifact_snapshot = None
    try:
        start_dt = datetime.strptime(req.start_date, "%Y-%m-%d")
        warmup_start = (start_dt - timedelta(days=FACTOR_LAB_WARMUP_DAYS)).strftime("%Y-%m-%d")
        symbols = resolve_factor_lab_symbols(req.pool, req.max_symbols, req.end_date, req.start_date)
        run_readiness = build_factor_lab_run_readiness(req, symbols)
        with FACTOR_LAB_ARTIFACT_LOCK:
            artifact_snapshot = snapshot_factor_lab_artifacts()
        df, data_sources = data_manager.get_stock_pool_data(
            symbols,
            warmup_start,
            req.end_date,
            allow_mock=False,
        )
        if df.empty:
            with FACTOR_LAB_ARTIFACT_LOCK:
                restore_factor_lab_artifacts(artifact_snapshot)
            FACTOR_LAB_SEMAPHORE.release()
            return factor_lab_error_response(
                400,
                "未获取到 Factor Lab 研究所需的真实行情数据。",
                "FACTOR_LAB_DATA_EMPTY",
                run_readiness=run_readiness,
            )
    except HTTPException as exc:
        FACTOR_LAB_SEMAPHORE.release()
        return factor_lab_error_response(
            exc.status_code,
            str(exc.detail),
            "FACTOR_LAB_INVALID_REQUEST",
        )
    except ValueError as exc:
        FACTOR_LAB_SEMAPHORE.release()
        return factor_lab_error_response(
            400,
            f"日期格式错误: {exc}",
            "FACTOR_LAB_INVALID_DATE",
        )
    except (DataFetchError, PoolDataFetchError) as exc:
        with FACTOR_LAB_ARTIFACT_LOCK:
            restore_factor_lab_artifacts(artifact_snapshot)
        FACTOR_LAB_SEMAPHORE.release()
        return factor_lab_error_response(
            502,
            str(exc),
            "FACTOR_LAB_UPSTREAM_FETCH_FAILED",
            run_readiness=run_readiness,
        )
    except Exception as exc:
        with FACTOR_LAB_ARTIFACT_LOCK:
            restore_factor_lab_artifacts(artifact_snapshot)
        FACTOR_LAB_SEMAPHORE.release()
        return factor_lab_error_response(
            500,
            f"Factor Lab 准备阶段失败: {exc}",
            "FACTOR_LAB_RUN_FAILED",
            run_readiness=run_readiness,
        )

    config = build_factor_lab_config(
        start_date=req.start_date,
        end_date=req.end_date,
        pool=req.pool,
        label=req.label,
        top_n=req.top_n,
        max_symbols=req.max_symbols,
    )

    try:
        with FACTOR_LAB_ARTIFACT_LOCK:
            result = execute_factor_lab_pipeline(df, config, write_latest_summary=False)
        result.setdefault("summary", {}).update(
            build_factor_lab_universe_metadata(req.pool, symbols, req.max_symbols, req.end_date, req.start_date)
        )
        comparisons = run_factor_lab_strategy_comparison(
            req,
            ["ml_factor_ranker", "ml_factor_filter"],
            symbols=symbols,
            allow_mock=False,
        )
        comparisons = attach_factor_lab_user_views(comparisons, df)
        ranker_full_result = comparisons["ml_factor_ranker"].pop("with_cost_result")
        comparisons["ml_factor_filter"].pop("with_cost_result", None)
        result["run_readiness"] = run_readiness
        result["data_sources_used"] = data_sources
        result["backtest"] = ranker_full_result
        result["strategy_backtests"] = comparisons
        result["backtest_compare"] = {
            "factors": list(comparisons.keys()),
            "best_total_return_factor": max(
                comparisons.keys(),
                key=lambda factor: comparisons[factor]["with_cost"]["total_return"],
            ),
        }
        result["self_iteration"] = build_factor_lab_self_iteration(
            result,
            Path(result.get("artifacts", {}).get("report_dir") or FACTOR_LAB_REPORT_DIR),
        )
        materialize_factor_lab_run_archive(result, Path(result.get("artifacts", {}).get("report_dir") or FACTOR_LAB_REPORT_DIR))
        attach_factor_lab_lifecycle(result)
        result["api_examples"] = {
            "run": {
                "path": "/api/factor-lab/run",
                "body": req.model_dump(),
            },
            "results": {
                "path": "/api/factor-lab/results",
            },
            "backtest": {
                "path": "/api/factor-lab/backtest",
                "body": build_factor_lab_backtest_request(req, "ml_factor_ranker", symbols=symbols).model_dump(),
            },
        }
        with FACTOR_LAB_ARTIFACT_LOCK:
            persist_factor_lab_result(result, result.get("artifacts", {}).get("report_dir"))
            try:
                result["artifact_cleanup"] = cleanup_factor_lab_artifacts(
                    report_dir=Path(result.get("artifacts", {}).get("report_dir") or FACTOR_LAB_REPORT_DIR),
                    keep_recent_runs=FACTOR_LAB_KEEP_RECENT_RUNS,
                    dry_run=False,
                    delete_training_sample=False,
                )
            except Exception as cleanup_exc:
                logger.warning(f"Factor Lab artifact cleanup skipped: {cleanup_exc}")
            clear_factor_lab_artifact_snapshot(artifact_snapshot)
        return result
    except ValueError as exc:
        with FACTOR_LAB_ARTIFACT_LOCK:
            restore_factor_lab_artifacts(artifact_snapshot)
        return factor_lab_error_response(
            400,
            str(exc),
            "FACTOR_LAB_RESEARCH_FAILED",
            run_readiness=run_readiness,
        )
    except HTTPException as exc:
        with FACTOR_LAB_ARTIFACT_LOCK:
            restore_factor_lab_artifacts(artifact_snapshot)
        return factor_lab_error_response(
            exc.status_code,
            str(exc.detail),
            "FACTOR_LAB_RUN_FAILED",
            run_readiness=run_readiness,
        )
    except (DataFetchError, PoolDataFetchError) as exc:
        with FACTOR_LAB_ARTIFACT_LOCK:
            restore_factor_lab_artifacts(artifact_snapshot)
        return factor_lab_error_response(
            502,
            str(exc),
            "FACTOR_LAB_UPSTREAM_FETCH_FAILED",
            run_readiness=run_readiness,
        )
    except Exception as exc:
        with FACTOR_LAB_ARTIFACT_LOCK:
            restore_factor_lab_artifacts(artifact_snapshot)
        return factor_lab_error_response(
            500,
            f"Factor Lab 运行失败: {exc}",
            "FACTOR_LAB_RUN_FAILED",
            run_readiness=run_readiness,
        )
    finally:
        FACTOR_LAB_SEMAPHORE.release()


@app.post("/api/factor-lab/backtest")
def run_factor_lab_backtest(req: FactorLabBacktestRequest):
    if req.factor not in {"ml_factor_ranker", "ml_factor_filter"}:
        return factor_lab_error_response(
            400,
            "Factor Lab backtest 仅支持 ml_factor_ranker 或 ml_factor_filter。",
            "FACTOR_LAB_BACKTEST_FACTOR_UNSUPPORTED",
        )
    try:
        validate_factor_lab_backtest_artifacts(req)
        backtest_req = req
        if not req.stocks:
            artifact_symbols = load_factor_lab_artifact_symbols()
            if not artifact_symbols:
                raise HTTPException(status_code=409, detail="当前 Factor Lab artifact 缺少本轮样本股票，请先重新运行一次策略体检。")
            backtest_req = req.model_copy(update={"stocks": artifact_symbols, "max_symbols": len(artifact_symbols)})
        return execute_backtest(backtest_req, allow_mock=False)
    except HTTPException as exc:
        return factor_lab_error_response(
            exc.status_code,
            str(exc.detail),
            "FACTOR_LAB_BACKTEST_FAILED",
        )
    except (DataFetchError, PoolDataFetchError) as exc:
        return factor_lab_error_response(
            502,
            str(exc),
            "FACTOR_LAB_UPSTREAM_FETCH_FAILED",
        )
    except Exception as exc:
        return factor_lab_error_response(
            500,
            f"Factor Lab 回测失败: {exc}",
            "FACTOR_LAB_BACKTEST_FAILED",
        )


@app.get("/api/factor-lab/stress-test/results")
def get_factor_lab_stress_test_results():
    stress_test = load_latest_factor_lab_stress_result()
    if stress_test is None:
        return {
            "summary": {
                "status": "missing",
                "message": "No Factor Lab stress test result has been generated yet.",
            },
            "stress_test": None,
        }
    return {"stress_test": stress_test}


@app.post("/api/factor-lab/stress-test")
def run_factor_lab_stress_test_api(req: FactorLabStressTestRequest):
    if not FACTOR_LAB_SEMAPHORE.acquire(blocking=False):
        return factor_lab_error_response(429, "当前已有 Factor Lab 任务运行中，请稍后再试。", "FACTOR_LAB_BUSY")
    try:
        config = build_stress_test_config(req)
        anchor_date = req.anchor_date or data_manager.get_last_trading_day()
        end_dt = datetime.strptime(anchor_date, "%Y-%m-%d")
        start_dt = end_dt - timedelta(days=max(req.lookback_days * 3, 400))
        latest = load_latest_factor_lab_result()
        symbols = resolve_factor_lab_stress_symbols(
            req,
            anchor_date=anchor_date,
            lookback_start=start_dt.strftime("%Y-%m-%d"),
            latest_result=latest,
        )
        if len(symbols) < 3:
            return factor_lab_error_response(
                409,
                "压力测评需要至少 3 只可用标的；请先重新运行一次 Factor Lab 体检或调大样本预算。",
                "FACTOR_LAB_STRESS_SYMBOLS_TOO_FEW",
            )
        df, data_sources = data_manager.get_stock_pool_data(
            symbols,
            start_dt.strftime("%Y-%m-%d"),
            end_dt.strftime("%Y-%m-%d"),
            allow_mock=False,
        )
        if df.empty:
            return factor_lab_error_response(
                400,
                "未获取到压力测评所需的真实历史行情。",
                "FACTOR_LAB_STRESS_DATA_EMPTY",
            )

        with FACTOR_LAB_ARTIFACT_LOCK:
            stress_test = run_factor_lab_stress_pipeline(df, config, FACTOR_LAB_REPORT_DIR)
        stress_test["data_sources_used"] = data_sources

        self_iteration = None
        if latest and latest.get("summary", {}).get("status") != "missing":
            latest["stress_test"] = stress_test
            latest["self_iteration"] = build_factor_lab_self_iteration(latest, _resolve_factor_lab_report_dir(latest))
            strategy_version_store.sync_factor_lab_run_evidence(latest)
            attach_factor_lab_lifecycle(latest)
            self_iteration = latest["self_iteration"]
            with FACTOR_LAB_ARTIFACT_LOCK:
                persist_factor_lab_result(latest, str(_resolve_factor_lab_report_dir(latest)))

        return {
            "stress_test": stress_test,
            "self_iteration": self_iteration,
            "strategy_lifecycle": latest.get("strategy_lifecycle") if isinstance(latest, dict) else None,
        }
    except HTTPException as exc:
        return factor_lab_error_response(
            exc.status_code,
            str(exc.detail),
            "FACTOR_LAB_STRESS_TEST_FAILED",
        )
    except ValueError as exc:
        return factor_lab_error_response(
            400,
            str(exc),
            "FACTOR_LAB_STRESS_TEST_FAILED",
        )
    except (DataFetchError, PoolDataFetchError) as exc:
        return factor_lab_error_response(
            502,
            str(exc),
            "FACTOR_LAB_UPSTREAM_FETCH_FAILED",
        )
    except Exception as exc:
        return factor_lab_error_response(
            500,
            f"Factor Lab 压力测评失败: {exc}",
            "FACTOR_LAB_STRESS_TEST_FAILED",
        )
    finally:
        FACTOR_LAB_SEMAPHORE.release()


@app.post("/api/factor-lab/candidates/{run_id}/promote")
def promote_factor_lab_candidate(run_id: str, req: FactorLabPromoteRequest):
    try:
        result = load_factor_lab_result_by_run_id(run_id)
        if not (isinstance(result.get("artifacts"), dict) and result["artifacts"].get("run_dir")):
            materialize_factor_lab_run_archive(result, _resolve_factor_lab_report_dir(result))
        version = strategy_version_store.create_factor_lab_candidate(
            result,
            strategy_id=req.strategy_id,
            candidate_factor=req.candidate_factor,
            created_by=req.created_by,
            note=req.note,
        )
        attach_factor_lab_lifecycle(result)
        persist_factor_lab_result(result, str(_resolve_factor_lab_report_dir(result)))
        return {"version": version, "strategy_lifecycle": result.get("strategy_lifecycle")}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"候选版本提升失败: {exc}")


@app.post("/api/factor-lab/artifacts/cleanup")
def cleanup_factor_lab_artifacts_api(req: FactorLabArtifactCleanupRequest):
    try:
        return cleanup_factor_lab_artifacts(
            report_dir=FACTOR_LAB_REPORT_DIR,
            keep_recent_runs=req.keep_recent_runs,
            dry_run=req.dry_run,
            delete_training_sample=req.delete_training_sample,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Factor Lab 产物清理失败: {exc}")


@app.post("/api/strategy-versions/{version_id}/shadow")
def start_strategy_version_shadow(version_id: str, req: StrategyVersionActionRequest):
    try:
        version = strategy_version_store.start_shadow(version_id, started_by=req.user, note=req.note)
        return {"version": version}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"启动影子观察失败: {exc}")


@app.post("/api/strategy-versions/{version_id}/approve")
def approve_strategy_version(version_id: str, req: StrategyVersionActionRequest):
    try:
        version = strategy_version_store.approve(version_id, approved_by=req.user, note=req.note)
        return {"version": version}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"审批策略版本失败: {exc}")


@app.post("/api/strategy-versions/{version_id}/iterate")
def iterate_strategy_version(version_id: str, req: StrategyVersionIterateRequest):
    try:
        iteration = strategy_version_store.create_candidate_iteration_plan(
            version_id,
            created_by=req.user,
            note=req.note,
        )
        return {
            "iteration": iteration,
            "version": strategy_version_store.get_version(version_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"创建候选迭代计划失败: {exc}")


@app.post("/api/strategies/{strategy_id}/activate-version")
def activate_strategy_version(strategy_id: str, req: StrategyActivateVersionRequest):
    try:
        return strategy_version_store.activate(strategy_id, req.version_id, switched_by=req.user, note=req.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"激活策略版本失败: {exc}")


@app.post("/api/strategies/{strategy_id}/rollback")
def rollback_strategy_version(strategy_id: str, req: StrategyRollbackRequest):
    try:
        return strategy_version_store.rollback(strategy_id, switched_by=req.user, reason=req.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"回滚策略版本失败: {exc}")


@app.get("/api/strategies/{strategy_id}/versions")
def list_strategy_versions(strategy_id: str):
    return {
        "strategy_id": strategy_id,
        "active_version_id": strategy_version_store.get_active_version_id(strategy_id),
        "versions": strategy_version_store.list_versions(strategy_id),
    }


@app.get("/api/virtual-trade/accounts")
def get_vt_accounts():
    try:
        return _virtual_accounts_with_intraday_snapshot()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/virtual-trade/history")
def get_vt_history(
    strategy_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
):
    try:
        return vt_manager.get_trade_log(strategy_id, limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/virtual-trade/execute")
def execute_vt_daily(request: Request):
    _require_local_request(request)
    try:
        return _execute_virtual_trade_locked()
    except RuntimeError as e:
        # 业务逻辑错误 (如数据未就绪)
        status = 429 if "already running" in str(e) else 400
        raise HTTPException(status_code=status, detail=str(e))
    except Exception as e:
        logger.error(f"Execution failed: {e}")
        raise HTTPException(status_code=500, detail=f"执行失败: {e}")

@app.get("/api/virtual-trade/equity-history")
def get_vt_equity_history(strategy_id: str):
    try:
        return vt_manager.get_equity_history(strategy_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/virtual-trade/stats")
def get_vt_stats(strategy_id: str):
    try:
        return vt_manager.get_performance_stats(strategy_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8080)
