from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from ai_automation import AIAutomationService
from automation_store import AutomationStore
from data_lake_update_service import DataLakeUpdateService
from data_manager import DataManager


logger = logging.getLogger("AutomationScheduler")


VirtualTradeRunner = Callable[[], Dict[str, Any]]
ContextBuilder = Callable[[], Dict[str, Any]]


INTRADAY_SNAPSHOT_TIMES = ["09:35", "10:30", "11:30", "13:30", "14:55"]
EOD_UPDATE_TIMES = ["16:30", "18:00"]
AI_CYCLE_TIMES = ["18:10"]
AI_MANAGED_WORK_SCHEDULES: Dict[str, List[str]] = {
    "premarket_plan": ["08:55"],
    "intraday_review": ["09:45", "10:45", "13:45", "14:58"],
    "simulation_supervision": ["15:20"],
    "factor_lab_iteration": ["18:25"],
    "eod_report": ["19:20"],
}

MANAGED_WORK_PROFILES: Dict[str, Dict[str, Any]] = {
    "premarket_plan": {
        "title": "AI 盘前计划",
        "objective": "基于昨收数据、模拟盘持仓和策略状态生成当日观察重点，不做真实交易。",
        "preferred_actions": [
            {"type": "check_data_integrity", "params": {"max_scan": 300}},
            {"type": "generate_daily_report", "params": {"mode": "premarket_plan"}},
        ],
        "required_actions": ["check_data_integrity", "generate_daily_report"],
    },
    "intraday_review": {
        "title": "AI 盘中巡检",
        "objective": "抓取盘中快照并识别异常，只记录观察和提示，不写入历史 K 线。",
        "preferred_actions": [
            {"type": "realtime_snapshot", "params": {"limit": 200}},
            {"type": "check_data_integrity", "params": {"max_scan": 300}},
            {"type": "generate_daily_report", "params": {"mode": "intraday_review"}},
        ],
        "required_actions": ["realtime_snapshot", "generate_daily_report"],
    },
    "simulation_supervision": {
        "title": "AI 模拟盘托管",
        "objective": "在数据就绪后追赶模拟盘，检查账户、持仓、流水和风险，不触碰真实券商交易。",
        "preferred_actions": [
            {"type": "run_virtual_trade", "params": {}},
            {"type": "generate_daily_report", "params": {"mode": "simulation_supervision"}},
        ],
        "required_actions": ["run_virtual_trade", "generate_daily_report"],
    },
    "factor_lab_iteration": {
        "title": "AI 因子实验托管",
        "objective": "照料 Factor Lab 的策略优化、研究回测、压力测试和候选版本观察，正式版本切换仍走现有门禁。",
        "preferred_actions": [
            {"type": "check_data_integrity", "params": {"max_scan": 300}},
            {"type": "run_factor_lab", "params": {}},
            {"type": "run_factor_lab_backtest", "params": {}},
            {"type": "run_factor_lab_stress_test", "params": {}},
            {"type": "generate_daily_report", "params": {"mode": "factor_lab_iteration"}},
        ],
        "required_actions": [
            "check_data_integrity",
            "run_factor_lab",
            "run_factor_lab_backtest",
            "run_factor_lab_stress_test",
            "generate_daily_report",
        ],
    },
    "eod_report": {
        "title": "AI 收盘复盘",
        "objective": "汇总数据湖、模拟盘、Factor Lab 和策略版本状态，形成收盘工作记录。",
        "preferred_actions": [
            {"type": "check_data_integrity", "params": {"max_scan": 300}},
            {"type": "generate_daily_report", "params": {"mode": "eod_report"}},
        ],
        "required_actions": ["check_data_integrity", "generate_daily_report"],
    },
}


class AutomationOrchestrator:
    def __init__(
        self,
        *,
        store: AutomationStore,
        data_manager: DataManager,
        data_lake_service: DataLakeUpdateService,
        ai_service: AIAutomationService,
        virtual_trade_runner: VirtualTradeRunner,
        context_builder: ContextBuilder,
    ):
        self.store = store
        self.data_manager = data_manager
        self.data_lake_service = data_lake_service
        self.ai_service = ai_service
        self.virtual_trade_runner = virtual_trade_runner
        self.context_builder = context_builder
        self.ai_handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}

    def set_ai_handlers(self, handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]) -> None:
        self.ai_handlers = handlers

    def run_realtime_snapshot(self, *, trigger: str = "manual", limit: int = 200) -> Dict[str, Any]:
        run_id = self.store.start_run("realtime_snapshot", trigger)
        try:
            rows, source = self._fetch_market_snapshot(limit=limit)
            snapshot = self.store.record_market_snapshot(
                rows,
                market_session=self._market_session(datetime.now()),
                source=source,
            )
            summary = {"snapshot": snapshot, "row_count": len(rows), "source": source}
            return self.store.finish_run(run_id, "success", summary=summary)
        except Exception as exc:
            logger.exception("realtime snapshot failed")
            return self.store.finish_run(run_id, "failed", summary={}, error=str(exc))

    def run_eod_update(
        self,
        *,
        trigger: str = "manual",
        target_date: Optional[str] = None,
        dry_run: bool = False,
        buffer_days: int = 7,
        workers_a_share: int = 6,
        workers_etf: int = 4,
        retry: int = 3,
        task_timeout: int = 90,
        limit_a_share: int = 0,
        limit_etf: int = 0,
        skip_a_share: bool = False,
        skip_etf: bool = False,
    ) -> Dict[str, Any]:
        target_date = target_date or self.data_lake_service.default_target_date()
        run_id = self.store.start_run("eod_update", trigger, target_date)
        try:
            summary = self.data_lake_service.run_update(
                target_date=target_date,
                dry_run=dry_run,
                buffer_days=buffer_days,
                workers_a_share=workers_a_share,
                workers_etf=workers_etf,
                retry=retry,
                task_timeout=task_timeout,
                limit_a_share=limit_a_share,
                limit_etf=limit_etf,
                skip_a_share=skip_a_share,
                skip_etf=skip_etf,
            )
            status = self._update_status_from_summary(summary, dry_run=dry_run)
            if status in {"success", "partial"}:
                self.store.set_state("last_eod_update", {"target_date": target_date, "run_id": run_id, "status": status})
            return self.store.finish_run(run_id, status, summary=summary)
        except Exception as exc:
            logger.exception("eod update failed")
            return self.store.finish_run(run_id, "failed", summary={"target_date": target_date}, error=str(exc))

    def run_eod_chain(
        self,
        *,
        trigger: str = "scheduler",
        target_date: Optional[str] = None,
        retry_run: bool = False,
    ) -> Dict[str, Any]:
        update = self.run_eod_update(trigger=trigger, target_date=target_date)
        freshness = self.data_lake_service.data_freshness(target_date=target_date)
        virtual_trade = None
        ai_cycle = None
        ai_managed_work = None
        if update.get("status") in {"success", "partial"} and freshness.get("status") != "blocked":
            virtual_trade = self.run_virtual_trade(trigger=trigger)
            ai_cycle = self.run_ai_cycle(trigger=trigger)
            ai_managed_work = self.run_ai_managed_work(work_type="eod_report", trigger=trigger)
        return {
            "update": update,
            "freshness": freshness,
            "virtual_trade": virtual_trade,
            "ai_cycle": ai_cycle,
            "ai_managed_work": ai_managed_work,
            "retry_run": retry_run,
        }

    def run_virtual_trade(self, *, trigger: str = "manual") -> Dict[str, Any]:
        target_date = self.data_lake_service.default_target_date()
        run_id = self.store.start_run("virtual_trade", trigger, target_date)
        try:
            result = self.virtual_trade_runner()
            status = str(result.get("status") or "success")
            run_status = status if status in {"success", "partial", "skipped", "failed"} else "success"
            self.store.set_state("last_virtual_trade", {"target_date": target_date, "run_id": run_id, "status": run_status})
            return self.store.finish_run(run_id, run_status, summary=result)
        except Exception as exc:
            logger.exception("virtual trade automation failed")
            return self.store.finish_run(run_id, "failed", summary={"target_date": target_date}, error=str(exc))

    def run_ai_cycle(
        self,
        *,
        trigger: str = "manual",
        decision: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        run_id = self.store.start_run("ai_cycle", trigger, self.data_lake_service.default_target_date())
        try:
            context = self.context_builder()
            decision_payload = decision or self.ai_service.call_external_ai(context)
            execution = self.ai_service.execute_decision(
                decision_payload,
                handlers=self.ai_handlers,
                source=str(decision_payload.get("source") or trigger or "ai_cycle"),
                dry_run=dry_run,
            )
            summary = {
                "context_target_date": context.get("data_freshness", {}).get("target_date"),
                "decision": execution.get("decision"),
                "action_results": execution.get("action_results"),
            }
            status = "success" if execution.get("decision", {}).get("status") not in {"failed", "rejected"} else "partial"
            return self.store.finish_run(run_id, status, summary=summary)
        except Exception as exc:
            logger.exception("ai cycle failed")
            return self.store.finish_run(run_id, "failed", summary={}, error=str(exc))

    def run_ai_managed_work(
        self,
        *,
        work_type: str = "simulation_supervision",
        trigger: str = "manual",
        decision: Optional[Dict[str, Any]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        profile = self._managed_work_profile(work_type)
        target_date = self.data_lake_service.default_target_date()
        run_id = self.store.start_run("ai_managed_work", trigger, target_date)
        work_id = self.store.start_ai_work(work_type, trigger, target_date=target_date, title=str(profile["title"]))
        try:
            context = self.context_builder()
            managed_context = self._managed_context(context, work_type, profile, dry_run=dry_run)
            decision_payload = decision or self.ai_service.call_external_ai(managed_context)
            decision_payload = self._prepare_managed_decision(decision_payload, work_type, profile, context, dry_run=dry_run)
            execution = self.ai_service.execute_decision(
                decision_payload,
                handlers=self.ai_handlers,
                source=str(decision_payload.get("source") or trigger or work_type),
                dry_run=dry_run,
            )
            action_results = execution.get("action_results") or []
            decision_record = execution.get("decision") or {}
            work_items = self._work_items_from_action_results(action_results)
            summary_text = self._managed_summary_text(profile, decision_record, work_items)
            status = self._managed_run_status(str(decision_record.get("status") or ""), action_results)
            work_log = self.store.finish_ai_work(
                work_id,
                status,
                title=str(profile["title"]),
                summary=summary_text,
                work_items=work_items,
                actions=decision_payload.get("actions") if isinstance(decision_payload.get("actions"), list) else [],
                result={"decision": decision_record, "action_results": action_results},
                error=decision_record.get("error"),
            )
            summary = {
                "work_log": work_log,
                "decision": decision_record,
                "action_results": action_results,
                "work_type": work_type,
            }
            return self.store.finish_run(run_id, status, summary=summary, error=work_log.get("error"))
        except Exception as exc:
            logger.exception("ai managed work failed")
            self.store.finish_ai_work(
                work_id,
                "failed",
                title=str(profile["title"]),
                summary=f"{profile['title']} 执行失败: {exc}",
                error=str(exc),
            )
            return self.store.finish_run(run_id, "failed", summary={"work_type": work_type}, error=str(exc))

    def status_payload(self, scheduler: Optional["LightweightScheduler"] = None) -> Dict[str, Any]:
        freshness = self.data_lake_service.data_freshness(max_scan=300)
        return {
            "scheduler": scheduler.status_payload() if scheduler else {"enabled": False, "running": False},
            "data_freshness": freshness,
            "recent_runs": self.store.list_runs(limit=12),
            "recent_snapshots": self.store.latest_snapshots(limit=5),
            "ai_decisions": self.store.list_ai_decisions(limit=5),
            "ai_work_logs": self.store.list_ai_work_logs(limit=8),
            "last_eod_update": self.store.get_state("last_eod_update", {}),
            "last_virtual_trade": self.store.get_state("last_virtual_trade", {}),
        }

    def _managed_work_profile(self, work_type: str) -> Dict[str, Any]:
        profile = MANAGED_WORK_PROFILES.get(work_type)
        if profile:
            return profile
        fallback = dict(MANAGED_WORK_PROFILES["simulation_supervision"])
        fallback["title"] = f"AI 托管任务: {work_type}"
        return fallback

    def _managed_context(
        self,
        context: Dict[str, Any],
        work_type: str,
        profile: Dict[str, Any],
        *,
        dry_run: bool,
    ) -> Dict[str, Any]:
        managed = dict(context)
        managed["ai_work_order"] = {
            "work_type": work_type,
            "title": profile["title"],
            "objective": profile["objective"],
            "dry_run": dry_run,
            "authority_scope": [
                "可以自动执行模拟盘追赶、数据完整性检查、Factor Lab 研究/回测/压力测试、影子观察和日报。",
                "不得真实下单、不得删除数据、不得修改源码、不得绕过现有并发锁和策略版本门禁。",
                "当数据完整性阻塞时，只允许记录原因、发起完整性检查或 dry-run，不得强行调仓。",
            ],
            "preferred_actions": self._defaulted_profile_actions(profile, context),
            "output_contract": "Return strict JSON: summary, confidence, actions[].",
        }
        return managed

    def _prepare_managed_decision(
        self,
        decision: Dict[str, Any],
        work_type: str,
        profile: Dict[str, Any],
        context: Dict[str, Any],
        *,
        dry_run: bool,
    ) -> Dict[str, Any]:
        normalized = dict(decision or {})
        normalized.setdefault("actor", "ai_managed_work")
        normalized.setdefault("source", work_type)
        normalized.setdefault("summary", str(profile["objective"]))
        normalized["dry_run"] = bool(dry_run or normalized.get("dry_run"))

        actions = normalized.get("actions") if isinstance(normalized.get("actions"), list) else []
        normalized_actions = [self._default_action_params(action, context) for action in actions if isinstance(action, dict)]
        present_types = {str(action.get("type") or "") for action in normalized_actions}

        for required_type in profile.get("required_actions", []):
            action_type = str(required_type)
            if action_type in present_types:
                continue
            if not self._managed_action_allowed_now(action_type, context):
                continue
            normalized_actions.append(self._default_action_params({"type": action_type, "params": {}}, context))
            present_types.add(action_type)

        normalized["actions"] = normalized_actions
        return normalized

    def _defaulted_profile_actions(self, profile: Dict[str, Any], context: Dict[str, Any]) -> List[Dict[str, Any]]:
        actions = profile.get("preferred_actions") if isinstance(profile.get("preferred_actions"), list) else []
        return [self._default_action_params(action, context) for action in actions if isinstance(action, dict)]

    def _default_action_params(self, action: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        action_type = str(action.get("type") or "")
        params = dict(action.get("params") or {}) if isinstance(action.get("params"), dict) else {}
        target_date = self._context_target_date(context)
        if action_type in {"run_factor_lab", "run_factor_lab_backtest"}:
            params.setdefault("start_date", "2022-01-01")
            params.setdefault("end_date", target_date)
            params.setdefault("pool", "core")
            params.setdefault("label", "next_5d_ret")
            params.setdefault("top_n", 5)
            params.setdefault("max_symbols", 300)
            if action_type == "run_factor_lab_backtest":
                params.setdefault("factor", "ml_factor_ranker")
                params.setdefault("initial_capital", 1000000.0)
                params.setdefault("max_positions", 5)
        elif action_type == "run_factor_lab_stress_test":
            params.setdefault("pool", "core")
            params.setdefault("max_symbols", 300)
            params.setdefault("top_n", 5)
            params.setdefault("anchor_date", target_date)
            params.setdefault("factors", ["ml_factor_ranker"])
        elif action_type == "check_data_integrity":
            params.setdefault("target_date", target_date)
            params.setdefault("max_scan", 300)
        elif action_type == "generate_daily_report":
            params.setdefault("target_date", target_date)
        elif action_type == "realtime_snapshot":
            params.setdefault("limit", 200)
        return {"type": action_type, "params": params}

    def _managed_action_allowed_now(self, action_type: str, context: Dict[str, Any]) -> bool:
        freshness = context.get("data_freshness") if isinstance(context.get("data_freshness"), dict) else {}
        if action_type == "run_virtual_trade" and freshness.get("status") == "blocked":
            return False
        if action_type in {"run_factor_lab", "run_factor_lab_backtest", "run_factor_lab_stress_test"}:
            a_share = freshness.get("a_share") if isinstance(freshness.get("a_share"), dict) else {}
            checked = int(a_share.get("checked_count") or 0)
            fresh = int(a_share.get("fresh_count") or 0)
            return checked == 0 or fresh >= checked
        return True

    def _context_target_date(self, context: Dict[str, Any]) -> str:
        freshness = context.get("data_freshness") if isinstance(context.get("data_freshness"), dict) else {}
        target_date = freshness.get("target_date") or self.data_lake_service.default_target_date()
        return str(target_date)

    @staticmethod
    def _work_items_from_action_results(action_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for result in action_results:
            if not isinstance(result, dict):
                continue
            detail = result.get("error") or result.get("reason")
            if detail is None and isinstance(result.get("result"), dict):
                detail = result["result"].get("status") or result["result"].get("message")
            items.append(
                {
                    "action": result.get("type") or "unknown",
                    "status": result.get("status") or "unknown",
                    "detail": str(detail or "")[:240],
                }
            )
        return items

    @staticmethod
    def _managed_summary_text(
        profile: Dict[str, Any],
        decision_record: Dict[str, Any],
        work_items: List[Dict[str, Any]],
    ) -> str:
        summary = str(decision_record.get("summary") or profile.get("objective") or "")
        status_line = "；".join(
            f"{item.get('action')}={item.get('status')}" for item in work_items[:8] if item.get("action")
        )
        if status_line:
            return f"{summary} 动作结果：{status_line}。"
        return summary

    @staticmethod
    def _managed_run_status(decision_status: str, action_results: List[Dict[str, Any]]) -> str:
        if decision_status == "dry_run":
            return "dry_run"
        statuses = {str(item.get("status")) for item in action_results if isinstance(item, dict)}
        if "failed" in statuses:
            return "partial" if "executed" in statuses or "planned" in statuses else "failed"
        if statuses and statuses <= {"rejected"}:
            return "failed"
        if "rejected" in statuses:
            return "partial"
        if "executed" in statuses or "planned" in statuses:
            return "success"
        if decision_status in {"failed", "rejected"}:
            return "failed"
        return "skipped"

    def _fetch_market_snapshot(self, *, limit: int) -> tuple[List[Dict[str, Any]], str]:
        limit = max(1, min(int(limit or 200), 1000))
        try:
            ak = __import__("akshare")
            frame = ak.stock_zh_a_spot_em()
            if frame is not None and not frame.empty:
                if "涨跌幅" in frame.columns:
                    frame = frame.sort_values("涨跌幅", ascending=False)
                return frame.head(limit).to_dict(orient="records"), "akshare_spot_em"
        except Exception as exc:
            logger.warning("akshare spot snapshot failed, falling back to latest cache: %s", exc)
        rows = self.data_manager.get_latest_market_overview(limit=limit)
        return rows[:limit], "latest_market_overview"

    @staticmethod
    def _market_session(now: datetime) -> str:
        hm = now.strftime("%H:%M")
        if "09:30" <= hm <= "11:30":
            return "morning"
        if "13:00" <= hm <= "15:00":
            return "afternoon"
        if hm > "15:00":
            return "after_close"
        return "pre_open"

    @staticmethod
    def _update_status_from_summary(summary: Dict[str, Any], *, dry_run: bool) -> str:
        if dry_run:
            return "success"
        failed = 0
        for key in ("a_share", "etf"):
            section = summary.get(key)
            if isinstance(section, dict):
                failed += int(section.get("failed") or 0)
        return "partial" if failed else "success"


class LightweightScheduler:
    def __init__(self, orchestrator: AutomationOrchestrator, *, poll_seconds: int = 30):
        self.orchestrator = orchestrator
        self.poll_seconds = max(5, int(poll_seconds or 30))
        self.enabled = os.getenv("QUANT_AUTOMATION_SCHEDULER_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._run_lock = threading.Lock()

    def start(self) -> None:
        if not self.enabled:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="quant-automation-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def status_payload(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": bool(self._thread and self._thread.is_alive()),
            "poll_seconds": self.poll_seconds,
            "next_jobs": self.next_jobs(datetime.now()),
            "schedules": {
                "realtime_snapshot": INTRADAY_SNAPSHOT_TIMES,
                "eod_update": EOD_UPDATE_TIMES,
                "ai_cycle": AI_CYCLE_TIMES,
                "ai_managed_work": AI_MANAGED_WORK_SCHEDULES,
            },
        }

    def next_jobs(self, now: datetime) -> List[Dict[str, str]]:
        jobs = []
        schedules = [
            ("realtime_snapshot", INTRADAY_SNAPSHOT_TIMES),
            ("eod_update", EOD_UPDATE_TIMES),
            ("ai_cycle", AI_CYCLE_TIMES),
        ]
        for job_type, times in schedules:
            for hm in times:
                run_at = self._datetime_for_hm(now, hm)
                if run_at < now:
                    run_at = run_at + timedelta(days=1)
                jobs.append({"job_type": job_type, "run_at": run_at.isoformat(timespec="minutes")})
        for work_type, times in AI_MANAGED_WORK_SCHEDULES.items():
            for hm in times:
                run_at = self._datetime_for_hm(now, hm)
                if run_at < now:
                    run_at = run_at + timedelta(days=1)
                jobs.append(
                    {
                        "job_type": "ai_managed_work",
                        "work_type": work_type,
                        "run_at": run_at.isoformat(timespec="minutes"),
                    }
                )
        return sorted(jobs, key=lambda item: item["run_at"])[:6]

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick(datetime.now())
            except Exception:
                logger.exception("scheduler tick failed")
            self._stop.wait(self.poll_seconds)

    def _tick(self, now: datetime) -> None:
        if not self.enabled or not self.orchestrator.data_lake_service.is_trade_day(now):
            return
        if not self._run_lock.acquire(blocking=False):
            return
        try:
            date_key = now.strftime("%Y-%m-%d")
            hm = now.strftime("%H:%M")
            for schedule_hm in INTRADAY_SNAPSHOT_TIMES:
                if hm >= schedule_hm:
                    self._run_once(date_key, f"realtime_snapshot:{schedule_hm}", lambda: self.orchestrator.run_realtime_snapshot(trigger="scheduler"))
            for idx, schedule_hm in enumerate(EOD_UPDATE_TIMES):
                if hm >= schedule_hm:
                    self._run_once(
                        date_key,
                        f"eod_update:{schedule_hm}",
                        lambda retry_run=idx > 0: self.orchestrator.run_eod_chain(trigger="scheduler", retry_run=retry_run),
                    )
            for schedule_hm in AI_CYCLE_TIMES:
                if hm >= schedule_hm:
                    self._run_once(date_key, f"ai_cycle:{schedule_hm}", lambda: self.orchestrator.run_ai_cycle(trigger="scheduler"))
            for work_type, times in AI_MANAGED_WORK_SCHEDULES.items():
                for schedule_hm in times:
                    if hm >= schedule_hm:
                        self._run_once(
                            date_key,
                            f"ai_managed_work:{work_type}:{schedule_hm}",
                            lambda selected_work_type=work_type: self.orchestrator.run_ai_managed_work(
                                work_type=selected_work_type,
                                trigger="scheduler",
                            ),
                        )
        finally:
            self._run_lock.release()

    def _run_once(self, date_key: str, task_key: str, runner: Callable[[], Any]) -> None:
        state_key = f"scheduler_done:{date_key}:{task_key}"
        if self.orchestrator.store.get_state(state_key):
            return
        result = runner()
        self.orchestrator.store.set_state(
            state_key,
            {"completed_at": datetime.now().isoformat(timespec="seconds"), "result": result},
        )

    @staticmethod
    def _datetime_for_hm(day: datetime, hm: str) -> datetime:
        hour, minute = [int(part) for part in hm.split(":", 1)]
        return day.replace(hour=hour, minute=minute, second=0, microsecond=0)
