import pandas as pd
import pytest

from data_manager import DataManager
from factor_lab.data_prep import standardize_market_frame


def _make_manager(tmp_path):
    return DataManager(cache_dir=str(tmp_path / "cache"))


def _cn_row(
    date,
    *,
    open_price=10.0,
    high=10.4,
    low=9.8,
    close=10.2,
    volume=1000.0,
    amount=10200.0,
    pct_chg=1.2,
    turn=2.3,
    amplitude=6.1,
    stock_code="sz.000001",
    stock_name="",
):
    return {
        "日期": date,
        "开盘": open_price,
        "最高": high,
        "最低": low,
        "收盘": close,
        "成交量": volume,
        "成交额": amount,
        "涨跌幅": pct_chg,
        "换手率": turn,
        "振幅": amplitude,
        "股票代码": stock_code,
        "名称": stock_name,
    }


def test_normalize_market_frame_maps_cn_columns_and_keeps_latest_duplicate(tmp_path):
    manager = _make_manager(tmp_path)
    raw = pd.DataFrame(
        [
            _cn_row("2026-01-03", close=10.30, turn=2.5, amplitude=5.8),
            _cn_row("2026-01-02", close=10.10, turn=2.0, amplitude=5.1),
            _cn_row("2026-01-03", close=10.40, turn=3.1, amplitude=6.2),
        ]
    )

    normalized = manager._normalize_market_frame("000001", raw)

    assert normalized["date"].tolist() == ["2026-01-02", "2026-01-03"]
    latest_row = normalized.iloc[-1]
    assert latest_row["close"] == pytest.approx(10.40)
    assert latest_row["turn"] == pytest.approx(3.1)
    assert latest_row["amplitude"] == pytest.approx(6.2)
    assert latest_row["stock_code"] == "000001"
    assert latest_row["stock_name"] == "平安银行"


def test_factor_lab_standardize_market_frame_backfills_turnover_alias_and_amplitude():
    raw = pd.DataFrame(
        [
            _cn_row("2026-01-02", amplitude=None, turn=2.6),
            _cn_row("2026-01-03", open_price=10.1, high=10.6, low=9.9, close=10.4, amplitude=None, turn=2.9),
        ]
    )

    standardized = standardize_market_frame(raw)

    assert {"turn", "turnover_rate", "amplitude"}.issubset(standardized.columns)
    assert standardized["turn"].tolist() == pytest.approx([2.6, 2.9])
    assert standardized["turnover_rate"].tolist() == pytest.approx([2.6, 2.9])
    assert standardized["amplitude"].notna().all()


def test_normalize_market_frame_provides_turnover_rate_alias_for_ml_consumers(tmp_path):
    manager = _make_manager(tmp_path)
    normalized = manager._normalize_market_frame("000001", pd.DataFrame([_cn_row("2026-01-02")]))

    assert normalized["turnover_rate"].tolist() == normalized["turn"].tolist()


def test_mock_data_contains_factor_lab_minimum_market_columns(tmp_path):
    manager = _make_manager(tmp_path)

    mock_df = manager._generate_mock_data("000001", "2026-01-01", "2026-01-15")

    assert {"amplitude", "turnover_rate"}.issubset(mock_df.columns)
