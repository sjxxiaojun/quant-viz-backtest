from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import pandas as pd
import requests

import subprocess
from ai_automation import AIAutomationService
from automation_store import AutomationStore
from data_lake_update_service import DataLakeUpdateService
from data_manager import DataManager
from data_sentinel import DataSentinel


logger = logging.getLogger("AutomationScheduler")


VirtualTradeRunner = Callable[[], Dict[str, Any]]
ContextBuilder = Callable[[], Dict[str, Any]]


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

EASTMONEY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json,text/plain,*/*",
    "Connection": "close",
}
EASTMONEY_A_SHARE_URL = "https://82.push2delay.eastmoney.com/api/qt/clist/get"
EASTMONEY_ETF_URL = "https://88.push2delay.eastmoney.com/api/qt/clist/get"
EASTMONEY_STOCK_GET_URL = "https://push2delay.eastmoney.com/api/qt/stock/get"
EASTMONEY_A_SHARE_FS = "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048"
EASTMONEY_ETF_FS = "b:MK0021,b:MK0022,b:MK0023,b:MK0024,b:MK0827"
EASTMONEY_FIELDS = "f12,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18"
EASTMONEY_QUOTE_FIELDS = "f43,f57,f58,f46,f44,f45,f60,f170,f169,f47,f48,f168,f50,f49,f161"

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
STALE_TASK_TIMEOUT_MINUTES = _env_int("QUANT_AUTOMATION_TASK_TIMEOUT_MINUTES", 120)
STALE_RUN_TIMEOUTS = {
    "realtime_snapshot": _env_int("QUANT_SNAPSHOT_TIMEOUT_MINUTES", 15),
    "eod_update": _env_int("QUANT_EOD_UPDATE_TIMEOUT_MINUTES", 240),
    "virtual_trade": _env_int("QUANT_VIRTUAL_TRADE_TIMEOUT_MINUTES", 30),
    "ai_cycle": _env_int("QUANT_AI_CYCLE_TIMEOUT_MINUTES", 15),
}
STALE_AI_WORK_TIMEOUTS = {
    "premarket_plan": _env_int("QUANT_AI_WORK_TIMEOUT_MINUTES", 30),
    "intraday_review": _env_int("QUANT_AI_WORK_TIMEOUT_MINUTES", 30),
    "simulation_supervision": _env_int("QUANT_AI_WORK_TIMEOUT_MINUTES", 30),
    "factor_lab_iteration": _env_int("QUANT_FACTOR_LAB_WORK_TIMEOUT_MINUTES", 120),
    "eod_report": _env_int("QUANT_AI_WORK_TIMEOUT_MINUTES", 30),
}
EOD_PROGRESS_MESSAGE_INTERVAL_SECONDS = _env_int("QUANT_EOD_PROGRESS_MESSAGE_SECONDS", 600)

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
            {"type": "realtime_snapshot", "params": {"limit": 6000}},
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

AI_ACTION_LABELS = {
    "run_virtual_trade": "追赶模拟盘",
    "check_data_integrity": "数据完整性检查",
    "trigger_eod_update": "触发收盘补数",
    "realtime_snapshot": "盘中快照",
    "run_factor_lab": "Factor Lab 研究",
    "run_factor_lab_backtest": "Factor Lab 回测",
    "run_factor_lab_stress_test": "Factor Lab 压力测试",
    "promote_factor_lab_candidate": "候选策略推进",
    "start_shadow_observation": "影子观察",
    "approve_strategy_version": "策略版本审批",
    "activate_strategy_version": "策略版本激活",
    "generate_daily_report": "生成日报",
}

AI_ACTION_STATUS_LABELS = {
    "executed": "已执行",
    "planned": "已规划",
    "skipped": "已跳过",
    "rejected": "已拒绝",
    "failed": "失败",
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
        self._eod_update_lock = threading.Lock()
        self.ai_handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}
        self.sentinel = DataSentinel()

    def set_ai_handlers(self, handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]) -> None:
        self.ai_handlers = handlers

    def run_data_sentinel(self, *, target_date: Optional[str] = None, trigger: str = "manual") -> Dict[str, Any]:
        target_date = target_date or self.data_lake_service.default_target_date()
        run_id = self.store.start_run("data_sentinel", trigger, target_date)
        try:
            report = self.sentinel.check_data_health(target_date)
            status = report.get("status", "unknown")
            self._record_ai_work_message(
                work_id=run_id,
                work_type="data_sentinel",
                trigger=trigger,
                target_date=target_date,
                action_type="check_data_integrity",
                status="success",
                title=f"数据健康检查完成: {status}",
                body=f"目标日期: {target_date}, 健康评分: {report.get('health_score')}%",
                details=report,
            )
            return self.store.finish_run(run_id, "success", summary=report)
        except Exception as exc:
            logger.exception("data sentinel failed")
            return self.store.finish_run(run_id, "failed", summary={}, error=str(exc))

    def run_jiucai_capture(self, *, trigger: str = "manual") -> Dict[str, Any]:
        run_id = self.store.start_run("jiucai_capture", trigger)
        skill_dir = "/Users/gdxj/.agents/skills/capture-韭菜公社"
        try:
            # 抓取异动和产业链（较快）
            cmd = f"cd {skill_dir} && uv run python -m a_stock_watcher.cli fetch --source action && uv run python -m a_stock_watcher.cli fetch --source industry_chain"
            process = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
            
            if process.returncode != 0:
                raise RuntimeError(f"Jiucai capture failed: {process.stderr}")

            summary = {"status": "success", "output_tail": process.stdout[-1000:]}
            self._record_ai_work_message(
                work_id=run_id,
                work_type="jiucai_capture",
                trigger=trigger,
                target_date=None,
                action_type="sentiment_analysis",
                status="success",
                title="韭菜公社舆情抓取完成",
                body="已更新异动板块和产业链关注度数据。",
                details=summary,
            )
            return self.store.finish_run(run_id, "success", summary=summary)
        except Exception as exc:
            logger.exception("jiucai capture failed")
            return self.store.finish_run(run_id, "failed", summary={}, error=str(exc))

    def run_realtime_snapshot(self, *, trigger: str = "manual", limit: int = 6000) -> Dict[str, Any]:
        run_id = self.store.start_run("realtime_snapshot", trigger)
        try:
            rows, source = self._fetch_market_snapshot(limit=limit)
            snapshot = self.store.record_market_snapshot(
                rows,
                market_session=self._market_session(datetime.now()),
                source=source,
            )
            summary = {"snapshot": snapshot, "row_count": len(rows), "source": source}
            self._record_ai_work_message(
                work_id=run_id,
                work_type="realtime_snapshot",
                trigger=trigger,
                target_date=None,
                action_type="realtime_snapshot",
                status="success",
                title="盘中快照已更新",
                body=self._snapshot_message_body(rows, snapshot),
                details={"snapshot": snapshot, "top_movers": self._top_snapshot_rows(rows, limit=5)},
            )
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
        self._expire_stale_running_tasks()
        active_run = self._active_running_run("eod_update")
        if active_run:
            run_id = self.store.start_run("eod_update", trigger, target_date)
            summary = {
                "target_date": target_date,
                "dry_run": dry_run,
                "skipped_reason": "already_running",
                "active_run_id": active_run.get("run_id"),
                "active_started_at": active_run.get("started_at"),
            }
            self.store.record_ai_work_message(
                work_id=run_id,
                work_type="eod_update",
                trigger=trigger,
                target_date=target_date,
                action_type="eod_update",
                status="skipped",
                level="warning",
                title="数据湖补数已跳过",
                body=(
                    f"已有数据湖补数任务 {active_run.get('run_id')} 正在运行，"
                    "本次请求没有启动第二个并发补数。"
                ),
                details={"active_run": active_run, "request": summary},
            )
            return self.store.finish_run(run_id, "skipped", summary=summary)

        if not self._eod_update_lock.acquire(blocking=False):
            run_id = self.store.start_run("eod_update", trigger, target_date)
            summary = {"target_date": target_date, "dry_run": dry_run, "skipped_reason": "lock_held"}
            self.store.record_ai_work_message(
                work_id=run_id,
                work_type="eod_update",
                trigger=trigger,
                target_date=target_date,
                action_type="eod_update",
                status="skipped",
                level="warning",
                title="数据湖补数已跳过",
                body="已有数据湖补数线程正在运行，本次请求没有启动第二个并发补数。",
                details={"request": summary},
            )
            return self.store.finish_run(run_id, "skipped", summary=summary)

        run_id = self.store.start_run("eod_update", trigger, target_date)
        progress_reporter: Optional[tuple[threading.Event, threading.Thread]] = None
        try:
            self.store.record_ai_work_message(
                work_id=run_id,
                work_type="eod_update",
                trigger=trigger,
                target_date=target_date,
                action_type="eod_update",
                status="running",
                title="数据湖补数开始" if not dry_run else "数据湖补数演练开始",
                body=(
                    f"开始{'演练' if dry_run else '更新'} {target_date} 数据湖；"
                    f"A股限制 {limit_a_share or '全量'}，ETF限制 {limit_etf or '全量'}。"
                ),
                details={
                    "dry_run": dry_run,
                    "buffer_days": buffer_days,
                    "workers_a_share": workers_a_share,
                    "workers_etf": workers_etf,
                    "retry": retry,
                    "task_timeout": task_timeout,
                    "limit_a_share": limit_a_share,
                    "limit_etf": limit_etf,
                },
            )
            progress_reporter = self._start_eod_progress_reporter(
                run_id=run_id,
                trigger=trigger,
                target_date=target_date,
                dry_run=dry_run,
            )
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
            if not dry_run and status in {"success", "partial"}:
                self.store.set_state("last_eod_update", {"target_date": target_date, "run_id": run_id, "status": status})
            finished = self.store.finish_run(run_id, status, summary=summary)
            self.store.record_ai_work_message(
                work_id=run_id,
                work_type="eod_update",
                trigger=trigger,
                target_date=target_date,
                action_type="eod_update",
                status=status,
                level="warning" if status == "partial" else "info",
                title="数据湖补数完成" if not dry_run else "数据湖补数演练完成",
                body=self._eod_update_message_body(summary, dry_run=dry_run, status=status),
                details={"run_id": run_id, "summary": summary},
            )
            return finished
        except Exception as exc:
            logger.exception("eod update failed")
            failed = self.store.finish_run(run_id, "failed", summary={"target_date": target_date}, error=str(exc))
            self.store.record_ai_work_message(
                work_id=run_id,
                work_type="eod_update",
                trigger=trigger,
                target_date=target_date,
                action_type="eod_update",
                status="failed",
                level="error",
                title="数据湖补数失败",
                body=f"{target_date} 数据湖补数失败：{exc}",
                details={"run_id": run_id, "error": str(exc)},
            )
            return failed
        finally:
            if progress_reporter:
                stop_event, thread = progress_reporter
                stop_event.set()
                thread.join(timeout=1)
            self._eod_update_lock.release()

    def run_eod_chain(
        self,
        *,
        trigger: str = "scheduler",
        target_date: Optional[str] = None,
        retry_run: bool = False,
    ) -> Dict[str, Any]:
        update = self.run_eod_update(trigger=trigger, target_date=target_date)
        sentinel = self.run_data_sentinel(trigger=trigger, target_date=target_date)
        jiucai = self.run_jiucai_capture(trigger=trigger)
        
        freshness = self.data_lake_service.data_freshness(target_date=target_date)
        virtual_trade = None
        ai_cycle = None
        ai_managed_work = None
        # Use sentinel status to guard the rest of the chain if health is critical
        sentinel_status = sentinel.get("summary", {}).get("status", "healthy")
        
        if update.get("status") in {"success", "partial"} and freshness.get("status") != "blocked" and sentinel_status != "critical":
            virtual_trade = self.run_virtual_trade(trigger=trigger)
            ai_cycle = self.run_ai_cycle(trigger=trigger)
            ai_managed_work = self.run_ai_managed_work(work_type="eod_report", trigger=trigger)
        elif update.get("status") in {"success", "partial"}:
            self._record_ai_work_message(
                work_id=str(update.get("run_id") or f"eod_chain-{target_date or 'latest'}"),
                work_type="eod_update",
                trigger=trigger,
                target_date=target_date or freshness.get("target_date"),
                action_type="eod_chain_blocked",
                status="blocked",
                level="warning",
                title="收盘自动链路阻塞",
                body=(
                    f"数据湖补数结束，但数据校验结果为 {sentinel_status} 且新鲜度为 {freshness.get('status')}，"
                    "本次未继续触发模拟盘和 AI cycle。请检查数据源质量。"
                ),
                details={"update": update, "freshness": freshness, "sentinel": sentinel, "retry_run": retry_run},
            )
        return {
            "update": update,
            "sentinel": sentinel,
            "jiucai": jiucai,
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
        target_date = self.data_lake_service.default_target_date()
        run_id = self.store.start_run("ai_cycle", trigger, target_date)
        self._record_ai_work_message(
            work_id=run_id,
            work_type="ai_cycle",
            trigger=trigger,
            target_date=target_date,
            action_type="cycle_start",
            status="running",
            title="AI cycle 开始",
            body="开始读取系统状态、请求 AI 决策，并在白名单权限内执行模拟盘相关动作。",
            details={"dry_run": dry_run},
        )
        try:
            context = self.context_builder()
            context_target_date = self._context_target_date(context)
            decision_payload = decision or self._call_ai_cycle_with_fallback(context)
            execution = self.ai_service.execute_decision(
                decision_payload,
                handlers=self.ai_handlers,
                source=str(decision_payload.get("source") or trigger or "ai_cycle"),
                dry_run=dry_run,
                on_action_result=lambda result: self._record_ai_action_message(
                    result,
                    work_id=run_id,
                    work_type="ai_cycle",
                    trigger=trigger,
                    target_date=context_target_date,
                ),
            )
            summary = {
                "context_target_date": context_target_date,
                "decision": execution.get("decision"),
                "action_results": execution.get("action_results"),
            }
            status = "success" if execution.get("decision", {}).get("status") not in {"failed", "rejected"} else "partial"
            decision_record = execution.get("decision") or {}
            action_results = execution.get("action_results") or []
            self._record_ai_work_message(
                work_id=run_id,
                work_type="ai_cycle",
                trigger=trigger,
                target_date=context_target_date,
                action_type="cycle_finish",
                status=status,
                level=self._message_level_for_status(status),
                title="AI cycle 完成" if status == "success" else "AI cycle 部分完成",
                body=str(decision_record.get("summary") or "AI cycle 已完成。"),
                details={
                    "decision_id": decision_record.get("decision_id"),
                    "decision_status": decision_record.get("status"),
                    "action_count": len(action_results) if isinstance(action_results, list) else 0,
                },
            )
            return self.store.finish_run(run_id, status, summary=summary)
        except Exception as exc:
            logger.exception("ai cycle failed")
            self._record_ai_work_message(
                work_id=run_id,
                work_type="ai_cycle",
                trigger=trigger,
                target_date=target_date,
                action_type="cycle_failed",
                status="failed",
                level="error",
                title="AI cycle 失败",
                body=f"AI cycle 执行失败：{exc}",
                details={"error": str(exc)},
            )
            return self.store.finish_run(run_id, "failed", summary={}, error=str(exc))

    def _call_ai_cycle_with_fallback(self, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return self.ai_service.call_external_ai(context)
        except Exception as exc:
            logger.warning("external ai cycle call failed, using local fallback: %s", exc)
            target_date = self._context_target_date(context)
            return {
                "actor": "local_guardrail",
                "source": "ai_cycle_fallback",
                "summary": f"外部 AI 调用失败，已生成本地 AI cycle 日报兜底。原因：{exc}",
                "confidence": 1.0,
                "actions": [{"type": "generate_daily_report", "params": {"mode": "ai_cycle_fallback", "target_date": target_date}}],
            }

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
        self._record_ai_work_message(
            work_id=work_id,
            work_type=work_type,
            trigger=trigger,
            target_date=target_date,
            action_type="work_start",
            status="running",
            title=f"{profile['title']}开始",
            body=str(profile["objective"]),
            details={"run_id": run_id, "dry_run": dry_run},
        )
        try:
            context = self.context_builder()
            context_target_date = self._context_target_date(context)
            managed_context = self._managed_context(context, work_type, profile, dry_run=dry_run)
            decision_payload = decision or self._call_managed_ai_with_fallback(work_type, profile, managed_context)
            decision_payload = self._prepare_managed_decision(decision_payload, work_type, profile, context, dry_run=dry_run)
            execution = self.ai_service.execute_decision(
                decision_payload,
                handlers=self.ai_handlers,
                source=str(decision_payload.get("source") or trigger or work_type),
                dry_run=dry_run,
                on_action_result=lambda result: self._record_ai_action_message(
                    result,
                    work_id=work_id,
                    work_type=work_type,
                    trigger=trigger,
                    target_date=context_target_date,
                ),
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
            self._record_ai_work_message(
                work_id=work_id,
                work_type=work_type,
                trigger=trigger,
                target_date=context_target_date,
                action_type="work_finish",
                status=status,
                level=self._message_level_for_status(status),
                title=f"{profile['title']}完成" if status in {"success", "dry_run"} else f"{profile['title']}结束",
                body=summary_text or str(profile["objective"]),
                details={
                    "run_id": run_id,
                    "work_log_id": work_log.get("work_id"),
                    "decision_id": decision_record.get("decision_id"),
                    "action_count": len(action_results) if isinstance(action_results, list) else 0,
                },
            )
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
            self._record_ai_work_message(
                work_id=work_id,
                work_type=work_type,
                trigger=trigger,
                target_date=target_date,
                action_type="work_failed",
                status="failed",
                level="error",
                title=f"{profile['title']}失败",
                body=f"{profile['title']}执行失败：{exc}",
                details={"run_id": run_id, "error": str(exc)},
            )
            return self.store.finish_run(run_id, "failed", summary={"work_type": work_type}, error=str(exc))

    def _call_managed_ai_with_fallback(
        self,
        work_type: str,
        profile: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        try:
            return self.ai_service.call_external_ai(context)
        except Exception as exc:
            logger.warning("external ai managed work call failed, using local fallback: %s", exc)
            return {
                "actor": "local_guardrail",
                "source": f"{work_type}_fallback",
                "summary": f"外部 AI 调用失败，按内置托管动作继续执行。原因：{exc}",
                "confidence": 1.0,
                "actions": profile.get("preferred_actions") if isinstance(profile.get("preferred_actions"), list) else [],
            }

    def status_payload(self, scheduler: Optional["LightweightScheduler"] = None) -> Dict[str, Any]:
        self._expire_stale_running_tasks()
        freshness = self.data_lake_service.data_freshness(max_scan=300)
        return {
            "scheduler": scheduler.status_payload() if scheduler else {"enabled": False, "running": False},
            "data_freshness": freshness,
            "recent_runs": self.store.list_runs(limit=12),
            "recent_snapshots": self.store.latest_snapshots(limit=5),
            "ai_decisions": self.store.list_ai_decisions(limit=5),
            "ai_work_logs": self.store.list_ai_work_logs(limit=8),
            "ai_work_messages": self.store.list_ai_work_messages(limit=30),
            "last_eod_update": self.store.get_state("last_eod_update", {}),
            "last_virtual_trade": self.store.get_state("last_virtual_trade", {}),
        }

    def _expire_stale_running_tasks(self) -> None:
        try:
            expired_runs = self.store.expire_stale_runs(
                max_age_minutes=STALE_TASK_TIMEOUT_MINUTES,
                job_timeouts=STALE_RUN_TIMEOUTS,
            )
            expired_ai_work = self.store.expire_stale_ai_work_logs(
                max_age_minutes=STALE_TASK_TIMEOUT_MINUTES,
                work_timeouts=STALE_AI_WORK_TIMEOUTS,
            )
        except AttributeError:
            return
        except Exception:
            logger.exception("failed to expire stale automation tasks")
            return

        for run in expired_runs:
            timeout_minutes = (run.get("summary") or {}).get("timeout_minutes", STALE_TASK_TIMEOUT_MINUTES)
            self._record_ai_work_message(
                work_id=str(run.get("run_id") or ""),
                work_type=str(run.get("job_type") or "automation"),
                trigger=str(run.get("trigger") or "system"),
                target_date=run.get("target_date"),
                action_type="timeout",
                status="failed",
                level="error",
                title="自动化任务超时",
                body=(
                    f"{run.get('job_type')} 从 {run.get('started_at')} 开始后超过 "
                    f"{timeout_minutes} 分钟未结束，已自动标记失败。"
                ),
                details={"run": run},
            )

        for work in expired_ai_work:
            timeout_minutes = (work.get("result") or {}).get("timeout_minutes", STALE_TASK_TIMEOUT_MINUTES)
            self._record_ai_work_message(
                work_id=str(work.get("work_id") or ""),
                work_type=str(work.get("work_type") or "ai_work"),
                trigger=str(work.get("trigger") or "system"),
                target_date=work.get("target_date"),
                action_type="timeout",
                status="failed",
                level="error",
                title="AI 托管任务超时",
                body=(
                    f"{work.get('title') or work.get('work_type')} 从 {work.get('started_at')} 开始后超过 "
                    f"{timeout_minutes} 分钟未结束，已自动标记失败。"
                ),
                details={"work": work},
            )

    def _active_running_run(self, job_type: str) -> Optional[Dict[str, Any]]:
        for run in self.store.list_runs(job_type=job_type, limit=20):
            if run.get("status") == "running":
                return run
        return None

    def _start_eod_progress_reporter(
        self,
        *,
        run_id: str,
        trigger: str,
        target_date: str,
        dry_run: bool,
    ) -> Optional[tuple[threading.Event, threading.Thread]]:
        if dry_run or EOD_PROGRESS_MESSAGE_INTERVAL_SECONDS <= 0:
            return None

        stop_event = threading.Event()

        def report_loop() -> None:
            while not stop_event.wait(EOD_PROGRESS_MESSAGE_INTERVAL_SECONDS):
                try:
                    freshness = self.data_lake_service.data_freshness(target_date=target_date, max_scan=300)
                    self._record_ai_work_message(
                        work_id=run_id,
                        work_type="eod_update",
                        trigger=trigger,
                        target_date=target_date,
                        action_type="eod_progress",
                        status="running",
                        title="数据湖补数进行中",
                        body=self._eod_progress_message_body(freshness),
                        details={"freshness": freshness},
                    )
                except Exception:
                    logger.exception("failed to record eod progress message")

        thread = threading.Thread(target=report_loop, daemon=True, name=f"eod-progress-{run_id}")
        thread.start()
        return stop_event, thread

    def _record_ai_work_message(
        self,
        *,
        work_id: str,
        work_type: str,
        trigger: str,
        target_date: Optional[str],
        action_type: str,
        status: str,
        title: str,
        body: str,
        level: str = "info",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        try:
            self.store.record_ai_work_message(
                work_id=work_id,
                work_type=work_type,
                trigger=trigger,
                target_date=target_date,
                action_type=action_type,
                status=status,
                level=level,
                title=title,
                body=body,
                details=details or {},
            )
        except Exception:
            logger.exception("failed to record ai work message")

    def _record_ai_action_message(
        self,
        result: Dict[str, Any],
        *,
        work_id: str,
        work_type: str,
        trigger: str,
        target_date: Optional[str],
    ) -> None:
        if not isinstance(result, dict):
            return
        action_type = str(result.get("type") or result.get("action") or "unknown")
        status = str(result.get("status") or "unknown")
        label = AI_ACTION_LABELS.get(action_type, action_type)
        status_label = AI_ACTION_STATUS_LABELS.get(status, status)
        self._record_ai_work_message(
            work_id=work_id,
            work_type=work_type,
            trigger=trigger,
            target_date=target_date,
            action_type=action_type,
            status=status,
            level=self._message_level_for_status(status),
            title=f"{label} / {status_label}",
            body=self._action_message_body(action_type, status, result),
            details=self._compact_message_details(result),
        )

    @staticmethod
    def _message_level_for_status(status: str) -> str:
        if status in {"failed", "rejected", "blocked"}:
            return "error"
        if status in {"partial", "skipped", "degraded"}:
            return "warn"
        return "info"

    @staticmethod
    def _action_message_body(action_type: str, status: str, result: Dict[str, Any]) -> str:
        label = AI_ACTION_LABELS.get(action_type, action_type or "AI 动作")
        if status == "planned":
            return f"{label}已加入 dry-run 计划，未改变系统状态。"
        if status == "skipped":
            return f"{label}已跳过：{result.get('reason') or '当前条件或处理器未满足'}。"
        if status == "rejected":
            return f"{label}被权限边界拒绝：{result.get('reason') or '动作不在允许范围内'}。"
        if status == "failed":
            return f"{label}执行失败：{result.get('error') or result.get('reason') or '未知错误'}。"
        if status == "executed":
            detail = AutomationOrchestrator._action_result_detail(result.get("result"))
            return f"{label}已执行。{detail}" if detail else f"{label}已执行。"
        return f"{label}状态更新：{status}。"

    @staticmethod
    def _action_result_detail(value: Any) -> str:
        if isinstance(value, dict):
            for key in ("message", "summary", "status", "run_id", "work_id"):
                if value.get(key):
                    return str(value[key])[:240]
            if "date" in value:
                return f"日期 {value['date']}"
            if "score" in value or "target_date" in value:
                parts = []
                if value.get("target_date"):
                    parts.append(f"目标 {value['target_date']}")
                if value.get("status"):
                    parts.append(f"状态 {value['status']}")
                if value.get("score") is not None:
                    parts.append(f"评分 {value['score']}")
                return "，".join(parts)[:240]
        if isinstance(value, str):
            return value[:240]
        return ""

    @classmethod
    def _compact_message_details(cls, value: Any) -> Dict[str, Any]:
        compacted = cls._compact_value(value)
        return compacted if isinstance(compacted, dict) else {"value": compacted}

    @classmethod
    def _compact_value(cls, value: Any, *, depth: int = 0) -> Any:
        if depth >= 3:
            return "..."
        if isinstance(value, dict):
            items = list(value.items())[:12]
            compacted = {str(key): cls._compact_value(val, depth=depth + 1) for key, val in items}
            if len(value) > len(items):
                compacted["_truncated_keys"] = len(value) - len(items)
            return compacted
        if isinstance(value, list):
            items = [cls._compact_value(item, depth=depth + 1) for item in value[:8]]
            if len(value) > len(items):
                items.append({"_truncated_items": len(value) - len(items)})
            return items
        if isinstance(value, str):
            return value if len(value) <= 400 else value[:400] + "..."
        return value

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
            params.setdefault("max_symbols", 500)
            if action_type == "run_factor_lab_backtest":
                params.setdefault("factor", "ml_factor_ranker")
                params.setdefault("initial_capital", 1000000.0)
                params.setdefault("max_positions", 5)
        elif action_type == "run_factor_lab_stress_test":
            params.setdefault("pool", "core")
            params.setdefault("max_symbols", 500)
            params.setdefault("top_n", 5)
            params.setdefault("anchor_date", target_date)
            params.setdefault("factors", ["ml_factor_ranker"])
        elif action_type == "check_data_integrity":
            params.setdefault("target_date", target_date)
            params.setdefault("max_scan", 300)
        elif action_type == "generate_daily_report":
            params.setdefault("target_date", target_date)
        elif action_type == "realtime_snapshot":
            params.setdefault("limit", 6000)
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

    @staticmethod
    def _eod_update_message_body(summary: Dict[str, Any], *, dry_run: bool, status: str) -> str:
        target_date = summary.get("target_date") or summary.get("end_date") or "--"
        a_share = summary.get("a_share") if isinstance(summary.get("a_share"), dict) else {}
        etf = summary.get("etf") if isinstance(summary.get("etf"), dict) else {}
        a_scheduled = a_share.get("scheduled_updates", 0)
        etf_scheduled = etf.get("scheduled_updates", 0)
        mode = "演练" if dry_run else "更新"
        suffix = "未写入数据。" if dry_run else "已写入可获取的数据。"
        return (
            f"{target_date} 数据湖{mode}{status}："
            f"A股计划 {a_scheduled} 个，ETF计划 {etf_scheduled} 个。{suffix}"
        )

    @staticmethod
    def _eod_progress_message_body(freshness: Dict[str, Any]) -> str:
        target_date = freshness.get("target_date") or "--"
        a_share = freshness.get("a_share") if isinstance(freshness.get("a_share"), dict) else {}
        etf = freshness.get("etf") if isinstance(freshness.get("etf"), dict) else {}
        return (
            f"{target_date} 数据湖补数仍在运行：新鲜度 {freshness.get('score', 0)}%，"
            f"A股样本 {a_share.get('fresh_count', 0)}/{a_share.get('checked_count', 0)}，"
            f"ETF样本 {etf.get('fresh_count', 0)}/{etf.get('checked_count', 0)}。"
            "补数完成且完整性检查通过后，模拟盘和 AI cycle 才会继续。"
        )

    @staticmethod
    def _try_akshare_frame(fetcher_name: str) -> Optional[pd.DataFrame]:
        try:
            ak = __import__("akshare")
            fetcher = getattr(ak, fetcher_name, None)
            if not callable(fetcher):
                return None
            frame = fetcher()
            if frame is None or frame.empty:
                return None
            return frame
        except Exception as exc:
            logger.warning("%s snapshot failed: %s", fetcher_name, exc)
            return None

    @staticmethod
    def _to_number(value: Any) -> Optional[float]:
        if value in (None, "", "-"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _normalize_eastmoney_row(cls, row: Dict[str, Any], *, asset_type: str) -> Dict[str, Any]:
        return {
            "代码": str(row.get("f12") or "").strip(),
            "名称": row.get("f14"),
            "最新价": cls._to_number(row.get("f2")),
            "涨跌幅": cls._to_number(row.get("f3")),
            "涨跌额": cls._to_number(row.get("f4")),
            "成交量": cls._to_number(row.get("f5")),
            "成交额": cls._to_number(row.get("f6")),
            "最高": cls._to_number(row.get("f15")),
            "最低": cls._to_number(row.get("f16")),
            "今开": cls._to_number(row.get("f17")),
            "昨收": cls._to_number(row.get("f18")),
            "asset_type": asset_type,
            "source": "eastmoney_direct",
        }

    @classmethod
    def _fetch_eastmoney_clist_snapshot(
        cls,
        *,
        url: str,
        fs: str,
        asset_type: str,
        limit: int,
        page_size: int = 200,
    ) -> List[Dict[str, Any]]:
        request_limit = max(1, min(int(limit or 1), 8000))
        rows: List[Dict[str, Any]] = []
        session = requests.Session()
        session.headers.update(EASTMONEY_HEADERS)
        session.trust_env = False
        try:
            page = 1
            inferred_total_pages: Optional[int] = None
            while len(rows) < request_limit and (inferred_total_pages is None or page <= inferred_total_pages):
                response = session.get(
                    url,
                    params={
                        "pn": str(page),
                        "pz": str(page_size),
                        "po": "1",
                        "np": "1",
                        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                        "fltt": "2",
                        "invt": "2",
                        "fid": "f12",
                        "fs": fs,
                        "fields": EASTMONEY_FIELDS,
                        "wbp2u": "|0|0|0|web",
                    },
                    timeout=15,
                    proxies={"http": None, "https": None},
                )
                response.raise_for_status()
                payload = response.json()
                data = (payload or {}).get("data") or {}
                diff = data.get("diff") or []
                if not diff:
                    break
                per_page = max(1, len(diff))
                total_items = int(data.get("total") or 0)
                if total_items:
                    total_pages_by_data = max(1, (total_items + per_page - 1) // per_page)
                    total_pages_by_limit = max(1, (request_limit + per_page - 1) // per_page)
                    inferred_total_pages = min(total_pages_by_data, total_pages_by_limit)
                rows.extend(
                    cls._normalize_eastmoney_row(item, asset_type=asset_type)
                    for item in diff
                    if isinstance(item, dict)
                )
                if len(rows) >= request_limit or (inferred_total_pages is not None and page >= inferred_total_pages):
                    break
                page += 1
                time.sleep(0.12)
        finally:
            session.close()
        return rows[:request_limit]

    @staticmethod
    def _position_symbols_from_context(context: Dict[str, Any]) -> List[str]:
        virtual_trading = context.get("virtual_trading") if isinstance(context, dict) else {}
        accounts = virtual_trading.get("accounts") if isinstance(virtual_trading, dict) else []
        symbols: List[str] = []
        for account in accounts:
            if not isinstance(account, dict):
                continue
            for holding in account.get("top_holding_details") or []:
                if not isinstance(holding, dict):
                    continue
                symbol = str(holding.get("symbol") or "").strip()
                if symbol:
                    symbols.append(symbol)
        return sorted(set(symbols))

    @staticmethod
    def _eastmoney_secid(symbol: str) -> str:
        normalized = str(symbol or "").strip()
        market = 1 if normalized.startswith(("5", "6", "9", "11", "13")) else 0
        return f"{market}.{normalized}"

    @classmethod
    def _fetch_eastmoney_position_quotes(cls, symbols: List[str]) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        if not symbols:
            return rows
        session = requests.Session()
        session.headers.update(EASTMONEY_HEADERS)
        session.trust_env = False
        try:
            for symbol in symbols:
                response = session.get(
                    EASTMONEY_STOCK_GET_URL,
                    params={
                        "fltt": "2",
                        "invt": "2",
                        "fields": EASTMONEY_QUOTE_FIELDS,
                        "secid": cls._eastmoney_secid(symbol),
                    },
                    timeout=8,
                    proxies={"http": None, "https": None},
                )
                response.raise_for_status()
                data = (response.json() or {}).get("data") or {}
                code = str(data.get("f57") or symbol or "").strip()
                if not code:
                    continue
                rows.append(
                    {
                        "代码": code,
                        "名称": data.get("f58"),
                        "最新价": cls._to_number(data.get("f43")),
                        "涨跌幅": cls._to_number(data.get("f170")),
                        "涨跌额": cls._to_number(data.get("f169")),
                        "成交量": cls._to_number(data.get("f47")),
                        "成交额": cls._to_number(data.get("f48")),
                        "最高": cls._to_number(data.get("f44")),
                        "最低": cls._to_number(data.get("f45")),
                        "今开": cls._to_number(data.get("f46")),
                        "昨收": cls._to_number(data.get("f60")),
                        "换手率": cls._to_number(data.get("f168")),
                        "量比": cls._to_number(data.get("f50")),
                        "外盘": cls._to_number(data.get("f49")),
                        "内盘": cls._to_number(data.get("f161")),
                        "source": "eastmoney_position_quote",
                    }
                )
                time.sleep(0.04)
        finally:
            session.close()
        return rows

    def _supplement_position_quotes(self, rows: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], bool]:
        try:
            position_rows = self._current_position_quote_rows()
        except Exception as exc:
            logger.warning("current position quote collection failed: %s", exc)
            return rows, False
        if not position_rows:
            return rows, False

        existing_symbols = {
            str(row.get("代码") or row.get("symbol") or row.get("code") or "").strip()
            for row in rows
            if isinstance(row, dict)
        }
        supplemental_rows = [
            row
            for row in position_rows
            if str(row.get("代码") or "").strip() and str(row.get("代码") or "").strip() not in existing_symbols
        ]
        if not supplemental_rows:
            return rows, False
        return rows + supplemental_rows, True

    def _current_position_quote_rows(self) -> List[Dict[str, Any]]:
        try:
            context = self.context_builder()
        except Exception as exc:
            logger.warning("context builder failed while collecting position quotes: %s", exc)
            return []

        required_symbols = self._position_symbols_from_context(context)
        if not required_symbols:
            return []

        try:
            return self._fetch_eastmoney_position_quotes(required_symbols)
        except Exception as exc:
            logger.warning("position quote collection failed: %s", exc)
            return []

    def _fetch_market_snapshot(self, *, limit: int) -> tuple[List[Dict[str, Any]], str]:
        limit = max(1, min(int(limit or 6000), 8000))
        position_rows = self._current_position_quote_rows()
        if position_rows:
            cached_getter = getattr(self.data_manager, "get_latest_market_cached", None)
            cached_overview = cached_getter() if callable(cached_getter) else []
            cached_overview = cached_overview or []
            combined = pd.DataFrame(position_rows + list(cached_overview[:20]))
            if "代码" in combined.columns:
                combined = combined.drop_duplicates(subset=["代码"], keep="first")
            if "涨跌幅" in combined.columns:
                combined = combined.sort_values("涨跌幅", ascending=False, na_position="last")
            source = "eastmoney_positions"
            if cached_overview:
                source += "+market_cache"
            return combined.head(limit).to_dict(orient="records"), source

        frames: List[pd.DataFrame] = []
        sources: List[str] = []

        stock_frame = self._try_akshare_frame("stock_zh_a_spot_em")
        if stock_frame is not None:
            frames.append(stock_frame)
            sources.append("akshare_a")
        else:
            try:
                stock_rows = self._fetch_eastmoney_clist_snapshot(
                    url=EASTMONEY_A_SHARE_URL,
                    fs=EASTMONEY_A_SHARE_FS,
                    asset_type="a_share",
                    limit=limit,
                )
                if stock_rows:
                    frames.append(pd.DataFrame(stock_rows))
                    sources.append("eastmoney_a")
            except Exception as exc:
                logger.warning("eastmoney a-share snapshot failed: %s", exc)

        etf_frame = self._try_akshare_frame("fund_etf_spot_em")
        if etf_frame is not None:
            frames.append(etf_frame)
            sources.append("akshare_etf")
        else:
            try:
                etf_rows = self._fetch_eastmoney_clist_snapshot(
                    url=EASTMONEY_ETF_URL,
                    fs=EASTMONEY_ETF_FS,
                    asset_type="etf",
                    limit=limit,
                )
                if etf_rows:
                    frames.append(pd.DataFrame(etf_rows))
                    sources.append("eastmoney_etf")
            except Exception as exc:
                logger.warning("eastmoney etf snapshot failed: %s", exc)

        if frames:
            combined = pd.concat(frames, ignore_index=True, sort=False)
            rows = combined.to_dict(orient="records")
            rows, supplemented = self._supplement_position_quotes(rows)
            combined = pd.DataFrame(rows)
            if "代码" in combined.columns:
                combined = combined.drop_duplicates(subset=["代码"], keep="last")
            if "涨跌幅" in combined.columns:
                combined = combined.sort_values("涨跌幅", ascending=False, na_position="last")
            if supplemented:
                sources.append("eastmoney_positions")
            source = "+".join(sources) if sources else "snapshot_mixed"
            return combined.head(limit).to_dict(orient="records"), source

        rows = self.data_manager.get_latest_market_overview(limit=limit)
        rows, supplemented = self._supplement_position_quotes(list(rows[:limit]))
        if supplemented:
            return rows[:limit], "latest_market_overview+eastmoney_positions"
        return rows[:limit], "latest_market_overview"

    @staticmethod
    def _top_snapshot_rows(rows: List[Dict[str, Any]], *, limit: int) -> List[Dict[str, Any]]:
        top_rows = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            top_rows.append(
                {
                    "symbol": row.get("代码") or row.get("stock_code") or row.get("symbol") or row.get("code"),
                    "name": row.get("名称") or row.get("stock_name") or row.get("name"),
                    "price": row.get("最新价") or row.get("current_price") or row.get("close"),
                    "pct_chg": row.get("涨跌幅") or row.get("pct_chg") or row.get("change_pct"),
                }
            )
        return top_rows

    @classmethod
    def _snapshot_message_body(cls, rows: List[Dict[str, Any]], snapshot: Dict[str, Any]) -> str:
        movers = cls._top_snapshot_rows(rows, limit=3)
        mover_text = "；".join(
            f"{item.get('name') or item.get('symbol')} {item.get('pct_chg')}%"
            for item in movers
            if item.get("symbol") or item.get("name")
        )
        suffix = f" 领涨：{mover_text}。" if mover_text else ""
        return (
            f"已抓取 {snapshot.get('row_count', len(rows))} 条盘中行情，"
            "后续会作为实盘模拟页的盘中估值覆盖层，并进入 AI 汇报上下文；不会写入历史 K 线。"
            f"{suffix}"
        )

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
