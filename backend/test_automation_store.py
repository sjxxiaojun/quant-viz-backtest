from datetime import datetime

from automation_store import AutomationStore
from scheduler_service import LightweightScheduler


def test_automation_store_records_runs_and_ai_decisions(tmp_path):
    store = AutomationStore(tmp_path / "automation.db")
    run_id = store.start_run("eod_update", "test", "2026-01-02")
    finished = store.finish_run(run_id, "success", summary={"ok": True})

    runs = store.list_runs()

    assert finished["run_id"] == run_id
    assert finished["summary"] == {"ok": True}
    assert runs[0]["job_type"] == "eod_update"
    assert store.latest_success("eod_update")["run_id"] == run_id

    decision = store.record_ai_decision(
        actor="tester",
        source="unit",
        status="executed",
        summary="run virtual trade",
        actions=[{"type": "run_virtual_trade"}],
        result={"actions": [{"status": "executed"}]},
    )

    assert decision["status"] == "executed"
    assert store.list_ai_decisions()[0]["actions"][0]["type"] == "run_virtual_trade"

    work_id = store.start_ai_work("factor_lab_iteration", "unit", target_date="2026-01-02", title="AI 因子实验托管")
    work_log = store.finish_ai_work(
        work_id,
        "success",
        summary="完成因子实验巡检。",
        work_items=[{"action": "run_factor_lab", "status": "executed"}],
        actions=[{"type": "run_factor_lab"}],
        result={"ok": True},
    )

    assert work_log["summary"] == "完成因子实验巡检。"
    assert store.list_ai_work_logs()[0]["work_items"][0]["action"] == "run_factor_lab"


def test_scheduler_runs_due_trade_day_tasks_once():
    class FakeStore:
        def __init__(self):
            self.state = {}

        def get_state(self, key, fallback=None):
            return self.state.get(key, fallback)

        def set_state(self, key, value):
            self.state[key] = value

    class FakeDataLake:
        def is_trade_day(self, _now):
            return True

    class FakeOrchestrator:
        def __init__(self):
            self.store = FakeStore()
            self.data_lake_service = FakeDataLake()
            self.calls = []

        def run_realtime_snapshot(self, trigger):
            self.calls.append(("snapshot", trigger))
            return {"status": "success"}

        def run_eod_chain(self, trigger, retry_run=False):
            self.calls.append(("eod", trigger, retry_run))
            return {"status": "success"}

        def run_ai_cycle(self, trigger):
            self.calls.append(("ai", trigger))
            return {"status": "success"}

        def run_ai_managed_work(self, work_type, trigger):
            self.calls.append(("ai_work", work_type, trigger))
            return {"status": "success"}

    fake = FakeOrchestrator()
    scheduler = LightweightScheduler(fake, poll_seconds=5)

    scheduler._tick(datetime(2026, 1, 2, 9, 36))
    scheduler._tick(datetime(2026, 1, 2, 9, 37))

    assert fake.calls == [
        ("snapshot", "scheduler"),
        ("ai_work", "premarket_plan", "scheduler"),
    ]
