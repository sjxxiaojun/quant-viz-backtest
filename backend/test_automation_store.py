from datetime import datetime, timedelta

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


def test_store_expires_stale_running_tasks(tmp_path):
    store = AutomationStore(tmp_path / "automation.db")
    run_id = store.start_run("eod_update", "unit", "2026-01-02")
    work_id = store.start_ai_work("factor_lab_iteration", "unit", target_date="2026-01-02", title="AI 因子实验托管")
    stale_at = (datetime.now() - timedelta(minutes=130)).isoformat(timespec="seconds")

    with store._connect() as conn:
        conn.execute("UPDATE automation_runs SET started_at = ? WHERE run_id = ?", (stale_at, run_id))
        conn.execute("UPDATE ai_work_logs SET started_at = ? WHERE work_id = ?", (stale_at, work_id))
        conn.commit()

    expired_runs = store.expire_stale_runs(max_age_minutes=120)
    expired_work = store.expire_stale_ai_work_logs(max_age_minutes=120)

    assert expired_runs[0]["run_id"] == run_id
    assert expired_runs[0]["status"] == "failed"
    assert expired_runs[0]["summary"]["timeout"] is True
    assert expired_work[0]["work_id"] == work_id
    assert expired_work[0]["status"] == "failed"
    assert expired_work[0]["result"]["timeout"] is True


def test_store_uses_job_specific_stale_timeouts(tmp_path):
    store = AutomationStore(tmp_path / "automation.db")
    ai_run_id = store.start_run("ai_cycle", "unit", "2026-01-02")
    eod_run_id = store.start_run("eod_update", "unit", "2026-01-02")
    stale_at = (datetime.now() - timedelta(minutes=20)).isoformat(timespec="seconds")

    with store._connect() as conn:
        conn.execute("UPDATE automation_runs SET started_at = ? WHERE run_id IN (?, ?)", (stale_at, ai_run_id, eod_run_id))
        conn.commit()

    expired = store.expire_stale_runs(max_age_minutes=120, job_timeouts={"ai_cycle": 15, "eod_update": 240})

    assert [run["run_id"] for run in expired] == [ai_run_id]
    assert store.list_runs(job_type="eod_update")[0]["status"] == "running"


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


def test_eod_update_messages_and_dry_run_state_boundary(tmp_path):
    store = AutomationStore(tmp_path / "automation.db")

    class FakeDataLake:
        def default_target_date(self):
            return "2026-01-02"

        def run_update(self, **kwargs):
            return {
                "target_date": kwargs["target_date"],
                "dry_run": kwargs["dry_run"],
                "a_share": {"scheduled_updates": 2},
                "etf": {"scheduled_updates": 1},
            }

    orchestrator = AutomationOrchestrator(
        store=store,
        data_manager=object(),
        data_lake_service=FakeDataLake(),
        ai_service=object(),
        virtual_trade_runner=lambda: {"status": "success"},
        context_builder=lambda: {},
    )

    dry_run = orchestrator.run_eod_update(trigger="unit", dry_run=True)

    assert dry_run["status"] == "success"
    assert store.get_state("last_eod_update") is None
    messages = store.list_ai_work_messages(work_type="eod_update")
    assert messages[0]["title"] == "数据湖补数演练完成"
    assert messages[1]["title"] == "数据湖补数演练开始"

    real_run = orchestrator.run_eod_update(trigger="unit", dry_run=False)

    assert real_run["status"] == "success"
    assert store.get_state("last_eod_update")["run_id"] == real_run["run_id"]
    assert store.list_ai_work_messages(work_type="eod_update")[0]["title"] == "数据湖补数完成"


def test_eod_update_skips_when_another_update_is_running(tmp_path):
    store = AutomationStore(tmp_path / "automation.db")
    active_run_id = store.start_run("eod_update", "unit", "2026-01-02")

    class FakeDataLake:
        def default_target_date(self):
            return "2026-01-02"

        def run_update(self, **_kwargs):
            raise AssertionError("concurrent update should not start")

    orchestrator = AutomationOrchestrator(
        store=store,
        data_manager=object(),
        data_lake_service=FakeDataLake(),
        ai_service=object(),
        virtual_trade_runner=lambda: {"status": "success"},
        context_builder=lambda: {},
    )

    result = orchestrator.run_eod_update(trigger="unit", dry_run=False)

    assert result["status"] == "skipped"
    assert result["summary"]["active_run_id"] == active_run_id
    assert store.list_ai_work_messages(work_type="eod_update")[0]["title"] == "数据湖补数已跳过"


def test_eod_progress_message_body_reports_sample_counts():
    body = AutomationOrchestrator._eod_progress_message_body(
        {
            "target_date": "2026-01-02",
            "score": 42.5,
            "a_share": {"fresh_count": 20, "checked_count": 50},
            "etf": {"fresh_count": 5, "checked_count": 20},
        }
    )

    assert "2026-01-02 数据湖补数仍在运行" in body
    assert "A股样本 20/50" in body
    assert "ETF样本 5/20" in body


def test_status_payload_marks_stale_runs_failed_and_messages(tmp_path):
    store = AutomationStore(tmp_path / "automation.db")
    run_id = store.start_run("ai_cycle", "unit", "2026-01-02")
    stale_at = (datetime.now() - timedelta(minutes=130)).isoformat(timespec="seconds")
    with store._connect() as conn:
        conn.execute("UPDATE automation_runs SET started_at = ? WHERE run_id = ?", (stale_at, run_id))
        conn.commit()

    class FakeDataLake:
        def data_freshness(self, max_scan=300):
            return {"status": "ready", "score": 100.0, "max_scan": max_scan}

    orchestrator = AutomationOrchestrator(
        store=store,
        data_manager=object(),
        data_lake_service=FakeDataLake(),
        ai_service=object(),
        virtual_trade_runner=lambda: {"status": "success"},
        context_builder=lambda: {},
    )

    payload = orchestrator.status_payload()

    assert payload["recent_runs"][0]["run_id"] == run_id
    assert payload["recent_runs"][0]["status"] == "failed"
    assert store.list_ai_work_messages()[0]["title"] == "自动化任务超时"


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


def test_market_snapshot_supplements_missing_position_quotes(tmp_path, monkeypatch):
    store = AutomationStore(tmp_path / "automation.db")

    class FakeDataManager:
        def get_latest_market_overview(self, limit=10):
            return []

    orchestrator = AutomationOrchestrator(
        store=store,
        data_manager=FakeDataManager(),
        data_lake_service=object(),
        ai_service=object(),
        virtual_trade_runner=lambda: {"status": "success"},
        context_builder=lambda: {
            "virtual_trading": {
                "accounts": [
                    {"top_holding_details": [{"symbol": "000001"}, {"symbol": "518880"}]},
                ]
            }
        },
    )

    monkeypatch.setattr(AutomationOrchestrator, "_try_akshare_frame", staticmethod(lambda _name: None))
    monkeypatch.setattr(
        AutomationOrchestrator,
        "_fetch_eastmoney_clist_snapshot",
        classmethod(lambda cls, **_kwargs: []),
    )
    monkeypatch.setattr(
        AutomationOrchestrator,
        "_fetch_eastmoney_position_quotes",
        classmethod(
            lambda cls, symbols: [
                {"代码": symbol, "名称": symbol, "最新价": 10.0, "涨跌幅": 0.5, "昨收": 9.9}
                for symbol in symbols
            ]
        ),
    )

    rows, source = orchestrator._fetch_market_snapshot(limit=6000)

    assert source == "eastmoney_positions"
    assert [row["代码"] for row in rows] == ["000001", "518880"]
