from fastapi.testclient import TestClient
import pytest

import main


client = TestClient(main.app)


def _symbols(n):
    return [f"{idx:06d}" for idx in range(1, n + 1)]


def test_backtest_all_pool_prescreens_to_default_limit(monkeypatch):
    monkeypatch.setattr(
        main.data_manager,
        "list_local_codes",
        lambda asset_type="a_share": _symbols(5021) if asset_type == "a_share" else [],
    )

    calls = {}

    def select_symbols(limit, min_end_date=None, min_start_date=None, allow_late_start=False):
        calls["limit"] = limit
        calls["min_end_date"] = min_end_date
        calls["min_start_date"] = min_start_date
        calls["allow_late_start"] = allow_late_start
        return _symbols(limit)

    monkeypatch.setattr(main.data_manager, "select_local_a_share_symbols", select_symbols)
    monkeypatch.setattr(main.data_manager, "get_last_symbol_selection_metadata", lambda: {})

    req = main.BacktestRequest(
        start_date="2024-01-01",
        end_date="2024-12-31",
        initial_capital=1000000,
        factor="turtle",
        pool="all",
    )

    symbols, pool_ctx, warmup_start = main.prepare_backtest_universe(req)

    assert len(symbols) == main.BACKTEST_MAX_SYMBOLS
    assert calls["limit"] == main.BACKTEST_MAX_SYMBOLS
    assert calls["min_end_date"] == "2024-12-31"
    assert calls["min_start_date"] == warmup_start
    assert calls["allow_late_start"] is True
    assert pool_ctx["symbols_before_budget"] == 5021
    assert pool_ctx["symbols_count"] == main.BACKTEST_MAX_SYMBOLS
    assert pool_ctx["selection_method"] == "full_market_backtest_prescreen_v2"
    assert pool_ctx["budget_truncated"] is True


def test_backtest_all_pool_respects_requested_max_symbols(monkeypatch):
    monkeypatch.setattr(
        main.data_manager,
        "list_local_codes",
        lambda asset_type="a_share": _symbols(5021) if asset_type == "a_share" else [],
    )
    monkeypatch.setattr(main.data_manager, "select_local_a_share_symbols", lambda limit, **kwargs: _symbols(limit))
    monkeypatch.setattr(main.data_manager, "get_last_symbol_selection_metadata", lambda: {})

    req = main.BacktestRequest(
        start_date="2024-01-01",
        end_date="2024-01-31",
        initial_capital=1000000,
        factor="turtle",
        pool="all",
        max_symbols=3,
    )

    symbols, pool_ctx, _ = main.prepare_backtest_universe(req)

    assert symbols == ["000001", "000002", "000003"]
    assert pool_ctx["symbols_before_budget"] == 5021
    assert pool_ctx["symbols_count"] == 3
    assert pool_ctx["budget_truncated"] is True


def test_backtest_rejects_explicit_stocks_over_limit(monkeypatch):
    monkeypatch.setattr(
        main.data_manager,
        "list_local_codes",
        lambda asset_type="a_share": _symbols(main.BACKTEST_MAX_SYMBOLS + 1) if asset_type == "a_share" else [],
    )

    req = main.BacktestRequest(
        start_date="2024-01-01",
        end_date="2024-01-31",
        initial_capital=1000000,
        factor="turtle",
        pool="all",
        stocks=_symbols(main.BACKTEST_MAX_SYMBOLS + 1),
        max_symbols=main.BACKTEST_MAX_SYMBOLS,
    )

    with pytest.raises(main.HTTPException) as exc:
        main.prepare_backtest_universe(req)

    assert exc.value.status_code == 413
    assert "自选股票列表" in str(exc.value.detail)


def test_compare_rejects_too_many_strategies_without_truncation(monkeypatch):
    calls = {"execute": 0}

    def fake_execute(*args, **kwargs):
        calls["execute"] += 1
        return {}

    monkeypatch.setattr(main, "execute_backtest", fake_execute)

    response = client.post(
        "/api/backtest/compare",
        json={
            "strategies": ["turtle", "hfmr", "reversal", "atm", "ai_ml"],
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": 1000000,
            "pool": "core",
        },
    )

    assert response.status_code == 400
    assert calls["execute"] == 0


def test_compare_all_pool_uses_prescreened_budget(monkeypatch):
    calls = {"execute": 0}

    monkeypatch.setattr(
        main.data_manager,
        "list_local_codes",
        lambda asset_type="a_share": _symbols(5021) if asset_type == "a_share" else [],
    )
    monkeypatch.setattr(main.data_manager, "select_local_a_share_symbols", lambda limit, **kwargs: _symbols(limit))
    monkeypatch.setattr(main.data_manager, "get_last_symbol_selection_metadata", lambda: {})

    def fake_execute(req, *args, **kwargs):
        calls["execute"] += 1
        assert req.pool == "all"
        return {"resolved_pool": {"symbols_count": main.BACKTEST_MAX_SYMBOLS}}

    monkeypatch.setattr(main, "execute_backtest", fake_execute)

    response = client.post(
        "/api/backtest/compare",
        json={
            "strategies": ["turtle", "hfmr"],
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": 1000000,
            "pool": "all",
        },
    )

    assert response.status_code == 200
    assert calls["execute"] == 2


def test_factor_lab_backtest_requires_artifact_symbols_before_data_fetch(monkeypatch):
    calls = {"pool_fetch": 0}

    def fail_if_called(*args, **kwargs):
        calls["pool_fetch"] += 1
        raise AssertionError("data fetch should not run without Factor Lab artifact symbols")

    monkeypatch.setattr(main.data_manager, "get_stock_pool_data", fail_if_called)
    monkeypatch.setattr(main, "validate_factor_lab_backtest_artifacts", lambda req: None)
    monkeypatch.setattr(main, "load_factor_lab_artifact_symbols", lambda: [])

    response = client.post(
        "/api/factor-lab/backtest",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": 1000000,
            "factor": "ml_factor_ranker",
            "pool": "all",
            "max_positions": 3,
            "weight_mode": "score",
        },
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "FACTOR_LAB_BACKTEST_FAILED"
    assert calls["pool_fetch"] == 0


def test_backtest_concurrency_budget_returns_429():
    acquired = []
    try:
        for _ in range(main.BACKTEST_MAX_CONCURRENT):
            assert main.BACKTEST_SEMAPHORE.acquire(blocking=False)
            acquired.append(True)

        response = client.post(
            "/api/backtest",
            json={
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "initial_capital": 1000000,
                "factor": "turtle",
                "pool": "core",
                "stocks": ["000001"],
            },
        )

        assert response.status_code == 429
    finally:
        for _ in acquired:
            main.BACKTEST_SEMAPHORE.release()
