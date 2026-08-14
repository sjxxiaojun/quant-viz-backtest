"""注册表装配约束测试。"""
from strategy_registry import STRATEGY_REGISTRY


def test_aph_pro_uses_close_to_next_open_execution():
    """aph_pro 的收益来源是 D 日收盘 -> D+1 开盘的隔夜溢价，
    必须以 signal_close_to_next_open 执行，否则回测衡量的是另一个策略。"""
    assert STRATEGY_REGISTRY["aph_pro"].execution_mode == "signal_close_to_next_open"


def test_next_day_relay_strategies_keep_default_execution():
    """weak_to_strong / limit_up_doji 为次日接力型（D+1 开盘买入），保持默认执行模式。"""
    assert STRATEGY_REGISTRY["weak_to_strong"].execution_mode == "next_open_rebalance"
    assert STRATEGY_REGISTRY["limit_up_doji"].execution_mode == "next_open_rebalance"


def test_ai_ml_and_pro_plus_share_single_implementation():
    """ai_ml 与 ai_ml_pro_plus 为同一因子配置，注册表两个 id 指向同一策略实例。"""
    assert (
        STRATEGY_REGISTRY["ai_ml"].func.__self__
        is STRATEGY_REGISTRY["ai_ml_pro_plus"].func.__self__
    )


def test_overnight_family_execution_mode():
    for key in ("overnight", "overnight_quality", "overnight_balanced", "overnight_ranked"):
        assert STRATEGY_REGISTRY[key].execution_mode == "signal_close_to_next_open"
