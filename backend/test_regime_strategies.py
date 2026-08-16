"""Regime 策略约束测试：

1. 熊市 (regime==2) 必须空仓——哨兵分数不得被排名逻辑选中买入
   （extra_strategies_pro.calculate_ai_adaptive_signals_pro 与
   multi_factor_engine.RegimeAdaptiveFactorStrategy）。
2. pro_plus 三态 regime 与因子映射方向锁定：趋势市用动量 (f_trend_z)，
   震荡/平静市用反转 (f_swing_z)。
"""
import numpy as np
import pandas as pd

from strategies.extra_strategies_pro import calculate_ai_adaptive_signals_pro
from strategies.extra_strategies_pro_plus import (
    calculate_ai_adaptive_signals_pro_plus,
    REGIME_CALM,
    REGIME_TREND,
    REGIME_CHOPPY,
)
from strategies.multi_factor_engine import RegimeAdaptiveFactorStrategy


def _build_market(codes, n_calm=70, n_bear=15, calm_pct=0.5, bear_pct=-3.0):
    """前 n_calm 天温和上涨（低波），后 n_bear 天每日按 bear_pct 涨跌。"""
    rows = []
    base_date = pd.Timestamp("2025-01-01")
    for idx, code in enumerate(codes):
        close = 10.0 + idx
        for i in range(n_calm + n_bear):
            pct = calm_pct if i < n_calm else bear_pct
            close = close * (1 + pct / 100.0) * (1 + 0.0005 * idx)
            rows.append(
                {
                    "date": (base_date + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                    "stock_code": code,
                    "close": close,
                    "open": close * 0.999,
                    "high": close * 1.005,
                    "low": close * 0.995,
                    "pct_chg": pct,
                    "volume": 10000.0 + idx * 100,
                    "amount": close * (10000.0 + idx * 100),
                    "pb": 2.0 + 0.1 * idx,
                    "pe": 15.0 + idx,
                    "turn": 2.0,
                }
            )
    return pd.DataFrame(rows)


def test_ai_adaptive_pro_bear_regime_holds_cash():
    df = _build_market(["AAA", "BBB", "CCC"])
    result = calculate_ai_adaptive_signals_pro(df)

    bear_rows = result[result["regime"] == 2]
    assert not bear_rows.empty, "测试数据必须触发熊市 regime"
    assert (bear_rows["signal"] != 1).all(), "熊市 (regime==2) 不允许出现买入信号"

    # 非熊市阶段应存在买入信号，确保测试非空转
    non_bear = result[result["regime"] != 2]
    assert (non_bear["signal"] == 1).any()


def test_ai_adaptive_pro_bear_threshold_uses_percentage_units():
    """mkt_trend 阈值为百分数口径：20 日累计 -4% 不应判熊，-6% 应判熊。"""
    mild = _build_market(["M1", "M2", "M3"], n_calm=70, n_bear=30, calm_pct=0.5, bear_pct=-0.2)
    mild_result = calculate_ai_adaptive_signals_pro(mild)
    assert not (mild_result["regime"] == 2).any(), "20 日累计跌幅仅 -4%，不应触发熊市空仓"

    strong = _build_market(["S1", "S2", "S3"], n_calm=70, n_bear=30, calm_pct=0.5, bear_pct=-0.3)
    strong_result = calculate_ai_adaptive_signals_pro(strong)
    assert (strong_result["regime"] == 2).any(), "20 日累计跌幅 -6%，应触发熊市空仓"


def test_regime_adaptive_factor_strategy_bear_regime_holds_cash():
    df = _build_market(["S1", "S2", "S3", "S4", "S5", "S6"])
    result = RegimeAdaptiveFactorStrategy(top_n=5).calculate_signals(df)

    bear_rows = result[result["regime"] == 2]
    assert not bear_rows.empty, "测试数据必须触发熊市 regime"
    assert (bear_rows["signal"] != 1).all(), "熊市 (regime==2) 不允许出现买入信号"

    non_bear = result[result["regime"] != 2]
    assert (non_bear["signal"] == 1).any()


def _build_three_phase_market(codes):
    """平静(40天, 恒定+0.1%) -> 高波震荡(30天, ±2%交替) -> 趋势(30天, 恒定+1%)。"""
    rows = []
    base_date = pd.Timestamp("2025-01-01")
    phases = [0.1] * 40 + [2.0 if i % 2 == 0 else -2.0 for i in range(30)] + [1.0] * 30
    for idx, code in enumerate(codes):
        close = 10.0 + idx * 2
        for i, pct in enumerate(phases):
            # 各股叠加不同微小漂移，保证截面分数有差异
            close = close * (1 + pct / 100.0) * (1 + 0.0008 * idx)
            rows.append(
                {
                    "date": (base_date + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                    "stock_code": code,
                    "close": close,
                    "pct_chg": pct,
                    "volume": 10000.0 + idx * 100,
                }
            )
    return pd.DataFrame(rows)


def test_pro_plus_regime_factor_mapping_locked():
    df = _build_three_phase_market(["AAA", "BBB", "CCC"])
    result = calculate_ai_adaptive_signals_pro_plus(df)

    # 三态都必须在测试数据中出现
    present = set(result["regime"].unique())
    assert REGIME_CALM in present, "0.1% 级别的平静市不应被 0.05 的旧阈值误判成趋势市"
    assert REGIME_TREND in present
    assert REGIME_CHOPPY in present

    valid = result.dropna(subset=["score", "f_trend_z", "f_swing_z"])

    trend_rows = valid[valid["regime"] == REGIME_TREND]
    assert not trend_rows.empty
    assert np.allclose(trend_rows["score"], trend_rows["f_trend_z"]), \
        "趋势市必须使用动量因子 f_trend_z"

    choppy_rows = valid[valid["regime"] == REGIME_CHOPPY]
    assert not choppy_rows.empty
    assert np.allclose(choppy_rows["score"], choppy_rows["f_swing_z"]), \
        "高波震荡市必须使用反转因子 f_swing_z"

    calm_rows = valid[valid["regime"] == REGIME_CALM]
    if not calm_rows.empty:
        assert np.allclose(calm_rows["score"], calm_rows["f_swing_z"]), \
            "平静市沿用反转因子 f_swing_z"
