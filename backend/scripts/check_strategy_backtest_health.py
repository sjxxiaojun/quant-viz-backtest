#!/usr/bin/env python3
"""
Run a lightweight backtest for every strategy in STRATEGY_REGISTRY.

Supports:
- health check (pass/fail)
- ranking by total_return

Notes:
- This script calls backend in-process (main.execute_backtest), not via HTTP.
- It is capped by BACKTEST_SEMAPHORE inside execute_backtest.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import HTTPException

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import main
from factor_lab.strategy import FactorLabScoringError, get_factor_lab_artifact_readiness


@dataclass
class CheckResult:
    factor: str
    status: str
    trade_count: int = 0
    total_return: float = 0.0
    final_value: float | None = None
    symbols_count: int = 0
    buy_fills: int = 0
    artifact_status: str | None = None
    error_type: str | None = None
    error: str | None = None


def run_check(
    start_date: str,
    end_date: str,
    *,
    pool: str,
    max_symbols: int,
    initial_capital: float,
    allow_mock: bool,
    commission_rate: float,
    stamp_tax_rate: float,
    slippage_rate: float,
    commission_min: float,
    strict_artifacts: bool,
) -> List[CheckResult]:
    results: List[CheckResult] = []
    for factor in sorted(main.STRATEGY_REGISTRY.keys()):
        spec = main.STRATEGY_REGISTRY[factor]
        if getattr(spec, "requires_artifact", False):
            readiness = get_factor_lab_artifact_readiness(main.FACTOR_LAB_REPORT_DIR)
            if not readiness.get("ready") and not strict_artifacts:
                results.append(
                    CheckResult(
                        factor=factor,
                        status="skipped_prereq",
                        artifact_status=str(readiness.get("status") or "unknown"),
                        error_type="FactorLabArtifactNotReady",
                        error=str(readiness.get("message") or "Factor Lab artifact is not ready."),
                    )
                )
                continue
        req = main.BacktestRequest(
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            factor=factor,
            pool=pool,
            max_symbols=max_symbols,
            max_positions=5,
            weight_mode="equal",
            stop_loss=-0.08,
            commission_rate=commission_rate,
            stamp_tax_rate=stamp_tax_rate,
            slippage_rate=slippage_rate,
            commission_min=commission_min,
            allow_mock=allow_mock,
        )
        try:
            payload = main.execute_backtest(req, allow_mock=allow_mock)
            trades = payload.get("trades") or []
            total_return = float(payload.get("total_return", 0.0))
            final_value = None
            if isinstance(payload.get("summary"), dict):
                try:
                    final_value = float(payload["summary"].get("final_value"))
                except Exception:
                    final_value = None
            symbols_count = int(
                (payload.get("resolved_pool") or {}).get("symbols_count")
                or 0
            )
            buy_fills = int(
                ((payload.get("summary") or {}).get("execution_stats") or {}).get("buy_fills")
                or 0
            )
            results.append(
                CheckResult(
                    factor=factor,
                    status="passed",
                    trade_count=len(trades),
                    total_return=total_return,
                    final_value=final_value,
                    symbols_count=symbols_count,
                    buy_fills=buy_fills,
                )
            )
        except HTTPException as exc:
            results.append(
                CheckResult(
                    factor=factor,
                    status="failed",
                    error_type="HTTPException",
                    error=f"{exc.status_code}: {exc.detail}",
                )
            )
        except FactorLabScoringError as exc:
            results.append(
                CheckResult(
                    factor=factor,
                    status="failed" if strict_artifacts else "skipped_prereq",
                    artifact_status="not_ready",
                    error_type="FactorLabScoringError",
                    error=str(exc),
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CheckResult(
                    factor=factor,
                    status="failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
            )
    return results


def summarize(results: List[CheckResult]) -> dict:
    total = len(results)
    passed = sum(1 for r in results if r.status == "passed")
    skipped_prereq = sum(1 for r in results if r.status == "skipped_prereq")
    failed = total - passed - skipped_prereq
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total": total,
        "passed": passed,
        "skipped_prereq": skipped_prereq,
        "failed": failed,
        "pass_rate": (passed / total) if total else 0.0,
    }


def main_cli() -> int:
    parser = argparse.ArgumentParser(description="Check all strategy backtest health.")
    parser.add_argument("--start-date", default="2025-10-01")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument("--pool", default="all", choices=["auto", "core", "blackhorse", "all", "etf"])
    parser.add_argument("--max-symbols", type=int, default=40)
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0)
    parser.add_argument("--commission-rate", type=float, default=0.0003)
    parser.add_argument("--stamp-tax-rate", type=float, default=0.001)
    parser.add_argument("--slippage-rate", type=float, default=0.0003)
    parser.add_argument("--commission-min", type=float, default=5.0)
    parser.add_argument("--allow-mock", action="store_true", help="Allow fallback mock data when real data missing.")
    parser.add_argument("--json", action="store_true", help="Output JSON report.")
    parser.add_argument("--rank", action="store_true", help="Print ranking by total_return (desc).")
    parser.add_argument("--show-traceback", action="store_true", help="Show traceback when script errors.")
    parser.add_argument("--strict-artifacts", action="store_true", help="Fail ML artifact prerequisites instead of skipping them.")
    args = parser.parse_args()

    try:
        results = run_check(
            args.start_date,
            args.end_date,
            pool=args.pool,
            max_symbols=args.max_symbols,
            initial_capital=args.initial_capital,
            allow_mock=args.allow_mock,
            commission_rate=args.commission_rate,
            stamp_tax_rate=args.stamp_tax_rate,
            slippage_rate=args.slippage_rate,
            commission_min=args.commission_min,
            strict_artifacts=args.strict_artifacts,
        )
        summary = summarize(results)
        report = {
            "summary": summary,
            "params": {
                "start_date": args.start_date,
                "end_date": args.end_date,
                "pool": args.pool,
                "max_symbols": args.max_symbols,
                "initial_capital": args.initial_capital,
                "commission_rate": args.commission_rate,
                "stamp_tax_rate": args.stamp_tax_rate,
                "slippage_rate": args.slippage_rate,
                "commission_min": args.commission_min,
                "allow_mock": bool(args.allow_mock),
            },
            "results": [asdict(r) for r in results],
        }
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0

        print(
            f"[strategy-health] total={summary['total']} passed={summary['passed']} "
            f"skipped_prereq={summary['skipped_prereq']} failed={summary['failed']} "
            f"pass_rate={summary['pass_rate']:.2%}"
        )
        if args.rank:
            ranked = [r for r in results if r.status == "passed"]
            ranked.sort(key=lambda r: r.total_return, reverse=True)
            print("\n[strategy-rank] by total_return (desc)")
            for idx, r in enumerate(ranked, 1):
                fv = f"{r.final_value:.2f}" if r.final_value is not None else "NA"
                print(
                    f"{idx:2d}. {r.factor:24s} total_return={r.total_return:+.4f} "
                    f"trades={r.trade_count:4d} final_value={fv} symbols={r.symbols_count:4d} buys={r.buy_fills:4d}"
                )
            if summary["failed"]:
                print("\n[strategy-rank] some strategies failed; see FAIL lines below.")
        for r in results:
            if r.status == "passed":
                print(f"PASS {r.factor:24s} trades={r.trade_count:4d} total_return={r.total_return:.4f}")
            elif r.status == "skipped_prereq":
                print(f"SKIP {r.factor:24s} {r.error_type}: {r.error}")
            else:
                print(f"FAIL {r.factor:24s} {r.error_type}: {r.error}")
        return 0 if summary["failed"] == 0 else 1
    except Exception:  # noqa: BLE001
        if args.show_traceback:
            traceback.print_exc()
        else:
            print("Health check script failed. Re-run with --show-traceback for details.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main_cli())
