import pandas as pd
import pytest

from data_manager import DataFetchError, DataManager, PoolDataFetchError


def _manager(tmp_path):
    return DataManager(cache_dir=str(tmp_path / "cache"))


def _symbols(n):
    return [f"{idx:06d}" for idx in range(1, n + 1)]


JAN_2024_BUSINESS_DATES = pd.bdate_range("2024-01-01", "2024-01-31").strftime("%Y-%m-%d").tolist()


def _rows(symbols, dates):
    return pd.DataFrame(
        [
            {
                "date": date,
                "stock_code": symbol,
                "stock_name": symbol,
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 1000.0,
                "amount": 10500.0,
                "pct_chg": 0.5,
            }
            for symbol in symbols
            for date in dates
        ]
    )


def test_consolidated_fast_path_falls_back_for_missing_symbols(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    symbols = _symbols(51)
    consolidated_dir = manager.cache_dir / "consolidated"
    consolidated_dir.mkdir(parents=True)
    _rows(symbols[:50], JAN_2024_BUSINESS_DATES).to_parquet(
        consolidated_dir / "market_2024.parquet",
        index=False,
    )

    def fake_get_stock_data(symbol, start_date, end_date, auto_login=True, allow_mock=True, allow_late_start=False):
        assert symbol == symbols[50]
        return _rows([symbol], JAN_2024_BUSINESS_DATES), "CACHE"

    monkeypatch.setattr(manager, "get_stock_data", fake_get_stock_data)

    df, sources = manager.get_stock_pool_data(symbols, "2024-01-01", "2024-01-31", allow_mock=False)

    assert set(df["stock_code"].unique()) == set(symbols)
    assert sources[symbols[0]] == "CONSOLIDATED_2024"
    assert sources[symbols[50]] == "CACHE"


def test_consolidated_fast_path_raises_pool_error_when_fallback_fails(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    symbols = _symbols(51)
    consolidated_dir = manager.cache_dir / "consolidated"
    consolidated_dir.mkdir(parents=True)
    _rows(symbols[:50], JAN_2024_BUSINESS_DATES).to_parquet(
        consolidated_dir / "market_2024.parquet",
        index=False,
    )

    def fail_get_stock_data(symbol, start_date, end_date, auto_login=True, allow_mock=True, allow_late_start=False):
        raise DataFetchError(symbol, start_date, end_date, attempted_sources=["CACHE"])

    monkeypatch.setattr(manager, "get_stock_data", fail_get_stock_data)

    with pytest.raises(PoolDataFetchError) as exc:
        manager.get_stock_pool_data(symbols, "2024-01-01", "2024-01-31", allow_mock=False)

    assert symbols[50] in exc.value.failures


def test_consolidated_fast_path_rejects_insufficient_symbol_coverage(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    symbols = _symbols(51)
    consolidated_dir = manager.cache_dir / "consolidated"
    consolidated_dir.mkdir(parents=True)
    complete_symbols = symbols[:50]
    partial_symbol = symbols[50]
    pd.concat(
        [
            _rows(complete_symbols, JAN_2024_BUSINESS_DATES),
            _rows([partial_symbol], ["2024-01-15"]),
        ],
        ignore_index=True,
    ).to_parquet(consolidated_dir / "market_2024.parquet", index=False)

    fetched = []

    def fake_get_stock_data(symbol, start_date, end_date, auto_login=True, allow_mock=True, allow_late_start=False):
        fetched.append(symbol)
        return _rows([symbol], JAN_2024_BUSINESS_DATES), "CACHE"

    monkeypatch.setattr(manager, "get_stock_data", fake_get_stock_data)

    df, sources = manager.get_stock_pool_data(symbols, "2024-01-01", "2024-01-31", allow_mock=False)

    assert fetched == [partial_symbol]
    assert sources[partial_symbol] == "CACHE"
    assert set(df["stock_code"].unique()) == set(symbols)


def test_consolidated_fast_path_backfills_stock_names_from_single_symbol_cache(tmp_path):
    manager = _manager(tmp_path)
    symbols = _symbols(51)
    consolidated_dir = manager.cache_dir / "consolidated"
    consolidated_dir.mkdir(parents=True)
    consolidated = _rows(symbols, JAN_2024_BUSINESS_DATES).drop(columns=["stock_name"])
    consolidated.to_parquet(consolidated_dir / "market_2024.parquet", index=False)
    _rows(["000001"], ["2024-01-31"]).assign(stock_name="平安银行").to_parquet(
        manager.cache_dir / "000001_full_history.parquet",
        index=False,
    )

    df, sources = manager.get_stock_pool_data(symbols, "2024-01-01", "2024-01-31", allow_mock=False)

    row = df[(df["stock_code"] == "000001") & (df["date"] == "2024-01-31")].iloc[0]
    assert row["stock_name"] == "平安银行"
    assert sources["000001"] == "CONSOLIDATED_2024"


def test_range_coverage_rejects_sparse_middle_gap(tmp_path):
    manager = _manager(tmp_path)
    df = _rows(["000001"], ["2024-01-01", "2024-01-31"])

    summary = manager._coverage_summary(df, "2024-01-01", "2024-01-31")

    assert summary["ok"] is False
    assert summary["coverage_ratio"] < 0.65
    assert summary["max_consecutive_missing_business_days"] > 5


def test_get_stock_data_allows_late_listing_when_enabled(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    symbol = "001239"
    late_dates = pd.bdate_range("2024-01-15", "2024-01-30").strftime("%Y-%m-%d").tolist()
    _rows([symbol], late_dates).to_parquet(manager.get_cache_path(symbol), index=False)

    monkeypatch.setattr(manager, "_fetch_from_akshare", lambda *args, **kwargs: (pd.DataFrame(), ""))
    monkeypatch.setattr(manager, "_fetch_from_baostock", lambda *args, **kwargs: (pd.DataFrame(), ""))

    with pytest.raises(DataFetchError):
        manager.get_stock_data(symbol, "2024-01-01", "2024-01-31", allow_mock=False)

    df, source = manager.get_stock_data(
        symbol,
        "2024-01-01",
        "2024-01-31",
        allow_mock=False,
        allow_late_start=True,
    )

    assert source == "CACHE"
    assert df["date"].min() == "2024-01-15"
    assert df["date"].max() == "2024-01-30"


def test_consolidated_fast_path_allows_late_listing_when_enabled(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    symbols = _symbols(51)
    late_symbol = symbols[50]
    consolidated_dir = manager.cache_dir / "consolidated"
    consolidated_dir.mkdir(parents=True)
    late_dates = pd.bdate_range("2024-01-15", "2024-01-31").strftime("%Y-%m-%d").tolist()
    pd.concat(
        [
            _rows(symbols[:50], JAN_2024_BUSINESS_DATES),
            _rows([late_symbol], late_dates),
        ],
        ignore_index=True,
    ).to_parquet(consolidated_dir / "market_2024.parquet", index=False)

    def fail_get_stock_data(*args, **kwargs):
        raise AssertionError("late-listed consolidated symbol should not fall back to single-symbol fetch")

    monkeypatch.setattr(manager, "get_stock_data", fail_get_stock_data)

    df, sources = manager.get_stock_pool_data(
        symbols,
        "2024-01-01",
        "2024-01-31",
        allow_mock=False,
        allow_late_start=True,
    )

    assert set(df["stock_code"].unique()) == set(symbols)
    assert sources[late_symbol] == "CONSOLIDATED_2024"
    assert manager.get_last_pool_quality()["symbols_with_sparse_coverage"] == 0


def test_range_coverage_uses_market_calendar_for_exchange_holidays(tmp_path):
    manager = _manager(tmp_path)
    consolidated_dir = manager.cache_dir / "consolidated"
    consolidated_dir.mkdir(parents=True)
    trading_dates = ["2025-01-27", "2025-02-05", "2025-02-06"]
    _rows(["000001", "000002"], trading_dates).to_parquet(
        consolidated_dir / "market_2025.parquet",
        index=False,
    )
    df = _rows(["000001"], ["2025-01-27", "2025-02-05", "2025-02-06"])

    summary = manager._coverage_summary(df, "2025-01-27", "2025-02-06")

    assert summary["ok"] is True
    assert summary["coverage_ratio"] == 1.0
    assert summary["max_consecutive_missing_business_days"] == 0
