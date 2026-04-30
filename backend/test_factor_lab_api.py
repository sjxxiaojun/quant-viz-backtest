import pandas as pd
import pytest
from fastapi.testclient import TestClient
from factor_lab.pipeline import _config_hash
from factor_lab.pipeline import load_latest_result as pipeline_load_latest_result

import main


client = TestClient(main.app)


def test_factor_lab_artifact_snapshot_restores_manifest(tmp_path):
    assert "latest_manifest.json" in main.FACTOR_LAB_TRACKED_ARTIFACTS
    for name in main.FACTOR_LAB_TRACKED_ARTIFACTS:
        (tmp_path / name).write_text(f"old-{name}", encoding="utf-8")

    snapshot = main.snapshot_factor_lab_artifacts(tmp_path)
    for name in main.FACTOR_LAB_TRACKED_ARTIFACTS:
        (tmp_path / name).write_text(f"new-{name}", encoding="utf-8")

    main.restore_factor_lab_artifacts(snapshot)

    for name in main.FACTOR_LAB_TRACKED_ARTIFACTS:
        assert (tmp_path / name).read_text(encoding="utf-8") == f"old-{name}"


def test_factor_lab_results_api_returns_latest_result(monkeypatch):
    monkeypatch.setattr(
        main,
        "load_latest_result",
        lambda: {"summary": {"status": "ok", "pool": "core"}, "factor_ranking": [{"factor": "mom_20d"}]},
    )
    monkeypatch.setattr(main, "persist_factor_lab_result", lambda result, report_dir: None)

    resp = client.get("/api/factor-lab/results")

    assert resp.status_code == 200
    assert resp.json()["summary"]["status"] == "ok"
    assert resp.json()["factor_ranking"][0]["factor"] == "mom_20d"


def test_factor_lab_results_api_upgrades_legacy_payload_with_readiness_and_user_view(monkeypatch, tmp_path):
    pd.DataFrame(
        [
            {"date": "2024-01-02", "stock_code": "600519", "stock_name": "贵州茅台", "score": 0.91, "daily_rank": 1},
            {"date": "2024-01-03", "stock_code": "600519", "stock_name": "贵州茅台", "score": 0.93, "daily_rank": 1},
        ]
    ).to_csv(tmp_path / "latest_scores.csv", index=False)

    legacy_payload = {
        "summary": {
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "pool": "core",
            "label": "next_5d_ret",
            "top_n": 3,
            "max_symbols": 1,
        },
        "factor_ranking": [{"factor": "mom_20d", "score": 0.5}],
        "feature_importance": [],
        "model_metrics": [],
        "bucket_returns": [],
        "stability": [],
        "backtest": None,
        "strategy_backtests": {
            "ml_factor_ranker": {
                "factor": "ml_factor_ranker",
                "with_cost": {
                    "total_return": 0.08,
                    "summary": {
                        "annual_return": 0.11,
                        "max_drawdown": -0.07,
                        "win_rate": 0.55,
                        "total_trades": 6,
                    },
                },
                "without_cost": {
                    "total_return": 0.10,
                    "summary": {
                        "annual_return": 0.13,
                        "max_drawdown": -0.06,
                        "win_rate": 0.57,
                        "total_trades": 6,
                    },
                },
                "cost_drag": {
                    "total_return_diff": 0.02,
                    "annual_return_diff": 0.02,
                    "cost_pct_initial": 0.01,
                },
            },
            "ml_factor_filter": {
                "factor": "ml_factor_filter",
                "with_cost": {
                    "total_return": 0.07,
                    "summary": {
                        "annual_return": 0.10,
                        "max_drawdown": -0.05,
                        "win_rate": 0.6,
                        "total_trades": 4,
                    },
                },
                "without_cost": {
                    "total_return": 0.09,
                    "summary": {
                        "annual_return": 0.12,
                        "max_drawdown": -0.04,
                        "win_rate": 0.62,
                        "total_trades": 4,
                    },
                },
                "cost_drag": {
                    "total_return_diff": 0.02,
                    "annual_return_diff": 0.02,
                    "cost_pct_initial": 0.01,
                },
            },
        },
        "backtest_compare": {
            "factors": ["ml_factor_ranker", "ml_factor_filter"],
            "best_total_return_factor": "ml_factor_ranker",
        },
        "artifacts": {"report_dir": str(tmp_path)},
    }

    monkeypatch.setattr(main, "load_latest_result", lambda: legacy_payload)
    monkeypatch.setattr(main, "resolve_factor_lab_symbols", lambda pool, max_symbols, end_date=None, start_date=None: ["600519"])
    monkeypatch.setattr(main.data_manager, "get_cached_window", lambda symbol: ("2023-01-01", "2025-12-31"))

    resp = client.get("/api/factor-lab/results")

    assert resp.status_code == 200
    body = resp.json()
    assert body["run_readiness"]["needs_backfill"] is False
    assert body["strategy_backtests"]["ml_factor_ranker"]["user_view"]["name_cn"] == "排序策略"
    assert body["strategy_backtests"]["ml_factor_ranker"]["user_view"]["trigger_days"] == 2
    assert body["strategy_backtests"]["ml_factor_ranker"]["user_view"]["recent_signal_symbols"] == ["贵州茅台"]
    assert body["strategy_backtests"]["ml_factor_filter"]["user_view"]["last_signal_date"] == "2024-01-03"


def test_factor_lab_results_rebuilds_preview_with_top_ranks_and_stock_names(monkeypatch, tmp_path):
    pd.DataFrame(
        [
            {"date": "2026-04-24", "stock_code": "000001", "stock_name": "000001", "score": 0.91, "daily_rank": 1, "signal": 1, "is_oos_score": True},
            {"date": "2026-04-24", "stock_code": "000002", "stock_name": "000002", "score": 0.12, "daily_rank": 80, "signal": 0, "is_oos_score": True},
        ]
    ).to_csv(tmp_path / "latest_scores.csv", index=False)
    payload = {
        "summary": {
            "start_date": "2024-01-01",
            "end_date": "2026-04-24",
            "pool": "all",
            "label": "next_5d_ret",
            "top_n": 1,
            "max_symbols": 2,
            "score_source": "score",
        },
        "factor_ranking": [],
        "feature_importance": [],
        "model_metrics": [],
        "bucket_returns": [],
        "stability": [],
        "backtest": None,
        "strategy_backtests": {},
        "scores_preview": [
            {"date": "2026-04-24", "stock_code": "000002", "stock_name": "000002", "score": 0.12, "daily_rank": 80}
        ],
        "artifacts": {"report_dir": str(tmp_path)},
    }

    monkeypatch.setattr(main, "load_latest_result", lambda: payload)
    monkeypatch.setattr(main, "resolve_factor_lab_symbols", lambda pool, max_symbols, end_date=None, start_date=None: ["000001", "000002"])
    monkeypatch.setattr(main.data_manager, "get_cached_window", lambda symbol: ("2023-01-01", "2026-04-24"))
    monkeypatch.setattr(main.data_manager, "get_stock_name", lambda symbol: {"000001": "平安银行", "000002": "万科A"}.get(symbol, symbol))
    monkeypatch.setattr(main, "persist_factor_lab_result", lambda result, report_dir: None)

    resp = client.get("/api/factor-lab/results")

    assert resp.status_code == 200
    preview = resp.json()["scores_preview"]
    assert preview[0]["stock_code"] == "000001"
    assert preview[0]["stock_name"] == "平安银行"
    assert preview[0]["daily_rank"] == 1
    assert "轻量预筛" in resp.json()["summary"]["sample_source_note"]


def test_factor_lab_backtest_api_delegates_to_execute_backtest(monkeypatch):
    expected = {"total_return": 0.12, "summary": {"annual_return": 0.18, "initial_capital": 1000000, "final_value": 1120000, "max_drawdown": -0.08, "sharpe_ratio": 1.2}}
    captured = {}

    monkeypatch.setattr(main, "validate_factor_lab_backtest_artifacts", lambda req: None)
    monkeypatch.setattr(main, "load_factor_lab_artifact_symbols", lambda: ["600519", "000001"])

    def fake_execute(req, override_cost_model=None, allow_mock=True):
        captured["stocks"] = req.stocks
        captured["max_symbols"] = req.max_symbols
        return expected

    monkeypatch.setattr(main, "execute_backtest", fake_execute)

    resp = client.post(
        "/api/factor-lab/backtest",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": 1000000,
            "factor": "ml_factor_ranker",
            "pool": "core",
            "max_positions": 3,
            "weight_mode": "score",
            "stop_loss": -0.08,
            "circuit_breaker": -0.15,
        },
    )

    assert resp.status_code == 200
    assert resp.json()["total_return"] == expected["total_return"]
    assert captured["stocks"] == ["600519", "000001"]
    assert captured["max_symbols"] == 2


def test_factor_lab_backtest_rejects_missing_artifact_symbols(monkeypatch):
    monkeypatch.setattr(main, "validate_factor_lab_backtest_artifacts", lambda req: None)
    monkeypatch.setattr(main, "load_factor_lab_artifact_symbols", lambda: [])
    monkeypatch.setattr(main, "execute_backtest", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not execute")))

    resp = client.post(
        "/api/factor-lab/backtest",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": 1000000,
            "factor": "ml_factor_ranker",
            "pool": "core",
            "max_positions": 3,
            "weight_mode": "score",
        },
    )

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "FACTOR_LAB_BACKTEST_FAILED"
    assert "样本股票" in resp.json()["detail"]


def test_factor_lab_backtest_rejects_missing_manifest(monkeypatch):
    monkeypatch.setattr(main, "_load_factor_lab_manifest", lambda: {})
    monkeypatch.setattr(main, "execute_backtest", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not execute")))

    resp = client.post(
        "/api/factor-lab/backtest",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": 1000000,
            "factor": "ml_factor_ranker",
            "pool": "core",
            "max_positions": 3,
            "weight_mode": "score",
        },
    )

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "FACTOR_LAB_BACKTEST_FAILED"
    assert "manifest" in resp.json()["detail"]


def test_factor_lab_backtest_rejects_config_hash_mismatch(monkeypatch):
    monkeypatch.setattr(
        main,
        "_load_factor_lab_manifest",
        lambda: {
            "run_id": "old-run",
            "config_hash": "stale-config",
            "oos_start_date": "2024-01-01",
            "oos_end_date": "2024-12-31",
        },
    )
    monkeypatch.setattr(main, "execute_backtest", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not execute")))

    resp = client.post(
        "/api/factor-lab/backtest",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "initial_capital": 1000000,
            "factor": "ml_factor_ranker",
            "pool": "core",
            "max_positions": 3,
            "weight_mode": "score",
        },
    )

    assert resp.status_code == 409
    assert resp.json()["error_code"] == "FACTOR_LAB_BACKTEST_FAILED"
    assert "分数与回测请求不匹配" in resp.json()["detail"]


def test_factor_lab_backtest_allows_matching_config_with_partial_oos_score_window(monkeypatch):
    config = main.build_factor_lab_config(
        start_date="2024-01-01",
        end_date="2026-04-25",
        pool="all",
        label="next_5d_ret",
        top_n=10,
        max_symbols=180,
    )
    monkeypatch.setattr(
        main,
        "_load_factor_lab_manifest",
        lambda: {
            "run_id": "current-run",
            "config_hash": _config_hash(config),
            "oos_start_date": "2024-10-11",
            "oos_end_date": "2026-04-17",
        },
    )
    expected = {"total_return": 0.12, "summary": {"annual_return": 0.18}}
    monkeypatch.setattr(main, "load_factor_lab_artifact_symbols", lambda: ["600519", "000001"])
    monkeypatch.setattr(main, "execute_backtest", lambda req, override_cost_model=None, allow_mock=True: expected)

    resp = client.post(
        "/api/factor-lab/backtest",
        json={
            "start_date": "2024-01-01",
            "end_date": "2026-04-25",
            "initial_capital": 1000000,
            "factor": "ml_factor_ranker",
            "pool": "all",
            "label": "next_5d_ret",
            "top_n": 10,
            "max_symbols": 180,
            "max_positions": 10,
            "weight_mode": "score",
        },
    )

    assert resp.status_code == 200
    assert resp.json()["total_return"] == expected["total_return"]


def test_factor_lab_run_api_builds_result_and_cost_comparison(monkeypatch):
    sample_df = pd.DataFrame(
        [
            {
                "date": "2024-01-02",
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000,
                "amount": 100500.0,
                "pct_chg": 0.5,
                "pe": 20.0,
                "pb": 5.0,
            }
        ]
    )

    monkeypatch.setattr(
        main.data_manager,
        "get_stock_pool_data",
        lambda symbols, start, end, allow_mock=True: (sample_df.copy(), {symbols[0]: "CACHE"}),
    )
    monkeypatch.setattr(
        main,
        "run_factor_lab",
        lambda df, config, write_latest_summary=True: {
            "summary": {"pool": config.pool, "label": config.label, "top_n": config.top_n},
            "factor_ranking": [{"factor": "mom_20d", "score": 0.5}],
            "feature_importance": [{"feature": "mom_20d", "importance": 0.3}],
            "model_metrics": [{"key": "test_rank_ic", "label": "测试 RankIC", "value": 0.08, "format": "ratio"}],
            "bucket_returns": [{"bucket": "Q1", "return": -0.01}, {"bucket": "Q5", "return": 0.03}],
            "stability": [{"key": "coverage", "label": "覆盖率", "value": 0.9, "format": "percent"}],
            "artifacts": {"report_dir": "/tmp/factor-lab-test"},
        },
    )

    call_counter = {"count": 0}
    backtest_requests = []

    monkeypatch.setattr(main.data_manager, "get_cached_window", lambda symbol: ("2023-01-01", "2025-12-31"))
    monkeypatch.setattr(main, "snapshot_factor_lab_artifacts", lambda report_dir=main.FACTOR_LAB_REPORT_DIR: None)
    monkeypatch.setattr(main, "restore_factor_lab_artifacts", lambda snapshot: None)
    monkeypatch.setattr(main, "clear_factor_lab_artifact_snapshot", lambda snapshot: None)

    def fake_execute(req, override_cost_model=None, allow_mock=True):
        call_counter["count"] += 1
        backtest_requests.append(req)
        return {
            "total_return": 0.1 if override_cost_model is None else 0.13,
            "summary": {
                "annual_return": 0.12 if override_cost_model is None else 0.15,
                "cost_stats": {"cost_pct_initial": 0.01},
                "initial_capital": req.initial_capital,
                "final_value": 1100000,
                "max_drawdown": -0.09,
                "sharpe_ratio": 1.1,
                "total_trades": 12,
            },
            "resolved_pool": {"effective_pool": req.pool},
        }

    monkeypatch.setattr(main, "execute_backtest", fake_execute)
    monkeypatch.setattr(main, "persist_factor_lab_result", lambda result, report_dir: None)
    monkeypatch.setattr(
        main,
        "attach_factor_lab_user_views",
        lambda comparisons, market_df: {
            key: {**value, "user_view": {"name_cn": "排序策略" if key == "ml_factor_ranker" else "过滤策略", "trigger_days": 0}}
            for key, value in comparisons.items()
        },
    )

    resp = client.post(
        "/api/factor-lab/run",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "pool": "core",
            "label": "next_5d_ret",
            "top_n": 3,
            "max_symbols": 2,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"]["pool"] == "core"
    assert body["run_readiness"]["needs_backfill"] is False
    assert body["backtest"]["total_return"] == 0.1
    assert body["strategy_backtests"]["ml_factor_ranker"]["cost_drag"]["total_return_diff"] == 0.03
    assert body["strategy_backtests"]["ml_factor_filter"]["cost_drag"]["total_return_diff"] == 0.03
    assert body["strategy_backtests"]["ml_factor_ranker"]["user_view"]["name_cn"] == "排序策略"
    assert "trigger_days" in body["strategy_backtests"]["ml_factor_filter"]["user_view"]
    assert body["backtest_compare"]["best_total_return_factor"] == "ml_factor_ranker"
    assert body["factor_ranking"][0]["factor"] == "mom_20d"
    assert call_counter["count"] == 4
    assert all(request.stocks == backtest_requests[0].stocks for request in backtest_requests)
    assert len(backtest_requests[0].stocks) == 2


def test_factor_lab_readiness_reports_full_cache_hit(monkeypatch):
    monkeypatch.setattr(main, "resolve_factor_lab_symbols", lambda pool, max_symbols, end_date=None, start_date=None: ["000001", "000002"])
    monkeypatch.setattr(main.data_manager, "get_cached_window", lambda symbol: ("2023-01-01", "2025-12-31"))

    response = client.post(
        "/api/factor-lab/readiness",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "pool": "core",
            "label": "next_5d_ret",
            "top_n": 5,
            "max_symbols": 2,
        },
    )

    assert response.status_code == 200
    readiness = response.json()["run_readiness"]
    assert readiness["needs_backfill"] is False
    assert readiness["missing_start"] is None
    assert readiness["missing_end"] is None
    assert readiness["cache_window_start"] == "2023-01-01"
    assert readiness["cache_window_end"] == "2025-12-31"


def test_factor_lab_strategy_comparison_scopes_backtests_to_research_symbols(monkeypatch):
    calls = []

    def fake_execute(req, override_cost_model=None, allow_mock=True):
        calls.append(req)
        return {
            "total_return": 0.1 if override_cost_model is None else 0.12,
            "summary": {
                "annual_return": 0.14,
                "cost_stats": {"cost_pct_initial": 0.01},
            },
            "resolved_pool": {
                "requested_pool": req.pool,
                "symbols_count": len(req.stocks or []),
            },
        }

    monkeypatch.setattr(main, "execute_backtest", fake_execute)
    req = main.FactorLabRunRequest(
        start_date="2024-01-01",
        end_date="2024-12-31",
        pool="all",
        label="next_5d_ret",
        top_n=3,
        max_symbols=2,
    )

    result = main.run_factor_lab_strategy_comparison(
        req,
        ["ml_factor_ranker"],
        symbols=["000001", "000002"],
        allow_mock=False,
    )

    assert list(result.keys()) == ["ml_factor_ranker"]
    assert len(calls) == 2
    assert all(call.pool == "all" for call in calls)
    assert all(call.stocks == ["000001", "000002"] for call in calls)


def test_factor_lab_readiness_reports_precise_missing_history_window(monkeypatch):
    monkeypatch.setattr(main, "resolve_factor_lab_symbols", lambda pool, max_symbols, end_date=None, start_date=None: ["000001", "000002"])
    monkeypatch.setattr(main.data_manager, "get_cached_window", lambda symbol: ("2023-09-01", "2025-12-31"))

    response = client.post(
        "/api/factor-lab/readiness",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "pool": "core",
            "label": "next_5d_ret",
            "top_n": 5,
            "max_symbols": 2,
        },
    )

    assert response.status_code == 200
    readiness = response.json()["run_readiness"]
    assert readiness["needs_backfill"] is True
    assert readiness["missing_start"] == "2023-04-16"
    assert readiness["missing_end"] == "2023-08-31"
    assert readiness["warning_message"].startswith("当前本地缓存的公共覆盖区间为 2023-09-01 至 2025-12-31")


def test_factor_lab_results_persist_and_read_back_run_readiness_and_user_view(monkeypatch, tmp_path):
    sample_df = pd.DataFrame(
        [
            {
                "date": "2024-01-02",
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000,
                "amount": 100500.0,
                "pct_chg": 0.5,
                "pe": 20.0,
                "pb": 5.0,
            }
        ]
    )

    monkeypatch.setattr(main.data_manager, "get_stock_pool_data", lambda symbols, start, end, allow_mock=True: (sample_df.copy(), {symbols[0]: "CACHE"}))
    monkeypatch.setattr(main.data_manager, "get_cached_window", lambda symbol: ("2023-01-01", "2025-12-31"))
    monkeypatch.setattr(main, "snapshot_factor_lab_artifacts", lambda report_dir=main.FACTOR_LAB_REPORT_DIR: None)
    monkeypatch.setattr(main, "restore_factor_lab_artifacts", lambda snapshot: None)
    monkeypatch.setattr(main, "clear_factor_lab_artifact_snapshot", lambda snapshot: None)
    monkeypatch.setattr(
        main,
        "run_factor_lab",
        lambda df, config, write_latest_summary=True: {
            "summary": {"pool": config.pool, "label": config.label, "top_n": config.top_n},
            "factor_ranking": [{"factor": "mom_20d", "score": 0.5}],
            "feature_importance": [{"feature": "mom_20d", "importance": 0.3}],
            "model_metrics": [],
            "bucket_returns": [],
            "stability": [],
            "artifacts": {"report_dir": str(tmp_path)},
        },
    )
    monkeypatch.setattr(
        main,
        "execute_backtest",
        lambda req, override_cost_model=None, allow_mock=True: {
            "total_return": 0.08 if override_cost_model is None else 0.1,
            "summary": {
                "annual_return": 0.11,
                "initial_capital": req.initial_capital,
                "final_value": 1080000,
                "max_drawdown": -0.07,
                "sharpe_ratio": 1.0,
                "total_trades": 6,
                "win_rate": 0.55,
                "cost_stats": {"cost_pct_initial": 0.01},
            },
            "resolved_pool": {"effective_pool": req.pool},
        },
    )
    monkeypatch.setattr(
        main,
        "attach_factor_lab_user_views",
        lambda comparisons, market_df: {
            key: {
                **value,
                "user_view": {
                    "name_cn": "排序策略" if key == "ml_factor_ranker" else "过滤策略",
                    "cost_drag": value.get("cost_drag", {}),
                },
            }
            for key, value in comparisons.items()
        },
    )

    response = client.post(
        "/api/factor-lab/run",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "pool": "core",
            "label": "next_5d_ret",
            "top_n": 3,
            "max_symbols": 1,
        },
    )

    assert response.status_code == 200

    monkeypatch.setattr(main, "load_latest_result", lambda: pipeline_load_latest_result(output_dir=tmp_path))
    results_response = client.get("/api/factor-lab/results")
    payload = results_response.json()

    assert payload["run_readiness"]["needs_backfill"] is False
    assert payload["strategy_backtests"]["ml_factor_ranker"]["user_view"]["name_cn"] == "排序策略"
    assert payload["strategy_backtests"]["ml_factor_filter"]["user_view"]["cost_drag"]["total_return_diff"] == pytest.approx(0.02)


def test_factor_lab_run_returns_structured_error_without_mock_persistence(monkeypatch):
    persist_calls = {"count": 0}

    monkeypatch.setattr(main, "snapshot_factor_lab_artifacts", lambda report_dir=main.FACTOR_LAB_REPORT_DIR: None)
    monkeypatch.setattr(main, "restore_factor_lab_artifacts", lambda snapshot: None)
    monkeypatch.setattr(main, "clear_factor_lab_artifact_snapshot", lambda snapshot: None)
    monkeypatch.setattr(main.data_manager, "get_cached_window", lambda symbol: (None, None))
    monkeypatch.setattr(
        main.data_manager,
        "get_stock_pool_data",
        lambda symbols, start, end, allow_mock=True: (_ for _ in ()).throw(
            main.PoolDataFetchError({"600519": "AKShare 与 Baostock 都失败"}, start, end)
        ),
    )
    monkeypatch.setattr(main, "persist_factor_lab_result", lambda result, report_dir: persist_calls.__setitem__("count", persist_calls["count"] + 1))

    response = client.post(
        "/api/factor-lab/run",
        json={
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "pool": "core",
            "label": "next_5d_ret",
            "top_n": 3,
            "max_symbols": 1,
        },
    )

    assert response.status_code == 502
    assert response.json()["error_code"] == "FACTOR_LAB_UPSTREAM_FETCH_FAILED"
    assert response.json()["run_readiness"]["needs_backfill"] is True
    assert persist_calls["count"] == 0


def test_factor_lab_stress_test_api_returns_display_contract_and_updates_latest(monkeypatch):
    sample_df = pd.DataFrame(
        [
            {
                "date": "2026-01-02",
                "stock_code": "000001",
                "stock_name": "平安银行",
                "open": 10.0,
                "high": 10.3,
                "low": 9.8,
                "close": 10.1,
                "volume": 1000.0,
                "amount": 10100.0,
                "pct_chg": 1.0,
                "turnover_rate": 1.2,
            }
        ]
    )
    latest_payload = {
        "summary": {
            "start_date": "2024-01-01",
            "end_date": "2026-01-02",
            "pool": "core",
            "label": "next_5d_ret",
            "top_n": 3,
            "max_symbols": 3,
            "score_source": "walk_forward_composite_score",
            "walk_forward": {"coverage_ratio": 0.8},
        },
        "model_metrics": [{"key": "test_rank_ic", "value": 0.05}],
        "bucket_returns": [{"bucket": "Q1", "return": -0.01}, {"bucket": "Q5", "return": 0.03}],
        "strategy_backtests": {
            "ml_factor_ranker": {
                "factor": "ml_factor_ranker",
                "with_cost": {
                    "total_return": 0.08,
                    "summary": {
                        "annual_return": 0.10,
                        "max_drawdown": -0.07,
                        "cost_stats": {"cost_pct_initial": 0.01},
                    },
                },
                "without_cost": {"total_return": 0.10, "summary": {"annual_return": 0.12}},
                "cost_drag": {"total_return_diff": 0.02},
            }
        },
        "backtest_compare": {"best_total_return_factor": "ml_factor_ranker"},
        "factor_ranking": [{"factor": "mom_20d"}],
        "feature_importance": [],
        "artifacts": {"report_dir": "/tmp/factor-lab-stress-test"},
    }
    stress_payload = {
        "run_id": "stress_test",
        "generated_at": "2026-04-26T10:00:00",
        "config": {"anchor_date": "2026-01-02", "symbols": 3},
        "scenarios": [
            {
                "scenario": "bear",
                "name_cn": "熊市年",
                "factors": {
                    "ml_factor_ranker": {
                        "median_total_return": -0.05,
                        "p05_total_return": -0.18,
                        "prob_positive": 0.25,
                        "p95_max_drawdown_abs": 0.22,
                        "survival_rate": 0.9,
                    }
                },
                "sample_paths": [],
            }
        ],
    }
    persisted = {}

    monkeypatch.setattr(main, "resolve_factor_lab_symbols", lambda pool, max_symbols, end_date=None, start_date=None: ["000001", "000002", "000003"])
    monkeypatch.setattr(main.data_manager, "get_last_trading_day", lambda: "2026-01-02")
    monkeypatch.setattr(main, "load_factor_lab_artifact_symbols", lambda report_dir=main.FACTOR_LAB_REPORT_DIR: [])
    monkeypatch.setattr(
        main.data_manager,
        "get_stock_pool_data",
        lambda symbols, start, end, allow_mock=True: (sample_df.copy(), {symbol: "CACHE" for symbol in symbols}),
    )
    monkeypatch.setattr(main, "run_factor_lab_stress_pipeline", lambda df, config, report_dir: stress_payload.copy())
    monkeypatch.setattr(main, "load_latest_factor_lab_result", lambda: latest_payload.copy())
    monkeypatch.setattr(main, "persist_factor_lab_result", lambda result, report_dir: persisted.update(result=result, report_dir=report_dir))

    response = client.post(
        "/api/factor-lab/stress-test",
        json={
            "pool": "core",
            "max_symbols": 3,
            "top_n": 3,
            "factors": ["ml_factor_ranker"],
            "horizon_days": 20,
            "paths_per_scenario": 1,
            "scenarios": ["bear"],
            "lookback_days": 90,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["stress_test"]["scenarios"][0]["name_cn"] == "熊市年"
    assert payload["stress_test"]["data_sources_used"]["000001"] == "CACHE"
    assert payload["self_iteration"]["stress_gate"]["available"] is True
    assert persisted["result"]["stress_test"]["run_id"] == "stress_test"
    assert persisted["result"]["self_iteration"]["promotion_decision"]["status"] in {"shadow", "research_pass", "no_promotion"}


def test_factor_lab_stress_test_prefers_current_artifact_symbols(monkeypatch):
    sample_df = pd.DataFrame(
        [
            {
                "date": "2026-01-02",
                "stock_code": symbol,
                "stock_name": symbol,
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.2,
                "volume": 1000,
                "amount": 10200.0,
            }
            for symbol in ["000001", "000002", "000003"]
        ]
    )
    latest_payload = {
        "summary": {
            "start_date": "2024-01-01",
            "end_date": "2026-01-02",
            "pool": "all",
            "label": "next_5d_ret",
            "top_n": 3,
            "max_symbols": 500,
        },
        "artifacts": {"report_dir": "/tmp/factor-lab-stress-test"},
    }
    captured = {}

    monkeypatch.setattr(main, "load_latest_factor_lab_result", lambda: latest_payload.copy())
    monkeypatch.setattr(main, "load_factor_lab_artifact_symbols", lambda report_dir=main.FACTOR_LAB_REPORT_DIR: ["000001", "000002", "000003"])
    monkeypatch.setattr(main, "resolve_factor_lab_symbols", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should use artifact symbols")))
    monkeypatch.setattr(main.data_manager, "get_last_trading_day", lambda: "2026-01-02")

    def fake_stock_pool_data(symbols, start, end, allow_mock=True):
        captured["symbols"] = list(symbols)
        return sample_df.copy(), {symbol: "CACHE" for symbol in symbols}

    monkeypatch.setattr(
        main.data_manager,
        "get_stock_pool_data",
        fake_stock_pool_data,
    )
    monkeypatch.setattr(
        main,
        "run_factor_lab_stress_pipeline",
        lambda df, config, report_dir: {
            "run_id": "stress_test",
            "generated_at": "2026-04-26T10:00:00",
            "config": {"anchor_date": "2026-01-02", "symbols": 3},
            "scenarios": [],
        },
    )
    monkeypatch.setattr(main, "build_factor_lab_self_iteration", lambda latest, report_dir: {"stress_gate": {"available": True, "passed": True}})
    monkeypatch.setattr(main, "persist_factor_lab_result", lambda result, report_dir: None)

    response = client.post(
        "/api/factor-lab/stress-test",
        json={
            "pool": "all",
            "max_symbols": 500,
            "top_n": 3,
            "factors": ["ml_factor_ranker"],
            "horizon_days": 20,
            "paths_per_scenario": 1,
            "scenarios": ["bear"],
            "lookback_days": 90,
        },
    )

    assert response.status_code == 200
    assert captured["symbols"] == ["000001", "000002", "000003"]


def test_factor_lab_stress_test_rejects_oversized_budget():
    response = client.post(
        "/api/factor-lab/stress-test",
        json={
            "pool": "core",
            "max_symbols": 501,
            "top_n": 3,
            "horizon_days": 20,
            "paths_per_scenario": 1,
            "scenarios": ["bear"],
            "lookback_days": 90,
        },
    )

    assert response.status_code == 422
    assert "max_symbols" in str(response.json()["detail"])
