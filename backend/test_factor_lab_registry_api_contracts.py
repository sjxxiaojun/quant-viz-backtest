import pytest
from fastapi.testclient import TestClient

import main
from strategy_registry import STRATEGY_REGISTRY, get_strategy_spec


client = TestClient(main.app)


def test_all_strategy_specs_expose_behavior_contract():
    for key, spec in STRATEGY_REGISTRY.items():
        as_dict = spec.as_dict()
        assert as_dict["key"] == key
        assert as_dict["name"]
        assert as_dict["pool"] in {"core", "etf", "blackhorse", "power_energy"}
        assert as_dict["signal_type"] in {"stateful", "ranking", "event"}
        assert as_dict["holding_policy"]
        assert as_dict["execution_mode"]
        assert isinstance(as_dict["requires_artifact"], bool)


def test_overnight_strategies_keep_event_execution_metadata():
    for key in ("overnight", "overnight_quality", "overnight_balanced", "overnight_ranked"):
        spec = get_strategy_spec(key)
        assert spec is not None
        assert spec.signal_type == "event"
        assert spec.holding_policy == "timeout_exit"
        assert spec.default_max_hold_days == 1
        assert spec.execution_mode == "signal_close_to_next_open"


def test_strategies_api_returns_registry_behavior_fields():
    response = client.get("/api/strategies")

    assert response.status_code == 200
    payload = response.json()

    for key in ("overnight_balanced", "ai_ml", "ai_ml_pro_plus", "ml_factor_ranker", "ml_factor_filter"):
        assert key in payload

    overnight_balanced = payload["overnight_balanced"]
    assert overnight_balanced["asset_class"] == "a_share"
    assert overnight_balanced["signal_type"] == "event"
    assert overnight_balanced["holding_policy"] == "timeout_exit"
    assert overnight_balanced["default_max_hold_days"] == 1
    assert overnight_balanced["execution_mode"] == "signal_close_to_next_open"
    assert payload["ml_factor_ranker"]["category"] == "Factor Lab"
    assert payload["ml_factor_ranker"]["signal_type"] == "ranking"
    assert payload["ml_factor_ranker"]["requires_artifact"] is True
    assert "artifact_status" in payload["ml_factor_ranker"]


def test_factor_lab_results_api_contract(monkeypatch):
    monkeypatch.setattr(
        main,
        "load_latest_result",
        lambda: {
            "summary": {"status": "ready", "label": "next_5d_ret"},
            "run_readiness": {"needs_backfill": False, "checked_symbols": ["600519"]},
            "factor_ranking": [{"factor": "mom_20d", "ic_mean": 0.11, "rank_ic_mean": 0.22}],
            "strategy_backtests": {
                "ml_factor_ranker": {
                    "user_view": {"name_cn": "排序策略", "trigger_days": 12},
                }
            },
            "artifacts": {"report_dir": "/tmp/factor-lab"},
        },
    )

    response = client.get("/api/factor-lab/results")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["status"] == "ready"
    assert payload["summary"]["label"] == "next_5d_ret"
    assert payload["run_readiness"]["needs_backfill"] is False
    assert payload["strategy_backtests"]["ml_factor_ranker"]["user_view"]["name_cn"] == "排序策略"
    assert payload["artifacts"]["report_dir"] == "/tmp/factor-lab"
    assert payload["factor_ranking"][0]["factor"] == "mom_20d"


def test_factor_lab_factors_api_contract(monkeypatch):
    monkeypatch.setattr(
        main,
        "load_latest_result",
        lambda: {
            "summary": {"status": "ready", "label": "next_5d_ret"},
            "factor_ranking": [
                {"factor": "mom_20d", "ic_mean": 0.11, "rank_ic_mean": 0.22},
                {"factor": "volatility_20d", "ic_mean": -0.04, "rank_ic_mean": -0.01},
            ],
        },
    )

    response = client.get("/api/factor-lab/factors")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["status"] == "ready"
    assert isinstance(payload["factor_ranking"], list)
    assert payload["factor_ranking"][0]["factor"] == "mom_20d"
    assert {"factor", "ic_mean", "rank_ic_mean"}.issubset(payload["factor_ranking"][0])


def test_factor_lab_backtest_rejects_unknown_factor_before_data_fetch():
    response = client.post(
        "/api/factor-lab/backtest",
        json={
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "initial_capital": 1000000,
            "factor": "not_supported",
            "pool": "core",
        },
    )

    assert response.status_code == 400
    assert "仅支持 ml_factor_ranker 或 ml_factor_filter" in response.json()["detail"]
