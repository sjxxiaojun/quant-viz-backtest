#!/usr/bin/env python3
"""Fast incremental update for quant_data_lake.

Keeps one baostock session per worker process and processes many codes,
avoiding per-stock process spawn + login overhead.
"""
import argparse
import json
import multiprocessing as mp
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd

from lake_paths import resolve_data_lake_dir

BACKEND_DIR = Path(__file__).resolve().parent
ROOT_DIR = resolve_data_lake_dir()
ETF_DIR = ROOT_DIR / "etf"
DATA_CACHE_DIR = BACKEND_DIR / "data_cache"
START_DATE = "2022-01-01"

sys.path.insert(0, str(BACKEND_DIR))

import download_a_share_market as a_share_dl  # noqa: E402
import download_etf_market as etf_dl  # noqa: E402


def disable_proxies() -> None:
    a_share_dl.disable_proxies()


def shift_start(max_date: str, buffer_days: int) -> str:
    shifted = pd.Timestamp(max_date) - pd.Timedelta(days=buffer_days)
    return max(START_DATE, shifted.strftime("%Y-%m-%d"))


def read_max_date(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        dates = pd.read_parquet(path, columns=["date"])
        if dates.empty:
            return None
        return pd.to_datetime(dates["date"]).max().strftime("%Y-%m-%d")
    except Exception:
        return None


def merge_and_save(path: Path, incoming: pd.DataFrame, columns: List[str], code: str) -> int:
    frames = []
    if path.exists():
        existing = pd.read_parquet(path)
        for col in columns:
            if col not in existing.columns:
                existing[col] = pd.NA
        frames.append(existing[columns].copy())
    frames.append(incoming[columns].copy())

    # Align dtypes before concat to avoid parquet int/string conflicts (e.g. is_st)
    for frame in frames:
        for col in ("tradestatus", "is_st", "stock_code", "stock_name"):
            if col in frame.columns:
                frame[col] = frame[col].astype("string")
        for col in ("open", "high", "low", "close", "volume", "amount", "pct_chg", "turn", "pe", "pb", "ps", "pcf"):
            if col in frame.columns:
                frame[col] = pd.to_numeric(frame[col], errors="coerce")

    merged = pd.concat(frames, ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"])
    merged = merged.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")
    merged["stock_code"] = str(code)
    if "stock_name" in incoming.columns and not incoming.empty:
        name = str(incoming["stock_name"].iloc[-1])
        if name and name != "nan":
            merged["stock_name"] = name
    for col in ("tradestatus", "is_st", "stock_code", "stock_name"):
        if col in merged.columns:
            merged[col] = merged[col].astype("string")
    path.parent.mkdir(parents=True, exist_ok=True)
    merged[columns].to_parquet(path, index=False)
    return len(merged)


def build_a_share_tasks(end_date: str, buffer_days: int, limit: int) -> List[dict]:
    tasks = []
    for path in sorted(ROOT_DIR.glob("*_full_history.parquet")):
        code = path.name.split("_")[0]
        if not (len(code) == 6 and code.isdigit()):
            continue
        if code.startswith(etf_dl.ETF_PREFIXES) or code.startswith(a_share_dl.BSE_PREFIXES):
            continue
        if code.startswith(("4", "8")):
            continue
        max_date = read_max_date(path)
        if max_date and max_date >= end_date:
            continue
        start_date = START_DATE if not max_date else shift_start(max_date, buffer_days)
        tasks.append(
            {
                "asset": "a_share",
                "code": code,
                "name": code,
                "start_date": start_date,
                "path": str(path),
            }
        )
    if limit > 0:
        tasks = tasks[:limit]
    return tasks


def build_etf_tasks(end_date: str, buffer_days: int, limit: int) -> List[dict]:
    tasks = []
    for path in sorted(ETF_DIR.glob("*_full_history.parquet")):
        code = path.name.split("_")[0]
        if not code.startswith(etf_dl.ETF_PREFIXES):
            continue
        max_date = read_max_date(path)
        if max_date and max_date >= end_date:
            continue
        start_date = START_DATE if not max_date else shift_start(max_date, buffer_days)
        tasks.append(
            {
                "asset": "etf",
                "code": code,
                "name": code,
                "start_date": start_date,
                "path": str(path),
            }
        )
    if limit > 0:
        tasks = tasks[:limit]
    return tasks


def fetch_a_share_baostock(code: str, name: str, start_date: str, end_date: str) -> pd.DataFrame:
    import baostock as bs

    symbol = a_share_dl.get_bs_symbol(code)
    fields = (
        "date,open,high,low,close,volume,amount,pctChg,turn,"
        "tradestatus,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
    )
    rs = bs.query_history_k_data_plus(
        symbol,
        fields,
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag="2",
    )
    if rs.error_code != "0":
        raise RuntimeError(f"baostock a_share {code}: {rs.error_msg}")
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        raise RuntimeError(f"baostock a_share {code}: empty")

    real_name = name
    rs_name = bs.query_stock_basic(code=symbol)
    if rs_name.error_code == "0" and rs_name.next():
        basic_row = rs_name.get_row_data()
        if len(basic_row) > 1 and basic_row[1]:
            real_name = basic_row[1]

    df = pd.DataFrame(rows, columns=rs.fields)
    return a_share_dl.normalize_baostock_df(df, code, real_name)


def fetch_etf_baostock(code: str, name: str, start_date: str, end_date: str) -> pd.DataFrame:
    import baostock as bs

    # Match download_etf_market.fetch_with_baostock field set
    symbol = f"{etf_dl.infer_exchange(code)}.{code}"
    fields = (
        "date,open,high,low,close,volume,amount,pctChg,turn,"
        "tradestatus,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
    )
    rs = bs.query_history_k_data_plus(
        symbol,
        fields,
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag="2",
    )
    if rs.error_code != "0":
        raise RuntimeError(f"baostock etf {code}: {rs.error_msg}")
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        raise RuntimeError(f"baostock etf {code}: empty")

    real_name = name
    rs_name = bs.query_stock_basic(code=symbol)
    if rs_name.error_code == "0" and rs_name.next():
        row = rs_name.get_row_data()
        if len(row) > 1 and row[1]:
            real_name = row[1]

    df = pd.DataFrame(rows, columns=rs.fields)
    return etf_dl.normalize_baostock_df(df, code, real_name)


def worker_main(task_queue: mp.Queue, result_queue: mp.Queue, end_date: str, retry: int) -> None:
    disable_proxies()
    import baostock as bs

    lg = bs.login()
    if lg.error_code != "0":
        result_queue.put({"type": "fatal", "error": f"baostock login failed: {lg.error_msg}"})
        return

    try:
        while True:
            task = task_queue.get()
            if task is None:
                break
            code = task["code"]
            asset = task["asset"]
            path = Path(task["path"])
            errors = []
            ok = False
            source = None
            rows = 0
            for attempt in range(1, retry + 1):
                try:
                    if asset == "a_share":
                        fetched = fetch_a_share_baostock(code, task["name"], task["start_date"], end_date)
                        columns = a_share_dl.STANDARD_COLUMNS
                    else:
                        fetched = fetch_etf_baostock(code, task["name"], task["start_date"], end_date)
                        columns = etf_dl.STANDARD_COLUMNS
                    rows = merge_and_save(path, fetched, columns, code)
                    ok = True
                    source = "baostock"
                    break
                except Exception as exc:
                    errors.append(f"baostock#{attempt}:{exc}")
                    time.sleep(0.5 * attempt)
                    # re-login once if session dies
                    try:
                        bs.logout()
                    except Exception:
                        pass
                    lg = bs.login()
                    if lg.error_code != "0":
                        errors.append(f"relogin:{lg.error_msg}")

            if not ok and asset == "a_share":
                for attempt in range(1, retry + 1):
                    try:
                        fetched = a_share_dl.fetch_with_akshare(code, task["name"], task["start_date"], end_date)
                        rows = merge_and_save(path, fetched, a_share_dl.STANDARD_COLUMNS, code)
                        ok = True
                        source = "akshare"
                        break
                    except Exception as exc:
                        errors.append(f"akshare#{attempt}:{exc}")
                        time.sleep(0.5 * attempt)

            if not ok and asset == "etf":
                for attempt in range(1, retry + 1):
                    try:
                        # prefer sina/akshare path if available
                        if hasattr(etf_dl, "fetch_with_akshare"):
                            fetched = etf_dl.fetch_with_akshare(code, task["name"], task["start_date"], end_date)
                        elif hasattr(etf_dl, "fetch_with_sina"):
                            fetched = etf_dl.fetch_with_sina(code, task["name"], task["start_date"], end_date)
                        else:
                            raise RuntimeError("no etf fallback fetcher")
                        rows = merge_and_save(path, fetched, etf_dl.STANDARD_COLUMNS, code)
                        ok = True
                        source = "akshare"
                        break
                    except Exception as exc:
                        errors.append(f"etf_fallback#{attempt}:{exc}")
                        time.sleep(0.5 * attempt)

            result_queue.put(
                {
                    "type": "result",
                    "code": code,
                    "asset": asset,
                    "status": "success" if ok else "failed",
                    "source": source,
                    "rows": rows,
                    "error": " | ".join(errors) if errors else "",
                }
            )
    except Exception:
        result_queue.put({"type": "fatal", "error": traceback.format_exc()})
    finally:
        try:
            bs.logout()
        except Exception:
            pass


def run_pool(tasks: List[dict], workers: int, end_date: str, retry: int) -> List[dict]:
    if not tasks:
        return []
    ctx = mp.get_context("spawn")
    task_queue: mp.Queue = ctx.Queue()
    result_queue: mp.Queue = ctx.Queue()
    for task in tasks:
        task_queue.put(task)
    for _ in range(workers):
        task_queue.put(None)

    procs = [
        ctx.Process(target=worker_main, args=(task_queue, result_queue, end_date, retry))
        for _ in range(workers)
    ]
    for p in procs:
        p.start()

    results = []
    total = len(tasks)
    done = 0
    success = 0
    failed = 0
    t0 = time.time()
    while done < total:
        try:
            item = result_queue.get(timeout=120)
        except Exception:
            alive = sum(1 for p in procs if p.is_alive())
            if alive == 0:
                break
            print(f"waiting... done={done}/{total} alive_workers={alive}", flush=True)
            continue
        if item.get("type") == "fatal":
            print(f"worker fatal: {item.get('error')}", flush=True)
            continue
        results.append(item)
        done += 1
        if item["status"] == "success":
            success += 1
        else:
            failed += 1
        if done == 1 or done % 50 == 0 or item["status"] == "failed" or done == total:
            rate = done / max(time.time() - t0, 1e-6)
            eta = (total - done) / max(rate, 1e-6)
            print(
                f"[{done}/{total}] {item['asset']}:{item['code']} {item['status']} "
                f"via {item.get('source') or '-'} ok={success} fail={failed} "
                f"rate={rate:.2f}/s eta={eta/60:.1f}m",
                flush=True,
            )

    for p in procs:
        p.join(timeout=10)
        if p.is_alive():
            p.terminate()
    return results


def consolidate() -> str:
    try:
        from scripts.consolidate_lake import consolidate_lake

        consolidate_lake(lake_dir=str(ROOT_DIR), output_dir=str(ROOT_DIR / "consolidated"))
        return "success"
    except Exception as exc:
        return f"error: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Fast incremental quant_data_lake update")
    parser.add_argument(
        "--end-date",
        default=(pd.Timestamp.today().normalize() - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    parser.add_argument("--buffer-days", type=int, default=7)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--retry", type=int, default=3)
    parser.add_argument("--limit-a-share", type=int, default=0)
    parser.add_argument("--limit-etf", type=int, default=0)
    parser.add_argument("--skip-a-share", action="store_true")
    parser.add_argument("--skip-etf", action="store_true")
    parser.add_argument("--skip-consolidate", action="store_true")
    args = parser.parse_args()

    disable_proxies()
    DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    a_tasks = [] if args.skip_a_share else build_a_share_tasks(args.end_date, args.buffer_days, args.limit_a_share)
    e_tasks = [] if args.skip_etf else build_etf_tasks(args.end_date, args.buffer_days, args.limit_etf)
    print(
        f"end_date={args.end_date} a_share_tasks={len(a_tasks)} etf_tasks={len(e_tasks)} workers={args.workers}",
        flush=True,
    )

    t0 = time.time()
    a_results = run_pool(a_tasks, args.workers, args.end_date, args.retry)
    e_results = run_pool(e_tasks, max(4, args.workers // 2), args.end_date, args.retry)
    elapsed = round(time.time() - t0, 2)

    consolidated = "skipped" if args.skip_consolidate else consolidate()
    summary = {
        "timestamp": timestamp,
        "end_date": args.end_date,
        "elapsed_seconds": elapsed,
        "a_share": {
            "scheduled": len(a_tasks),
            "success": sum(1 for r in a_results if r["status"] == "success"),
            "failed": sum(1 for r in a_results if r["status"] == "failed"),
        },
        "etf": {
            "scheduled": len(e_tasks),
            "success": sum(1 for r in e_results if r["status"] == "success"),
            "failed": sum(1 for r in e_results if r["status"] == "failed"),
        },
        "consolidated": consolidated,
    }
    failed_rows = [r for r in a_results + e_results if r["status"] == "failed"]
    failed_path = DATA_CACHE_DIR / f"fast_update_failed_{timestamp}.json"
    summary_path = DATA_CACHE_DIR / f"fast_update_summary_{timestamp}.json"
    failed_path.write_text(json.dumps(failed_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["failed_json"] = str(failed_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(f"summary_json={summary_path}", flush=True)


if __name__ == "__main__":
    # macOS spawn safety
    mp.set_start_method("spawn", force=True)
    main()
