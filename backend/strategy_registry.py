from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import pandas as pd

from strategies.atm_filter import calculate_atm_signals
from strategies.extra_strategies import (
    calculate_reversal_vol_signals,
    calculate_turtle_signals,
    calculate_hfmr_signals,
    calculate_sector_alpha_signals,
    calculate_etf_bottom_signals,
    calculate_blackhorse_signals,
    calculate_ai_adaptive_signals,
)
from strategies.signal_factory import (
    calculate_overnight_hold_signals,
    calculate_overnight_hold_signals_quality,
    calculate_overnight_hold_signals_balanced,
    calculate_overnight_hold_signals_ranked,
    calculate_weak_to_strong_signals,
    calculate_limit_up_doji_signals,
)
from strategies.extra_strategies_pro import (
    calculate_ai_adaptive_signals_pro,
    calculate_blackhorse_signals_pro,
    calculate_aph_pro_signals,
)
from strategies.extra_strategies_pro_plus import (
    calculate_ai_adaptive_signals_pro_plus,
    calculate_blackhorse_signals_pro_plus,
)
from strategies.multi_factor_engine import (
    MultiFactorStrategy,
    FactorConfig,
    factor_low_volatility,
    factor_value,
    factor_quality,
    factor_turnover,
    factor_size,
    factor_volatility_stability,
    factor_volatility_clustering,
    factor_short_term_reversal,
    RegimeAdaptiveFactorStrategy,
)
from factor_lab.strategy import (
    calculate_ml_factor_filter_signals,
    calculate_ml_factor_ranker_signals,
)
from strategies.sector_strategy import calculate_power_energy_signals


@dataclass(frozen=True)
class StrategySpec:
    key: str
    name: str
    func: Callable[[pd.DataFrame], pd.DataFrame]
    pool: str
    category: str
    signal_type: str = "stateful"
    holding_policy: str = "sell_on_minus_one"
    default_max_hold_days: Optional[int] = None
    default_take_profit: Optional[float] = None
    execution_mode: str = "next_open_rebalance"
    requires_artifact: bool = False

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "func": self.func,
            "pool": self.pool,
            "category": self.category,
            "signal_type": self.signal_type,
            "holding_policy": self.holding_policy,
            "default_max_hold_days": self.default_max_hold_days,
            "default_take_profit": self.default_take_profit,
            "execution_mode": self.execution_mode,
            "requires_artifact": self.requires_artifact,
        }


STRATEGY_REGISTRY: Dict[str, StrategySpec] = {
    "atm": StrategySpec(
        key="atm",
        name="趋势增强 (ATM Filter)",
        func=calculate_atm_signals,
        pool="core",
        category="经典量化",
        signal_type="stateful",
        holding_policy="sell_on_minus_one",
    ),
    "reversal": StrategySpec(
        key="reversal",
        name="超跌反转 (Reversal)",
        func=calculate_reversal_vol_signals,
        pool="core",
        category="经典量化",
        signal_type="stateful",
        holding_policy="sell_on_minus_one",
    ),
    "turtle": StrategySpec(
        key="turtle",
        name="海龟法则 (高频版)",
        func=calculate_turtle_signals,
        pool="core",
        category="经典量化",
        signal_type="stateful",
        holding_policy="sell_on_minus_one",
    ),
    "hfmr": StrategySpec(
        key="hfmr",
        name="高频均值回归 (HFMR)",
        func=calculate_hfmr_signals,
        pool="core",
        category="经典量化",
        signal_type="stateful",
        holding_policy="sell_on_minus_one",
    ),
    "sector_alpha": StrategySpec(
        key="sector_alpha",
        name="行业优选 (Alpha)",
        func=calculate_sector_alpha_signals,
        pool="core",
        category="经典量化",
        signal_type="ranking",
        holding_policy="hold_while_selected",
    ),
    "ai_ml": StrategySpec(
        key="ai_ml",
        name="防御多因子模型 (Defense)",
        func=MultiFactorStrategy(
            factors=[
                FactorConfig("low_vol", factor_low_volatility, weight=0.42),
                FactorConfig("value", factor_value, weight=0.22),
                FactorConfig("turnover", factor_turnover, weight=0.08),
            ],
            top_n=2,
        ).calculate_signals,
        pool="core",
        category="多因子类",
        signal_type="ranking",
        holding_policy="hold_while_selected",
    ),
    "bottom_fishing": StrategySpec(
        key="bottom_fishing",
        name="ETF 技术抗底 (进攻版)",
        func=lambda df: calculate_etf_bottom_signals(df, mode="aggressive"),
        pool="etf",
        category="ETF专属",
        signal_type="ranking",
        holding_policy="hold_while_selected",
    ),
    "bottom_fishing_stable": StrategySpec(
        key="bottom_fishing_stable",
        name="ETF 技术抗底 (稳定版)",
        func=lambda df: calculate_etf_bottom_signals(df, mode="stable"),
        pool="etf",
        category="ETF专属",
        signal_type="ranking",
        holding_policy="hold_while_selected",
    ),
    "overnight": StrategySpec(
        key="overnight",
        name="一夜持股 (Signal Factory)",
        func=calculate_overnight_hold_signals,
        pool="blackhorse",
        category="信号工厂 (高共识)",
        signal_type="event",
        holding_policy="timeout_exit",
        default_max_hold_days=1,
        execution_mode="signal_close_to_next_open",
    ),
    "overnight_quality": StrategySpec(
        key="overnight_quality",
        name="一夜持股 质量收缩版",
        func=calculate_overnight_hold_signals_quality,
        pool="blackhorse",
        category="信号工厂 (高共识)",
        signal_type="event",
        holding_policy="timeout_exit",
        default_max_hold_days=1,
        execution_mode="signal_close_to_next_open",
    ),
    "overnight_balanced": StrategySpec(
        key="overnight_balanced",
        name="一夜持股 平衡推荐版",
        func=calculate_overnight_hold_signals_balanced,
        pool="blackhorse",
        category="信号工厂 (高共识)",
        signal_type="event",
        holding_policy="timeout_exit",
        default_max_hold_days=1,
        execution_mode="signal_close_to_next_open",
    ),
    "overnight_ranked": StrategySpec(
        key="overnight_ranked",
        name="一夜持股 打分排序版",
        func=calculate_overnight_hold_signals_ranked,
        pool="blackhorse",
        category="信号工厂 (高共识)",
        signal_type="event",
        holding_policy="timeout_exit",
        default_max_hold_days=1,
        execution_mode="signal_close_to_next_open",
    ),
    "weak_to_strong": StrategySpec(
        key="weak_to_strong",
        name="弱转强 (Signal Factory)",
        func=calculate_weak_to_strong_signals,
        pool="blackhorse",
        category="信号工厂 (高共识)",
        signal_type="event",
        holding_policy="timeout_exit",
        default_max_hold_days=1,
    ),
    "limit_up_doji": StrategySpec(
        key="limit_up_doji",
        name="涨停后十字星",
        func=calculate_limit_up_doji_signals,
        pool="blackhorse",
        category="信号工厂 (高共识)",
        signal_type="event",
        holding_policy="timeout_exit",
        default_max_hold_days=1,
    ),
    "blackhorse": StrategySpec(
        key="blackhorse",
        name="动量猎手 (Blackhorse)",
        func=calculate_blackhorse_signals,
        pool="blackhorse",
        category="动量类",
        signal_type="stateful",
        holding_policy="sell_on_minus_one",
    ),
    "ai_adaptive": StrategySpec(
        key="ai_adaptive",
        name="自适应双模策略 (Adaptive)",
        func=calculate_ai_adaptive_signals,
        pool="core",
        category="自适应类",
        signal_type="stateful",
        holding_policy="sell_on_minus_one",
    ),
    "ai_ml_pro": StrategySpec(
        key="ai_ml_pro",
        name="防御多因子 Pro (Defense Pro)",
        func=MultiFactorStrategy(
            factors=[
                FactorConfig("low_vol", factor_low_volatility, weight=0.4),
                FactorConfig("value", factor_value, weight=0.3),
                FactorConfig("quality", factor_quality, weight=0.3),
            ],
            top_n=2,
            score_threshold=0.5,
            liquidity_filter_pct=0.2,
        ).calculate_signals,
        pool="core",
        category="多因子类 (Pro)",
        signal_type="ranking",
        holding_policy="hold_while_selected",
    ),
    "ai_adaptive_pro": StrategySpec(
        key="ai_adaptive_pro",
        name="市场环境切换 Pro",
        func=calculate_ai_adaptive_signals_pro,
        pool="core",
        category="自适应类 (Pro)",
        signal_type="ranking",
        holding_policy="hold_while_selected",
    ),
    "blackhorse_pro": StrategySpec(
        key="blackhorse_pro",
        name="动量猎手 Pro",
        func=calculate_blackhorse_signals_pro,
        pool="blackhorse",
        category="动量类 (Pro)",
        signal_type="ranking",
        holding_policy="hold_while_selected",
    ),
    "aph_pro": StrategySpec(
        key="aph_pro",
        name="APH Pro (T+1 Down-frequency)",
        func=calculate_aph_pro_signals,
        pool="blackhorse",
        category="小G量化战队 (Pro+)",
        signal_type="event",
        holding_policy="timeout_exit",
        default_max_hold_days=1,
    ),
    "ai_ml_pro_plus": StrategySpec(
        key="ai_ml_pro_plus",
        name="防御多因子原味版",
        func=MultiFactorStrategy(
            factors=[
                FactorConfig("low_vol", factor_low_volatility, weight=0.42),
                FactorConfig("value", factor_value, weight=0.22),
                FactorConfig("turnover", factor_turnover, weight=0.08),
            ],
            top_n=2,
        ).calculate_signals,
        pool="core",
        category="多因子类 (Original)",
        signal_type="ranking",
        holding_policy="hold_while_selected",
    ),
    "ml_factor_ranker": StrategySpec(
        key="ml_factor_ranker",
        name="ML 因子排序策略",
        func=calculate_ml_factor_ranker_signals,
        pool="core",
        category="Factor Lab",
        signal_type="ranking",
        holding_policy="hold_while_selected",
        requires_artifact=True,
    ),
    "ml_factor_filter": StrategySpec(
        key="ml_factor_filter",
        name="ML 因子过滤策略",
        func=calculate_ml_factor_filter_signals,
        pool="core",
        category="Factor Lab",
        signal_type="ranking",
        holding_policy="hold_while_selected",
        requires_artifact=True,
    ),
    "ai_adaptive_pro_plus": StrategySpec(
        key="ai_adaptive_pro_plus",
        name="自适应双模原味版",
        func=calculate_ai_adaptive_signals_pro_plus,
        pool="core",
        category="自适应类 (Original)",
        signal_type="ranking",
        holding_policy="hold_while_selected",
    ),
    "blackhorse_pro_plus": StrategySpec(
        key="blackhorse_pro_plus",
        name="动量加速原味版",
        func=calculate_blackhorse_signals_pro_plus,
        pool="blackhorse",
        category="动量类 (Original)",
        signal_type="ranking",
        holding_policy="hold_while_selected",
    ),
    "smallcap_lowvol": StrategySpec(
        key="smallcap_lowvol",
        name="全 A 股小市值低波 Pro+",
        func=MultiFactorStrategy(
            factors=[
                FactorConfig("size", factor_size, weight=0.5),
                FactorConfig("stability", factor_volatility_stability, weight=0.3),
                FactorConfig("value", factor_value, weight=0.2),
            ],
            top_n=5,
            liquidity_filter_pct=0.1,
        ).calculate_signals,
        pool="core",
        category="多因子类 (Pro+)",
        signal_type="ranking",
        holding_policy="hold_while_selected",
    ),
    "regime_adaptive": StrategySpec(
        key="regime_adaptive",
        name="环境自适应动态因子 (Adaptive Pro+)",
        func=RegimeAdaptiveFactorStrategy(top_n=5).calculate_signals,
        pool="core",
        category="多因子类 (Pro+)",
        signal_type="ranking",
        holding_policy="hold_while_selected",
    ),
    "alpha_miner_2026": StrategySpec(
        key="alpha_miner_2026",
        name="Alpha Miner 2026 (Marathon Edition)",
        func=MultiFactorStrategy(
            factors=[
                FactorConfig("rev_1", factor_short_term_reversal, weight=0.5),
                FactorConfig("vol_clustering", factor_volatility_clustering, weight=-0.4), # Inverse signal
                FactorConfig("low_vol", factor_low_volatility, weight=0.1),
            ],
            top_n=5,
            liquidity_filter_pct=0.2,
        ).calculate_signals,
        pool="core",
        category="小G量化战队 (Mined)",
        signal_type="ranking",
        holding_policy="hold_while_selected",
    ),
    "power_energy": StrategySpec(
        key="power_energy",
        name="电力与储能 (Regime Switching)",
        func=calculate_power_energy_signals,
        pool="power_energy",
        category="行业轮动",
        signal_type="ranking",
        holding_policy="hold_while_selected",
    ),
}


def get_strategy_spec(strategy_key: str) -> Optional[StrategySpec]:
    return STRATEGY_REGISTRY.get(strategy_key)
