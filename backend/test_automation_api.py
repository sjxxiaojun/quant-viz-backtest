from fastapi.testclient import TestClient

import main
from ai_automation import AIAutomationService
from automation_store import AutomationStore


client = TestClient(main.app)


def test_automation_status_endpoint_uses_orchestrator(monkeypatch):
    monkeypatch.setattr(
        main.automation_orchestrator,
        "status_payload",
        lambda scheduler: {
            "scheduler": {"enabled": True, "running": False},
            "data_freshness": {"status": "ready", "score": 100.0},
            "recent_runs": [],
        },
    )

    response = client.get("/api/automation/status")

    assert response.status_code == 200
    assert response.json()["data_freshness"]["status"] == "ready"


def test_manual_eod_update_endpoint_passes_dry_run_request(monkeypatch):
    captured = {}

    def fake_run_eod_update(**kwargs):
        captured.update(kwargs)
        return {"run_id": "run-1", "status": "success", "summary": {"dry_run": kwargs["dry_run"]}}

    monkeypatch.setattr(main.automation_orchestrator, "run_eod_update", fake_run_eod_update)

    response = client.post(
        "/api/automation/jobs/eod-update",
        json={"target_date": "2026-01-02", "dry_run": True, "limit_a_share": 1, "limit_etf": 1},
    )

    assert response.status_code == 200
    assert response.json()["summary"]["dry_run"] is True
    assert captured["target_date"] == "2026-01-02"
    assert captured["limit_a_share"] == 1


def test_ai_decision_rejects_forbidden_action(tmp_path, monkeypatch):
    store = AutomationStore(tmp_path / "automation.db")
    monkeypatch.setattr(main, "ai_automation_service", AIAutomationService(store))

    response = client.post(
        "/api/ai/decisions",
        json={
            "actor": "test-ai",
            "source": "unit",
            "summary": "try forbidden order",
            "actions": [{"type": "real_trade", "params": {"symbol": "000001"}}],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"]["status"] == "rejected"
    assert payload["action_results"][0]["reason"] == "action_not_allowed"
    assert store.list_ai_decisions()[0]["status"] == "rejected"


def test_ai_managed_work_endpoint_passes_work_type(monkeypatch):
    captured = {}

    def fake_run_ai_managed_work(**kwargs):
        captured.update(kwargs)
        return {
            "run_id": "ai-managed-1",
            "status": "dry_run",
            "summary": {"work_type": kwargs["work_type"]},
        }

    monkeypatch.setattr(main.automation_orchestrator, "run_ai_managed_work", fake_run_ai_managed_work)

    response = client.post(
        "/api/automation/jobs/ai-managed-work",
        json={"work_type": "factor_lab_iteration", "dry_run": True},
    )

    assert response.status_code == 200
    assert response.json()["summary"]["work_type"] == "factor_lab_iteration"
    assert captured["dry_run"] is True


def test_ai_work_logs_endpoint_reads_store(tmp_path, monkeypatch):
    store = AutomationStore(tmp_path / "automation.db")
    work_id = store.start_ai_work("simulation_supervision", "unit", title="AI 模拟盘托管")
    store.finish_ai_work(work_id, "success", summary="已追赶模拟盘。")
    monkeypatch.setattr(main, "automation_store", store)

    response = client.get("/api/ai/work-logs")

    assert response.status_code == 200
    assert response.json()[0]["work_type"] == "simulation_supervision"
    assert response.json()[0]["summary"] == "已追赶模拟盘。"


def test_ai_work_messages_endpoint_reads_store(tmp_path, monkeypatch):
    store = AutomationStore(tmp_path / "automation.db")
    store.record_ai_work_message(
        work_id="aiwork-unit",
        work_type="simulation_supervision",
        trigger="unit",
        action_type="run_virtual_trade",
        status="executed",
        title="追赶模拟盘 / 已执行",
        body="追赶模拟盘已执行。",
    )
    monkeypatch.setattr(main, "automation_store", store)

    response = client.get("/api/ai/work-messages")

    assert response.status_code == 200
    assert response.json()[0]["work_type"] == "simulation_supervision"
    assert response.json()[0]["body"] == "追赶模拟盘已执行。"


def test_ai_decision_callback_receives_each_action_result(tmp_path):
    store = AutomationStore(tmp_path / "automation.db")
    service = AIAutomationService(store)
    seen = []

    result = service.execute_decision(
        {
            "actor": "unit-ai",
            "source": "unit",
            "summary": "plan report",
            "actions": [{"type": "generate_daily_report", "params": {"mode": "unit"}}],
        },
        handlers={},
        dry_run=True,
        on_action_result=seen.append,
    )

    assert result["decision"]["status"] == "dry_run"
    assert seen[0]["type"] == "generate_daily_report"
    assert seen[0]["status"] == "planned"


def test_ai_compatible_response_parser_handles_thinking_text(tmp_path):
    service = AIAutomationService(AutomationStore(tmp_path / "automation.db"))

    parsed = service._parse_decision_text(
        '<think>reviewing state</think>\n'
        '{"summary":"ok","confidence":0.8,"actions":[{"type":"generate_daily_report"}]}'
    )

    assert parsed["summary"] == "ok"
    assert parsed["actions"][0]["type"] == "generate_daily_report"
