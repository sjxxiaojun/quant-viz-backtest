from types import SimpleNamespace

import pandas as pd

from position_manager import PositionManager
from strategy_registry import STRATEGY_REGISTRY


def _row(code, open_price=10.0, close_price=10.0, signal=0, score=0.0):
    return {
        "stock_code": code,
        "stock_name": code,
        "open": float(open_price),
        "close": float(close_price),
        "signal": signal,
        "score": float(score),
    }


def _split_day(rows):
    df = pd.DataFrame(rows)
    day_data = df.drop(columns=["signal", "score"]).copy()
    strategy_signals = df[["stock_code", "signal", "score"]].copy()
    return day_data, strategy_signals


def test_event_policy_expires_after_one_signal_day():
    manager = PositionManager(
        max_positions=2,
        weight_mode="equal",
        strategy_spec=STRATEGY_REGISTRY["overnight"],
    )

    day1_data, day1_signals = _split_day([
        _row("AAA", signal=1, score=1.0),
        _row("BBB", signal=0, score=0.0),
    ])
    day2_target = manager.generate_target_weights("2026-01-01", day1_data, day1_signals, current_positions={})
    assert day2_target == {"AAA": 1.0}
    assert manager.last_decision_info["raw_signal_count"] == 1
    assert manager.last_decision_info["selected_signal_count"] == 1
    assert manager.last_decision_info["ranking_basis"] == "score"

    current_positions = {
        "AAA": SimpleNamespace(entry_date="2026-01-02", avg_price=10.0),
    }
    day2_data, day2_signals = _split_day([
        _row("AAA", signal=0, score=0.0),
        _row("BBB", signal=0, score=0.0),
    ])
    day3_target = manager.generate_target_weights("2026-01-02", day2_data, day2_signals, current_positions=current_positions)
    assert day3_target == {}
    assert manager.last_decision_info["raw_signal_count"] == 0
    assert manager.last_decision_info["selected_signal_count"] == 0


def test_event_policy_does_not_extend_holding_on_repeated_signal():
    manager = PositionManager(
        max_positions=2,
        weight_mode="equal",
        strategy_spec=STRATEGY_REGISTRY["overnight"],
    )

    day1_data, day1_signals = _split_day([
        _row("AAA", signal=1, score=1.0),
    ])
    assert manager.generate_target_weights("2026-01-01", day1_data, day1_signals, current_positions={}) == {"AAA": 1.0}

    current_positions = {
        "AAA": SimpleNamespace(entry_date="2026-01-02", avg_price=10.0),
    }
    day2_data, day2_signals = _split_day([
        _row("AAA", signal=1, score=1.0),
    ])
    # 对严格 T+1 事件策略，重复信号不应刷新持有天数
    assert manager.generate_target_weights("2026-01-02", day2_data, day2_signals, current_positions=current_positions) == {}


def test_ranking_policy_only_holds_current_selected_names():
    manager = PositionManager(
        max_positions=2,
        weight_mode="score",
        strategy_spec=STRATEGY_REGISTRY["ai_ml"],
    )

    day1_data, day1_signals = _split_day([
        _row("AAA", signal=1, score=2.0),
        _row("BBB", signal=1, score=1.0),
        _row("CCC", signal=0, score=0.2),
    ])
    day2_target = manager.generate_target_weights("2026-01-01", day1_data, day1_signals, current_positions={})
    assert set(day2_target.keys()) == {"AAA", "BBB"}

    current_positions = {
        "AAA": SimpleNamespace(entry_date="2026-01-02", avg_price=10.0),
        "BBB": SimpleNamespace(entry_date="2026-01-02", avg_price=10.0),
    }
    day2_data, day2_signals = _split_day([
        _row("AAA", signal=0, score=0.2),
        _row("BBB", signal=1, score=1.5),
        _row("CCC", signal=1, score=1.4),
    ])
    day3_target = manager.generate_target_weights("2026-01-02", day2_data, day2_signals, current_positions=current_positions)
    assert set(day3_target.keys()) == {"BBB", "CCC"}
    assert "AAA" not in day3_target
    assert manager.last_decision_info["dropped_by_max_positions"] == 0


def test_stateful_policy_keeps_holding_on_zero_signal():
    manager = PositionManager(
        max_positions=2,
        weight_mode="equal",
        strategy_spec=STRATEGY_REGISTRY["turtle"],
    )

    day1_data, day1_signals = _split_day([
        _row("AAA", signal=1, score=1.0),
    ])
    day2_target = manager.generate_target_weights("2026-01-01", day1_data, day1_signals, current_positions={})
    assert day2_target == {"AAA": 1.0}

    current_positions = {
        "AAA": SimpleNamespace(entry_date="2026-01-02", avg_price=10.0),
    }
    day2_data, day2_signals = _split_day([
        _row("AAA", signal=0, score=0.0),
    ])
    day3_target = manager.generate_target_weights("2026-01-02", day2_data, day2_signals, current_positions=current_positions)
    assert day3_target == {"AAA": 1.0}
