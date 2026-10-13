"""Public request contracts shared by API routes and workers."""
from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from datetime import date
BACKTEST_MAX_SYMBOLS = FACTOR_LAB_MAX_SYMBOLS = 500
FACTOR_LAB_KEEP_RECENT_RUNS = 5

class DateRangeRequest(BaseModel):
    @field_validator('start_date', 'end_date', check_fields=False)
    @classmethod
    def iso_date(cls, value):
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError('日期必须为 YYYY-MM-DD')
        return value

    @model_validator(mode='after')
    def ordered_dates(self):
        if self.start_date > self.end_date:
            raise ValueError('开始日期不能晚于结束日期')
        return self


class BacktestRequest(DateRangeRequest):
    model_config = ConfigDict(extra="forbid")
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
    # 证券交易印花税自 2023-08-28 起由 0.1% 降至 0.05%（卖出单边），历史分段费率由引擎层按成交日期处理。
    stamp_tax_rate: float = Field(default=0.0005, ge=0.0, le=0.1)
    slippage_rate: float = Field(default=0.0003, ge=0.0, le=0.1)
    # 收盘（尾盘）成交滑点。None = 不指定，沿用引擎默认 0.0015（既有回测结果不变）；
    # 显式传值时直接生效，解析规则见 resolve_close_slippage_rate()。
    close_slippage_rate: Optional[float] = Field(default=None, ge=0.0, le=0.1)
    commission_min: float = Field(default=5.0, ge=0.0, le=1000.0)
    allow_mock: bool = False
    price_mode: Literal["strict_raw", "approximate_adjusted"] = "strict_raw"
    same_close_approximation: bool = False


class BacktestJobSubmitResponse(BaseModel):
    job_id: str


class BacktestJobStatusResponse(BaseModel):
    job_id: str
    status: str
    created_at: float
    updated_at: float
    error: Optional[str] = None
    stage: Optional[str] = None


class CompareRequest(DateRangeRequest):
    model_config = ConfigDict(extra="forbid")
    price_mode: Literal["strict_raw", "approximate_adjusted"] = "strict_raw"
    same_close_approximation: bool = False
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
    # 证券交易印花税自 2023-08-28 起由 0.1% 降至 0.05%（卖出单边），历史分段费率由引擎层按成交日期处理。
    stamp_tax_rate: float = Field(default=0.0005, ge=0.0, le=0.1)
    slippage_rate: float = Field(default=0.0003, ge=0.0, le=0.1)
    # 与 BacktestRequest 同义：None = 沿用引擎默认收盘滑点。
    close_slippage_rate: Optional[float] = Field(default=None, ge=0.0, le=0.1)
    commission_min: float = Field(default=5.0, ge=0.0, le=1000.0)
    allow_mock: bool = False


class FactorLabRunRequest(DateRangeRequest):
    enable_hist_gradient_boosting: bool = False
    price_mode: Literal["strict_raw", "approximate_adjusted"] = "strict_raw"
    model_config = ConfigDict(extra="forbid")
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
    # 证券交易印花税自 2023-08-28 起由 0.1% 降至 0.05%（卖出单边），历史分段费率由引擎层按成交日期处理。
    stamp_tax_rate: float = Field(default=0.0005, ge=0.0, le=0.1)
    slippage_rate: float = Field(default=0.0003, ge=0.0, le=0.1)
    # 与 BacktestRequest 同义：None = 沿用引擎默认收盘滑点。
    close_slippage_rate: Optional[float] = Field(default=None, ge=0.0, le=0.1)
    commission_min: float = Field(default=5.0, ge=0.0, le=1000.0)


class FactorLabBacktestRequest(BacktestRequest):
    enable_hist_gradient_boosting: bool = False
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
    # 证券交易印花税自 2023-08-28 起由 0.1% 降至 0.05%（卖出单边），历史分段费率由引擎层按成交日期处理。
    stamp_tax_rate: float = Field(default=0.0005, ge=0.0, le=0.1)
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

