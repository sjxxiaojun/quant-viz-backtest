from datetime import datetime

from automation_store import AutomationStore
from scheduler_service import AutomationOrchestrator, LightweightScheduler


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

    snapshot = store.record_market_snapshot(
        [{"代码": "000001", "最新价": 11.2}],
        market_session="morning",
        source="unit",
        captured_at="2026-01-02T10:00:00",
    )

    latest_snapshot = store.latest_snapshot(include_rows=True)
    assert latest_snapshot["snapshot_id"] == snapshot["snapshot_id"]
    assert latest_snapshot["rows"][0]["代码"] == "000001"

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

    message = store.record_ai_work_message(
        work_id=work_id,
        work_type="factor_lab_iteration",
        trigger="unit",
        target_date="2026-01-02",
        action_type="run_factor_lab",
        status="executed",
        level="info",
        title="Factor Lab 研究 / 已执行",
        body="Factor Lab 研究已执行。",
        details={"action": "run_factor_lab"},
    )

    assert message["work_id"] == work_id
    assert store.list_ai_work_messages()[0]["body"] == "Factor Lab 研究已执行。"


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


def test_ai_managed_work_uses_local_fallback_when_external_ai_fails(tmp_path):
    store = AutomationStore(tmp_path / "automation.db")

    class FailingAI:
        def call_external_ai(self, _context):
            raise RuntimeError("timeout")

    orchestrator = AutomationOrchestrator(
        store=store,
        data_manager=object(),
        data_lake_service=object(),
        ai_service=FailingAI(),
        virtual_trade_runner=lambda: {"status": "success"},
        context_builder=lambda: {"data_freshness": {"target_date": "2026-01-02"}},
    )

    decision = orchestrator._call_managed_ai_with_fallback(
        "simulation_supervision",
        {"preferred_actions": [{"type": "generate_daily_report", "params": {"mode": "unit"}}]},
        {},
    )

    assert decision["actor"] == "local_guardrail"
    assert "外部 AI 调用失败" in decision["summary"]
    assert decision["actions"][0]["type"] == "generate_daily_report"


def test_ai_cycle_uses_local_fallback_when_external_ai_fails(tmp_path):
    store = AutomationStore(tmp_path / "automation.db")

    class FailingAI:
        def call_external_ai(self, _context):
            raise RuntimeError("timeout")

    class FakeDataLake:
        def default_target_date(self):
            return "2026-01-02"

    orchestrator = AutomationOrchestrator(
        store=store,
        data_manager=object(),
        data_lake_service=FakeDataLake(),
        ai_service=FailingAI(),
        virtual_trade_runner=lambda: {"status": "success"},
        context_builder=lambda: {"data_freshness": {"target_date": "2026-01-02"}},
    )

    decision = orchestrator._call_ai_cycle_with_fallback({"data_freshness": {"target_date": "2026-01-02"}})

    assert decision["actor"] == "local_guardrail"
    assert decision["source"] == "ai_cycle_fallback"
    assert decision["actions"][0]["params"]["target_date"] == "2026-01-02"


def test_market_snapshot_falls_back_to_eastmoney_when_akshare_unavailable(tmp_path, monkeypatch):
    store = AutomationStore(tmp_path / "automation.db")

    class FakeDataManager:
        def get_latest_market_overview(self, limit=10):
            return [{"代码": "fallback", "最新价": 1.0}][:limit]

    orchestrator = AutomationOrchestrator(
        store=store,
        data_manager=FakeDataManager(),
        data_lake_service=object(),
        ai_service=object(),
        virtual_trade_runner=lambda: {"status": "success"},
        context_builder=lambda: {},
    )

    monkeypatch.setattr(AutomationOrchestrator, "_try_akshare_frame", staticmethod(lambda _name: None))

    def fake_eastmoney_fetch(cls, *, asset_type, limit, **_kwargs):
        if asset_type == "a_share":
            return [{"代码": "000001", "名称": "平安银行", "最新价": 11.2, "涨跌幅": 1.1, "昨收": 11.0}]
        return [{"代码": "518880", "名称": "黄金ETF", "最新价": 9.8, "涨跌幅": 0.6, "昨收": 9.7}]

    monkeypatch.setattr(
        AutomationOrchestrator,
        "_fetch_eastmoney_clist_snapshot",
        classmethod(fake_eastmoney_fetch),
    )

    rows, source = orchestrator._fetch_market_snapshot(limit=6000)

    assert source == "eastmoney_a+eastmoney_etf"
    assert [row["代码"] for row in rows] == ["000001", "518880"]
