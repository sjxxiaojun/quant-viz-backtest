from __future__ import annotations

import argparse
import contextlib
import io
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

import pandas as pd

from data_manager import DataManager
from daily_update_quant_data_lake import run_daily_update


logger = logging.getLogger("DataLakeUpdateService")


class DataLakeUpdateService:
    def __init__(self, data_manager: DataManager):
        self.data_manager = data_manager

    def default_target_date(self) -> str:
        return self.data_manager.get_last_trading_day()

    def build_args(
        self,
        *,
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
    ) -> argparse.Namespace:
        return argparse.Namespace(
            end_date=target_date or self.default_target_date(),
            buffer_days=buffer_days,
            workers_a_share=workers_a_share,
            workers_etf=workers_etf,
            retry=retry,
            task_timeout=task_timeout,
            limit_a_share=limit_a_share,
            limit_etf=limit_etf,
            skip_a_share=skip_a_share,
            skip_etf=skip_etf,
            dry_run=dry_run,
        )

    def run_update(self, **kwargs) -> Dict[str, object]:
        args = self.build_args(**kwargs)
        sink = io.StringIO()
        started_at = datetime.now()
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            summary = run_daily_update(args)
        output = sink.getvalue().strip()
        if output:
            logger.info("daily update output:\n%s", output[-4000:])
        summary["target_date"] = args.end_date
        summary["started_at"] = started_at.isoformat(timespec="seconds")
        summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
        summary["captured_output_tail"] = output[-4000:]
        return summary

    def data_freshness(self, *, target_date: Optional[str] = None, max_scan: int = 500) -> Dict[str, object]:
        target_date = target_date or self.default_target_date()
        max_scan = max(1, int(max_scan or 500))
        a_share = self._asset_freshness("a_share", target_date, max_scan)
        etf = self._asset_freshness("etf", target_date, max_scan)
        coverage = [item["coverage_ratio"] for item in (a_share, etf) if item["checked_count"] > 0]
        avg_coverage = sum(coverage) / len(coverage) if coverage else 0.0
        status = "ready" if avg_coverage >= 0.98 else "degraded" if avg_coverage >= 0.75 else "blocked"
        return {
            "target_date": target_date,
            "status": status,
            "score": round(avg_coverage * 100, 2),
            "sampled": True,
            "max_scan": max_scan,
            "a_share": a_share,
            "etf": etf,
        }

    def is_trade_day(self, day: Optional[datetime] = None) -> bool:
        day = day or datetime.now()
        if day.weekday() >= 5:
            return False
        try:
            prev = day - timedelta(days=7)
            calendar = self.data_manager._market_trading_calendar(
                pd.Timestamp(prev.date()),
                pd.Timestamp(day.date()),
            )
            if len(calendar) > 0:
                return pd.Timestamp(day.date()).normalize() in {d.normalize() for d in calendar}
        except Exception:
            pass
        return True

    def _asset_freshness(self, asset_type: str, target_date: str, max_scan: int) -> Dict[str, object]:
        symbols = self.data_manager.list_local_codes(asset_type)
        checked = symbols[:max_scan]
        fresh = 0
        stale = []
        missing = 0
        latest_date = None
        for symbol in checked:
            path = self.data_manager.get_cache_path(symbol)
            if not path.exists():
                missing += 1
                stale.append({"symbol": symbol, "max_date": None})
                continue
            try:
                df = pd.read_parquet(path, columns=["date"])
                if df.empty:
                    missing += 1
                    stale.append({"symbol": symbol, "max_date": None})
                    continue
                max_date = str(pd.to_datetime(df["date"], errors="coerce").dropna().max().date())
                latest_date = max(max_date, latest_date or max_date)
                if max_date >= target_date:
                    fresh += 1
                elif len(stale) < 10:
                    stale.append({"symbol": symbol, "max_date": max_date})
            except Exception as exc:
                missing += 1
                if len(stale) < 10:
                    stale.append({"symbol": symbol, "max_date": None, "error": str(exc)})
        checked_count = len(checked)
        return {
            "asset_type": asset_type,
            "total_local": len(symbols),
            "checked_count": checked_count,
            "fresh_count": fresh,
            "missing_or_error_count": missing,
            "stale_count": max(0, checked_count - fresh),
            "coverage_ratio": (fresh / checked_count) if checked_count else 0.0,
            "latest_date_seen": latest_date,
            "stale_examples": stale[:10],
        }
