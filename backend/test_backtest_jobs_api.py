import time

import pytest
from fastapi.testclient import TestClient

import main


client = TestClient(main.app)

@pytest.fixture(autouse=True)
def deterministic_queue(monkeypatch):
    # API contract tests inject a synchronous executor; process isolation is tested separately.
    def submit(kind, payload):
        job_id = main.job_store.create(kind, payload)
        main.job_store.update(job_id, status="running")
        if kind == "backtest":
            value = main.execute_backtest(main.BacktestRequest(**payload))
        else:
            value = main.execute_compare_request(main.CompareRequest(**payload))
        main.job_store.update(job_id, status="succeeded", result=value)
        return job_id
    monkeypatch.setattr(main.job_queue, "submit", submit)



def _min_req():
    return {
        "start_date": "2026-01-01",
        "end_date": "2026-01-10",
        "initial_capital": 1000000,
        "factor": "bottom_fishing",
        "pool": "auto",
        "max_positions": 5,
        "weight_mode": "equal",
        "stop_loss": -0.08,
        "circuit_breaker": -0.15,
        "commission_rate": 0.0003,
        "stamp_tax_rate": 0.001,
        "slippage_rate": 0.0003,
        "commission_min": 5.0,
        "allow_mock": True,
    }


def test_backtest_jobs_submit_then_status_then_result(monkeypatch):
    def fake_execute(req, *args, **kwargs):
        return {"history": [], "trades": [], "summary": {"initial_capital": 1, "final_value": 1, "max_drawdown": 0, "sharpe_ratio": 0}, "total_return": 0}

    monkeypatch.setattr(main, "execute_backtest", fake_execute)

    resp = client.post("/api/backtest/jobs", json=_min_req())
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    assert isinstance(job_id, str) and job_id

    # Poll status briefly until succeeded.
    status = None
    for _ in range(50):
        r = client.get(f"/api/backtest/jobs/{job_id}")
        assert r.status_code == 200
        status = r.json()["status"]
        if status == "succeeded":
            break
        time.sleep(0.01)

    assert status == "succeeded"

    result = client.get(f"/api/backtest/jobs/{job_id}/result")
    assert result.status_code == 200
    payload = result.json()
    assert "history" in payload and "trades" in payload and "summary" in payload


def test_backtest_api_accepts_legacy_circuit_breaker_without_circuit_trade(monkeypatch):
    def fake_execute(req, *args, **kwargs):
        return {
            "history": [],
            "trades": [{"date": "2026-01-02", "stock_code": "000001", "stock_name": "平安银行", "side": "sell", "price": 10.0, "qty": 100}],
            "summary": {"initial_capital": 1, "final_value": 1, "max_drawdown": 0, "sharpe_ratio": 0},
            "total_return": 0,
            "strategy_behavior": {
                "portfolio_circuit_breaker_active": False,
                "deprecated_circuit_breaker_requested": req.circuit_breaker,
            },
        }

    monkeypatch.setattr(main, "execute_backtest", fake_execute)

    resp = client.post("/api/backtest", json=_min_req())

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["strategy_behavior"]["portfolio_circuit_breaker_active"] is False
    assert payload["strategy_behavior"]["deprecated_circuit_breaker_requested"] == -0.15
    assert all(trade["side"] != "circuit_break" for trade in payload["trades"])


def test_backtest_job_status_404_when_missing():
    resp = client.get("/api/backtest/jobs/does-not-exist")
    assert resp.status_code == 404


def test_backtest_job_result_returns_425_when_running(monkeypatch):
    monkeypatch.setattr(main.job_queue, "submit", lambda kind, payload: main.job_store.create(kind, payload))

    resp = client.post("/api/backtest/jobs", json=_min_req())
    job_id = resp.json()["job_id"]

    result = client.get(f"/api/backtest/jobs/{job_id}/result")
    assert result.status_code == 425


def test_compare_jobs_submit_then_status_then_result(monkeypatch):
    def fake_compare(req):
        return {"atm": {"history": [], "trades": [], "summary": {"initial_capital": 1, "final_value": 1, "max_drawdown": 0, "sharpe_ratio": 0}, "total_return": 0}}

    monkeypatch.setattr(main, "execute_compare_request", fake_compare)

    payload = _min_req()
    payload.pop("factor")
    payload["strategies"] = ["atm", "reversal"]

    resp = client.post("/api/backtest/compare/jobs", json=payload)
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    status = None
    for _ in range(50):
        r = client.get(f"/api/backtest/compare/jobs/{job_id}")
        assert r.status_code == 200
        status = r.json()["status"]
        if status == "succeeded":
            break
        time.sleep(0.01)

    assert status == "succeeded"

    result = client.get(f"/api/backtest/compare/jobs/{job_id}/result")
    assert result.status_code == 200
    body = result.json()
    assert "atm" in body
