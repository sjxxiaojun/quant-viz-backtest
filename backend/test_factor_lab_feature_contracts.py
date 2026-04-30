import pandas as pd
import pytest

from data_manager import DataManager
from strategies.signal_factory import (
    _prepare_overnight_features,
    calculate_overnight_hold_signals_balanced,
)


def _build_history(
    code: str,
    *,
    signal_close: float,
    high: float,
    low: float,
    volume: float,
    turnover: float,
):
    rows = []
    base_date = pd.Timestamp("2026-01-01")
    for i in range(10):
        rows.append(
            {
                "date": (base_date + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                "stock_code": code,
                "stock_name": code,
                "open": 10.0,
                "high": 10.1,
                "low": 9.9,
                "close": 10.0 + (0.01 * i),
                "volume": 1000.0,
                "amount": 10000.0,
                "amplitude": 2.0,
                "pct_chg": 0.5,
                "turnover_rate": 1.0,
            }
        )

    rows.append(
        {
            "date": (base_date + pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
            "stock_code": code,
            "stock_name": code,
            "open": 10.2,
            "high": high,
            "low": low,
            "close": signal_close,
            "volume": volume,
            "amount": volume * signal_close,
            "amplitude": (high - low) / 10.09 * 100,
            "pct_chg": ((signal_close / 10.09) - 1) * 100,
            "turnover_rate": turnover,
        }
    )
    return rows


def _build_cn_history_rows():
    rows = []
    base_date = pd.Timestamp("2026-01-01")
    for i in range(10):
        rows.append(
            {
                "日期": (base_date + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                "股票代码": "sz.000001",
                "名称": "",
                "开盘": 10.0,
                "最高": 10.1,
                "最低": 9.9,
                "收盘": 10.0 + (0.01 * i),
                "成交量": 1000.0,
                "成交额": 10000.0,
                "涨跌幅": 0.5,
                "换手率": 1.0,
                "振幅": 2.0,
            }
        )

    rows.append(
        {
            "日期": "2026-01-11",
            "股票代码": "sz.000001",
            "名称": "",
            "开盘": 10.2,
            "最高": 10.56,
            "最低": 10.18,
            "收盘": 10.55,
            "成交量": 1600.0,
            "成交额": 16880.0,
            "涨跌幅": ((10.55 / 10.09) - 1) * 100,
            "换手率": 2.5,
            "振幅": (10.56 - 10.18) / 10.09 * 100,
        }
    )
    return rows


def test_prepare_overnight_features_exposes_ml_ready_feature_columns():
    df = pd.DataFrame(
        _build_history("AAA", signal_close=10.55, high=10.56, low=10.18, volume=1600.0, turnover=2.0)
        + _build_history("BBB", signal_close=10.52, high=10.54, low=10.18, volume=1550.0, turnover=2.1)
    )

    features = _prepare_overnight_features(df)
    signal_day = features[(features["date"] == "2026-01-11") & (features["stock_code"] == "AAA")].iloc[0]

    required_columns = {
        "prev_close",
        "ma5",
        "ma10",
        "vol_ma5",
        "close_strength",
        "pct_chg_real",
        "vol_ratio",
        "intraday_ret",
        "body_ratio",
        "open_gap",
        "above_ma10",
        "market_breadth_ma10",
        "signal",
        "raw_signal",
        "score",
    }

    assert required_columns.issubset(features.columns)
    assert pd.notna(signal_day["prev_close"])
    assert pd.notna(signal_day["ma10"])
    assert pd.notna(signal_day["market_breadth_ma10"])
    assert signal_day["signal"] == 0
    assert signal_day["raw_signal"] == 0
    assert signal_day["score"] == pytest.approx(0.0)


def test_overnight_balanced_retains_raw_signal_after_top_n_filtering():
    df = pd.DataFrame(
        _build_history("AAA", signal_close=10.55, high=10.56, low=10.18, volume=1600.0, turnover=2.0)
        + _build_history("BBB", signal_close=10.53, high=10.54, low=10.20, volume=1580.0, turnover=2.1)
        + _build_history("CCC", signal_close=10.51, high=10.52, low=10.20, volume=1540.0, turnover=2.2)
    )

    result = calculate_overnight_hold_signals_balanced(df)
    signal_day = result[result["date"] == "2026-01-11"].sort_values("stock_code")

    assert int(signal_day["raw_signal"].sum()) == 3
    assert int(signal_day["signal"].sum()) == 2
    dropped = signal_day[(signal_day["raw_signal"] == 1) & (signal_day["signal"] == 0)]
    assert len(dropped) == 1


def test_overnight_balanced_accepts_data_manager_normalized_frame(tmp_path):
    manager = DataManager(cache_dir=str(tmp_path / "cache"))
    normalized = manager._normalize_market_frame("000001", pd.DataFrame(_build_cn_history_rows()))

    result = calculate_overnight_hold_signals_balanced(normalized)

    assert "signal" in result.columns
