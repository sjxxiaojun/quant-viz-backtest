import argparse
import contextlib
import csv
import io
import json
import multiprocessing as mp
import queue as queue_mod
import sys
import time
import warnings
from datetime import datetime
from functools import partial
from pathlib import Path

import pandas as pd


BACKEND_DIR = Path("/Users/gdxj/quant-viz-backtest/backend")
ROOT_DIR = Path("/Users/gdxj/quant_data_lake")
DATA_CACHE_DIR = BACKEND_DIR / "data_cache"
START_DATE = "2022-01-01"

sys.path.insert(0, str(BACKEND_DIR))

import download_a_share_market as a_share_dl  # noqa: E402
import download_etf_market as etf_dl  # noqa: E402
import repair_quant_data_lake as repair  # noqa: E402


warnings.filterwarnings("ignore", category=FutureWarning, message="The behavior of DataFrame concatenation")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按现有目录结构做 quant_data_lake 日常增量更新")
    parser.add_argument(
        "--end-date",
        default=(pd.Timestamp.today().normalize() - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    parser.add_argument("--buffer-days", type=int, default=7)
    parser.add_argument("--workers-a-share", type=int, default=6)
    parser.add_argument("--workers-etf", type=int, default=4)
    parser.add_argument("--retry", type=int, default=3)
    parser.add_argument("--task-timeout", type=int, default=90)
    parser.add_argument("--limit-a-share", type=int, default=0)
    parser.add_argument("--limit-etf", type=int, default=0)
    parser.add_argument("--skip-a-share", action="store_true")
    parser.add_argument("--skip-etf", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def ensure_dirs() -> None:
    repair.ensure_dirs()


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def standardize_frame(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    frame = df.copy()
    for col in columns:
        if col not in frame.columns:
            frame[col] = pd.NA
    frame = frame[columns].copy()
    frame["date"] = pd.to_datetime(frame["date"]).dt.strftime("%Y-%m-%d")
    for col in ("tradestatus", "is_st", "stock_code", "stock_name"):
        if col in frame.columns:
            frame[col] = frame[col].astype("string")
    return frame


def merge_frames(existing_path: Path, incoming_df: pd.DataFrame, columns: list[str], code: str, name: str) -> pd.DataFrame:
    frames = []
    if existing_path.exists():
        frames.append(standardize_frame(pd.read_parquet(existing_path), columns))
    frames.append(standardize_frame(incoming_df, columns))

    merged = pd.concat(frames, ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"])
    merged = merged.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    merged["date"] = merged["date"].dt.strftime("%Y-%m-%d")
    merged["stock_code"] = code
    if name:
        merged["stock_name"] = name
    return merged[columns].reset_index(drop=True)


def quiet_call(fetcher):
    sink = io.StringIO()
    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        return fetcher()


def shift_start_date(end_date: str, buffer_days: int) -> str:
    shifted = pd.Timestamp(end_date) - pd.Timedelta(days=buffer_days)
    return max(START_DATE, shifted.strftime("%Y-%m-%d"))


def move_root_etfs_to_subdir() -> int:
    moved = 0
    for path in sorted(ROOT_DIR.glob("*_full_history.parquet")):
        code = path.name.split("_")[0]
        if not code.startswith(etf_dl.ETF_PREFIXES):
            continue

        dest = repair.ETF_DIR / path.name
        if dest.exists():
            merged = merge_frames(
                existing_path=dest,
                incoming_df=pd.read_parquet(path),
                columns=etf_dl.STANDARD_COLUMNS,
                code=code,
                name=str(pd.read_parquet(path, columns=["stock_name"]).iloc[-1, 0]),
            )
            merged.to_parquet(dest, index=False)
            path.unlink()
        else:
            repair.move_file(path, repair.ETF_DIR)
        moved += 1
    return moved


def load_local_a_share_universe() -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for path in sorted(ROOT_DIR.glob("*_full_history.parquet")):
        code = path.name.split("_")[0]
        if not (len(code) == 6 and code.isdigit()):
            continue
        if code.startswith(etf_dl.ETF_PREFIXES) or code.startswith(a_share_dl.BSE_PREFIXES) or code.startswith(("4", "8")):
            continue
        market = "SH" if code.startswith("6") else "SZ"
        rows.append({"code": code, "name": code, "market": market})

    universe_all = pd.DataFrame(rows, columns=["code", "name", "market"])
    if universe_all.empty:
        return universe_all, universe_all.copy()
    universe_all = universe_all.sort_values(["market", "code"]).reset_index(drop=True)
    clean_universe = universe_all[~universe_all["name"].map(repair.is_st_or_delisted_name)].copy()
    clean_universe = clean_universe.sort_values(["market", "code"]).reset_index(drop=True)
    return universe_all, clean_universe


def build_a_share_tasks(end_date: str, buffer_days: int, limit: int, dry_run: bool) -> tuple[pd.DataFrame, list[dict], dict]:
    universe_source = "local"
    universe_all, clean_universe = load_local_a_share_universe()
    if universe_all.empty:
        universe_source = "online"
        universe_all, clean_universe = repair.load_universe()
    if dry_run:
        audit = {
            "moved_counts": {"etf": 0, "st_delisted": 0, "non_universe": 0, "bj": 0},
        }
    elif universe_source == "local":
        audit = {
            "moved_counts": {"etf": move_root_etfs_to_subdir(), "st_delisted": 0, "non_universe": 0, "bj": 0},
        }
    else:
        move_root_etfs_to_subdir()
        audit = repair.audit_and_reorganize(set(universe_all["code"]), set(clean_universe["code"]), end_date)

    tasks = []
    for row in clean_universe.itertuples(index=False):
        path = ROOT_DIR / f"{row.code}_full_history.parquet"
        if not path.exists():
            tasks.append(
                {
                    "code": row.code,
                    "name": row.name,
                    "market": row.market,
                    "start_date": START_DATE,
                    "reason": "missing",
                }
            )
            continue

        schema_ok = repair.read_schema_columns(path) == a_share_dl.STANDARD_COLUMNS
        meta = repair.read_file_meta(path)
        placeholder_name = not meta["latest_name"] or meta["latest_name"] == row.code
        if schema_ok and not placeholder_name and meta["max_date"] >= end_date:
            continue

        tasks.append(
            {
                "code": row.code,
                "name": row.name,
                "market": row.market,
                "start_date": START_DATE if not schema_ok else shift_start_date(meta["max_date"], buffer_days),
                "reason": "schema" if not schema_ok else ("name" if placeholder_name else "stale"),
            }
        )

    if limit > 0:
        tasks = tasks[:limit]

    summary = {
        "universe_source": universe_source,
        "universe_all_count": int(len(universe_all)),
        "clean_universe_count": int(len(clean_universe)),
        "excluded_st_from_universe": int(len(universe_all) - len(clean_universe)),
        "audit_moved_counts": audit["moved_counts"],
    }
    return clean_universe, tasks, summary


def build_etf_tasks(end_date: str, buffer_days: int, limit: int) -> tuple[pd.DataFrame, list[dict]]:
    etf_dl.disable_proxies()
    universe = load_local_etf_universe()
    universe_source = "local"
    if universe.empty:
        universe = etf_dl.load_etf_universe()
        universe_source = "online"
    universe.attrs["source"] = universe_source
    tasks = []
    for row in universe.itertuples(index=False):
        path = repair.ETF_DIR / f"{row.code}_full_history.parquet"
        if not path.exists():
            tasks.append(
                {
                    "code": row.code,
                    "name": row.name,
                    "start_date": START_DATE,
                    "reason": "missing",
                }
            )
            continue

        df = pd.read_parquet(path, columns=["date"])
        max_date = pd.to_datetime(df["date"]).max().strftime("%Y-%m-%d")
        if max_date >= end_date:
            continue

        tasks.append(
            {
                "code": row.code,
                "name": row.name,
                "start_date": shift_start_date(max_date, buffer_days),
                "reason": "stale",
            }
        )

    if limit > 0:
        tasks = tasks[:limit]
    return universe, tasks


def load_local_etf_universe() -> pd.DataFrame:
    rows = []
    for path in sorted(repair.ETF_DIR.glob("*_full_history.parquet")):
        code = path.name.split("_")[0]
        if not code.startswith(etf_dl.ETF_PREFIXES):
            continue
        rows.append({"code": code, "name": code, "fund_type": "local"})
    return pd.DataFrame(rows, columns=["code", "name", "fund_type"])


def fetch_a_share_task(task: dict, end_date: str, retry: int, task_timeout: int) -> dict:
    code = task["code"]
    name = task["name"]
    market = task["market"]
    path = ROOT_DIR / f"{code}_full_history.parquet"
    errors = []

    for source in ("baostock", "akshare"):
        for attempt in range(1, retry + 1):
            try:
                with a_share_dl.time_limit(task_timeout):
                    if source == "baostock":
                        fetched = quiet_call(lambda: a_share_dl.fetch_with_baostock(code, name, task["start_date"], end_date))
                    else:
                        fetched = quiet_call(lambda: a_share_dl.fetch_with_akshare(code, name, task["start_date"], end_date))
                merged = merge_frames(path, fetched, a_share_dl.STANDARD_COLUMNS, code, str(fetched["stock_name"].iloc[-1]))
                merged.to_parquet(path, index=False)
                return {
                    "code": code,
                    "name": name,
                    "market": market,
                    "status": "success",
                    "source": source,
                    "reason": task["reason"],
                    "rows": int(len(merged)),
                    "start_date": str(merged["date"].min()),
                    "end_date": str(merged["date"].max()),
                    "error": "",
                }
            except Exception as exc:
                errors.append(f"{source} attempt {attempt}/{retry}: {exc}")
                time.sleep([1, 3, 8][min(attempt - 1, 2)])

    return {
        "code": code,
        "name": name,
        "market": market,
        "status": "failed",
        "source": "",
        "reason": task["reason"],
        "rows": 0,
        "start_date": "",
        "end_date": "",
        "error": " | ".join(errors),
    }


def fetch_etf_task(task: dict, end_date: str, retry: int, task_timeout: int) -> dict:
    code = task["code"]
    name = task["name"]
    path = repair.ETF_DIR / f"{code}_full_history.parquet"
    errors = []

    for source in ("sina", "baostock"):
        for attempt in range(1, retry + 1):
            try:
                with etf_dl.time_limit(task_timeout):
                    if source == "sina":
                        fetched = quiet_call(lambda: etf_dl.fetch_with_sina(code, name, task["start_date"]))
                    else:
                        fetched = quiet_call(lambda: etf_dl.fetch_with_baostock(code, name, task["start_date"], end_date))
                merged = merge_frames(path, fetched, etf_dl.STANDARD_COLUMNS, code, str(fetched["stock_name"].iloc[-1]))
                max_date = pd.to_datetime(merged["date"], errors="coerce").dropna().max().strftime("%Y-%m-%d")
                if max_date < end_date:
                    raise ValueError(f"{source} returned stale ETF data through {max_date}, expected {end_date}")
                merged.to_parquet(path, index=False)
                return {
                    "code": code,
                    "name": name,
                    "status": "success",
                    "source": source,
                    "reason": task["reason"],
                    "rows": int(len(merged)),
                    "start_date": str(merged["date"].min()),
                    "end_date": max_date,
                    "error": "",
                }
            except Exception as exc:
                errors.append(f"{source} attempt {attempt}/{retry}: {exc}")
                time.sleep([1, 3, 8][min(attempt - 1, 2)])

    return {
        "code": code,
        "name": name,
        "status": "failed",
        "source": "",
        "reason": task["reason"],
        "rows": 0,
        "start_date": "",
        "end_date": "",
        "error": " | ".join(errors),
    }


def failed_task_result(task: dict, error: str) -> dict:
    result = {
        "code": task.get("code", ""),
        "name": task.get("name", ""),
        "status": "failed",
        "source": "",
        "reason": task.get("reason", ""),
        "rows": 0,
        "start_date": "",
        "end_date": "",
        "error": error,
    }
    if "market" in task:
        result["market"] = task.get("market", "")
    return result


def task_process_entry(worker, task: dict, result_queue) -> None:
    try:
        result = worker(task)
    except Exception as exc:
        result = failed_task_result(task, str(exc))
    result_queue.put(result)


def print_pool_progress(done: int, total: int, result: dict) -> None:
    if done == 1 or done % 25 == 0 or result["status"] == "failed":
        print(
            f"[{done}/{total}] {result['code']} {result['status']} "
            f"via {result.get('source') or '-'} reason={result.get('reason') or '-'} rows={result.get('rows') or 0}",
            flush=True,
        )


def run_pool(tasks: list[dict], worker, max_workers: int, hard_timeout: int = 0) -> list[dict]:
    results = []
    if not tasks:
        return results

    ctx = mp.get_context("spawn")
    result_queue = ctx.Queue()
    pending = iter(tasks)
    active: dict[str, tuple[mp.Process, dict, float]] = {}
    total = len(tasks)
    max_workers = max(1, int(max_workers or 1))
    hard_timeout = max(0, int(hard_timeout or 0))

    def start_next() -> bool:
        try:
            task = next(pending)
        except StopIteration:
            return False
        process = ctx.Process(target=task_process_entry, args=(worker, task, result_queue))
        process.start()
        active[task["code"]] = (process, task, time.monotonic())
        return True

    for _ in range(min(max_workers, total)):
        start_next()

    while active:
        made_progress = False
        while True:
            try:
                result = result_queue.get_nowait()
            except queue_mod.Empty:
                break
            code = result.get("code", "")
            process_info = active.pop(code, None)
            if not process_info:
                continue
            process_info[0].join(timeout=1)
            results.append(result)
            print_pool_progress(len(results), total, result)
            start_next()
            made_progress = True

        now = time.monotonic()
        for code, (process, task, started_at) in list(active.items()):
            if process.is_alive():
                if hard_timeout and now - started_at > hard_timeout:
                    process.terminate()
                    process.join(timeout=3)
                    active.pop(code, None)
                    result = failed_task_result(task, f"task exceeded hard timeout {hard_timeout}s")
                    results.append(result)
                    print_pool_progress(len(results), total, result)
                    start_next()
                    made_progress = True
                continue

            process.join(timeout=1)
            active.pop(code, None)
            result = failed_task_result(task, f"worker exited without result (exitcode={process.exitcode})")
            results.append(result)
            print_pool_progress(len(results), total, result)
            start_next()
            made_progress = True

        if not made_progress:
            time.sleep(0.2)
    return results


def run_daily_update(args: argparse.Namespace) -> dict:
    ensure_dirs()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if getattr(args, "skip_a_share", False):
        clean_universe = pd.DataFrame(columns=["code", "name", "market"])
        a_share_tasks = []
        a_share_prep = {
            "universe_source": "skipped",
            "universe_all_count": 0,
            "clean_universe_count": 0,
            "excluded_st_from_universe": 0,
            "audit_moved_counts": {"etf": 0, "st_delisted": 0, "non_universe": 0, "bj": 0},
        }
    else:
        clean_universe, a_share_tasks, a_share_prep = build_a_share_tasks(
            end_date=args.end_date,
            buffer_days=args.buffer_days,
            limit=args.limit_a_share,
            dry_run=args.dry_run,
        )

    if getattr(args, "skip_etf", False):
        etf_universe = pd.DataFrame(columns=["code", "name", "fund_type"])
        etf_universe.attrs["source"] = "skipped"
        etf_tasks = []
    else:
        etf_universe, etf_tasks = build_etf_tasks(
            end_date=args.end_date,
            buffer_days=args.buffer_days,
            limit=args.limit_etf,
        )

    summary = {
        "timestamp": timestamp,
        "end_date": args.end_date,
        "buffer_days": args.buffer_days,
        "dry_run": args.dry_run,
        "a_share": {
            **a_share_prep,
            "scheduled_updates": len(a_share_tasks),
            "scheduled_by_reason": pd.Series([t["reason"] for t in a_share_tasks]).value_counts().to_dict()
            if a_share_tasks
            else {},
        },
        "etf": {
            "universe_source": etf_universe.attrs.get("source", "unknown"),
            "universe_count": int(len(etf_universe)),
            "scheduled_updates": len(etf_tasks),
            "scheduled_by_reason": pd.Series([t["reason"] for t in etf_tasks]).value_counts().to_dict()
            if etf_tasks
            else {},
        },
    }

    if args.dry_run:
        return summary

    start_ts = time.time()
    a_share_results = run_pool(
        tasks=a_share_tasks,
        worker=partial(fetch_a_share_task, end_date=args.end_date, retry=args.retry, task_timeout=args.task_timeout),
        max_workers=args.workers_a_share,
        hard_timeout=max(60, (args.task_timeout + 12) * max(1, args.retry) * 2 + 30),
    )
    etf_results = run_pool(
        tasks=etf_tasks,
        worker=partial(fetch_etf_task, end_date=args.end_date, retry=args.retry, task_timeout=args.task_timeout),
        max_workers=args.workers_etf,
        hard_timeout=max(60, (args.task_timeout + 12) * max(1, args.retry) * 2 + 30),
    )
    elapsed = round(time.time() - start_ts, 2)

    a_share_failures = [row for row in a_share_results if row["status"] == "failed"]
    etf_failures = [row for row in etf_results if row["status"] == "failed"]
    a_share_fieldnames = ["code", "name", "market", "status", "source", "reason", "rows", "start_date", "end_date", "error"]
    etf_fieldnames = ["code", "name", "status", "source", "reason", "rows", "start_date", "end_date", "error"]
    a_share_failed_path = DATA_CACHE_DIR / f"daily_update_a_share_failed_{timestamp}.csv"
    etf_failed_path = DATA_CACHE_DIR / f"daily_update_etf_failed_{timestamp}.csv"
    write_csv(a_share_failed_path, a_share_failures, a_share_fieldnames)
    write_csv(etf_failed_path, etf_failures, etf_fieldnames)

    validation = repair.collect_validation(args.end_date, set(clean_universe["code"]))
    summary.update(
        {
            "elapsed_seconds": elapsed,
            "a_share": {
                **summary["a_share"],
                "success": sum(1 for row in a_share_results if row["status"] == "success"),
                "failed": len(a_share_failures),
                "failed_csv": str(a_share_failed_path),
            },
            "etf": {
                **summary["etf"],
                "success": sum(1 for row in etf_results if row["status"] == "success"),
                "failed": len(etf_failures),
                "failed_csv": str(etf_failed_path),
            },
            "validation": validation,
        }
    )

    summary_path = DATA_CACHE_DIR / f"daily_update_summary_{timestamp}.json"
    summary["summary_json"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    args = build_parser().parse_args()
    summary = run_daily_update(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.dry_run and summary.get("summary_json"):
        print(f"summary_json={summary['summary_json']}")


if __name__ == "__main__":
    main()
