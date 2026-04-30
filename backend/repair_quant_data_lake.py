import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


BACKEND_DIR = Path("/Users/gdxj/quant-viz-backtest/backend")
ROOT_DIR = Path("/Users/gdxj/quant_data_lake")
ETF_DIR = ROOT_DIR / "etf"
REMOVED_ST_DIR = ROOT_DIR / "_removed_st_delisted"
REMOVED_NON_UNIVERSE_DIR = ROOT_DIR / "_removed_not_in_universe"
REMOVED_BJ_DIR = ROOT_DIR / "_removed_bj"
DATA_CACHE_DIR = BACKEND_DIR / "data_cache"
START_DATE = "2022-01-01"
EXPECTED_START_DATE = "2022-01-04"

sys.path.insert(0, str(BACKEND_DIR))

import download_a_share_market as a_share_dl  # noqa: E402
import download_etf_market as etf_dl  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repair local quant_data_lake layout and A-share data")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--end-date",
        default=(pd.Timestamp.today().normalize() - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
    )
    parser.add_argument("--retry", type=int, default=3)
    parser.add_argument("--task-timeout", type=int, default=90)
    return parser


def is_st_or_delisted_name(name: str) -> bool:
    text = str(name or "").strip()
    upper = text.upper()
    return "ST" in upper or "退市" in text or text.endswith("退") or text.startswith("退")


def is_truthy_is_st(value) -> bool:
    if pd.isna(value):
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "t", "yes", "y"}


def ensure_dirs() -> None:
    for path in (
        ROOT_DIR,
        ETF_DIR,
        REMOVED_ST_DIR,
        REMOVED_NON_UNIVERSE_DIR,
        REMOVED_BJ_DIR,
        DATA_CACHE_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


def move_file(path: Path, target_dir: Path) -> str:
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / path.name
    if dest.exists():
        dest.unlink()
    shutil.move(str(path), str(dest))
    return str(dest)


def load_universe() -> tuple[pd.DataFrame, pd.DataFrame]:
    a_share_dl.disable_proxies()
    universe_all = a_share_dl.load_a_share_universe({"SH", "SZ"})
    universe_all = universe_all.sort_values(["market", "code"]).reset_index(drop=True)
    clean_universe = universe_all[~universe_all["name"].map(is_st_or_delisted_name)].copy()
    clean_universe = clean_universe.sort_values(["market", "code"]).reset_index(drop=True)
    return universe_all, clean_universe


def read_schema_columns(path: Path) -> list[str]:
    return pq.read_schema(path).names


def read_file_meta(path: Path) -> dict:
    df = pd.read_parquet(path, columns=["date", "stock_name", "is_st"])
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    latest = df.iloc[-1]
    return {
        "rows": int(len(df)),
        "min_date": latest["date"].strftime("%Y-%m-%d") if len(df) == 1 else df["date"].iloc[0].strftime("%Y-%m-%d"),
        "max_date": df["date"].iloc[-1].strftime("%Y-%m-%d"),
        "latest_name": str(latest.get("stock_name", "") or "").strip(),
        "latest_is_st": is_truthy_is_st(latest.get("is_st")),
    }


def audit_and_reorganize(
    all_codes: set[str],
    clean_codes: set[str],
    freshness_date: str,
) -> dict:
    refresh_reasons: dict[str, list[str]] = {}
    kept_codes: set[str] = set()
    moved_counts = {
        "etf": 0,
        "st_delisted": 0,
        "non_universe": 0,
        "bj": 0,
    }

    for path in sorted(ROOT_DIR.glob("*_full_history.parquet")):
        code = path.name.split("_")[0]

        if code.startswith(etf_dl.ETF_PREFIXES):
            move_file(path, ETF_DIR)
            moved_counts["etf"] += 1
            continue

        if code.startswith(a_share_dl.BSE_PREFIXES) or code.startswith(("4", "8")):
            move_file(path, REMOVED_BJ_DIR)
            moved_counts["bj"] += 1
            continue

        if not (len(code) == 6 and code.isdigit()):
            move_file(path, REMOVED_NON_UNIVERSE_DIR)
            moved_counts["non_universe"] += 1
            continue

        schema_columns = read_schema_columns(path)
        meta = read_file_meta(path)

        if code not in all_codes:
            if meta["latest_is_st"] or is_st_or_delisted_name(meta["latest_name"]):
                move_file(path, REMOVED_ST_DIR)
                moved_counts["st_delisted"] += 1
            else:
                move_file(path, REMOVED_NON_UNIVERSE_DIR)
                moved_counts["non_universe"] += 1
            continue

        if code not in clean_codes or meta["latest_is_st"] or is_st_or_delisted_name(meta["latest_name"]):
            move_file(path, REMOVED_ST_DIR)
            moved_counts["st_delisted"] += 1
            continue

        kept_codes.add(code)
        reasons = []
        if schema_columns != a_share_dl.STANDARD_COLUMNS:
            reasons.append("schema")
        if meta["min_date"] > EXPECTED_START_DATE:
            reasons.append("start_date")
        if meta["max_date"] < freshness_date:
            reasons.append("stale")
        if not meta["latest_name"] or meta["latest_name"] == code:
            reasons.append("name")

        if reasons:
            refresh_reasons[code] = reasons

    missing_codes = sorted(clean_codes - kept_codes)
    for code in missing_codes:
        refresh_reasons.setdefault(code, []).append("missing")

    return {
        "refresh_reasons": refresh_reasons,
        "kept_codes": sorted(kept_codes),
        "missing_codes": missing_codes,
        "moved_counts": moved_counts,
    }


def write_codes_file(codes: list[str], timestamp: str) -> Path:
    path = DATA_CACHE_DIR / f"repair_a_share_codes_{timestamp}.txt"
    path.write_text("\n".join(codes) + ("\n" if codes else ""), encoding="utf-8")
    return path


def run_a_share_refresh(
    codes_file: Path,
    end_date: str,
    workers: int,
    retry: int,
    task_timeout: int,
) -> subprocess.CompletedProcess:
    cmd = [
        "python3",
        str(BACKEND_DIR / "download_a_share_market.py"),
        "--start-date",
        START_DATE,
        "--end-date",
        end_date,
        "--markets",
        "SH,SZ",
        "--workers",
        str(workers),
        "--retry",
        str(retry),
        "--task-timeout",
        str(task_timeout),
        "--codes-file",
        str(codes_file),
        "--include-existing",
    ]
    return subprocess.run(cmd, check=False, cwd=str(BACKEND_DIR))


def collect_validation(freshness_date: str, clean_codes: set[str]) -> dict:
    stock_records = []
    for path in sorted(ROOT_DIR.glob("*_full_history.parquet")):
        code = path.name.split("_")[0]
        if code not in clean_codes:
            continue
        meta = read_file_meta(path)
        stock_records.append(
            {
                "code": code,
                "rows": meta["rows"],
                "min_date": meta["min_date"],
                "max_date": meta["max_date"],
                "latest_name": meta["latest_name"],
            }
        )

    stock_df = pd.DataFrame(stock_records)
    validation = {
        "root_clean_a_share_files": int(len(stock_df)),
        "etf_files": int(len(list(ETF_DIR.glob("*_full_history.parquet")))),
        "removed_st_delisted_files": int(len(list(REMOVED_ST_DIR.glob("*_full_history.parquet")))),
        "removed_non_universe_files": int(len(list(REMOVED_NON_UNIVERSE_DIR.glob("*_full_history.parquet")))),
        "removed_bj_files": int(len(list(REMOVED_BJ_DIR.glob("*_full_history.parquet")))),
        "freshness_date": freshness_date,
        "fresh_up_to_target": 0,
        "still_stale_before_target": 0,
        "min_date_after_2022_01_04": 0,
        "placeholder_name_files": 0,
        "stale_examples": [],
    }

    if stock_df.empty:
        return validation

    validation["fresh_up_to_target"] = int((stock_df["max_date"] >= freshness_date).sum())
    validation["still_stale_before_target"] = int((stock_df["max_date"] < freshness_date).sum())
    validation["min_date_after_2022_01_04"] = int((stock_df["min_date"] > EXPECTED_START_DATE).sum())
    validation["placeholder_name_files"] = int((stock_df["latest_name"] == stock_df["code"]).sum())
    validation["stale_examples"] = (
        stock_df[stock_df["max_date"] < freshness_date]
        .sort_values(["max_date", "code"])
        .head(30)
        .to_dict(orient="records")
    )
    return validation


def main() -> None:
    args = build_parser().parse_args()
    ensure_dirs()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    universe_all, clean_universe = load_universe()
    all_codes = set(universe_all["code"])
    clean_codes = set(clean_universe["code"])

    audit = audit_and_reorganize(all_codes=all_codes, clean_codes=clean_codes, freshness_date=args.end_date)
    refresh_reasons = audit["refresh_reasons"]
    refresh_codes = sorted(refresh_reasons)
    codes_file = write_codes_file(refresh_codes, timestamp)

    pre_summary = {
        "timestamp": timestamp,
        "start_date": START_DATE,
        "end_date": args.end_date,
        "universe_all_count": int(len(universe_all)),
        "clean_universe_count": int(len(clean_universe)),
        "excluded_st_from_universe": int(len(universe_all) - len(clean_universe)),
        "kept_existing_clean_files": int(len(audit["kept_codes"])),
        "missing_codes": int(len(audit["missing_codes"])),
        "refresh_codes": int(len(refresh_codes)),
        "refresh_reason_counts": pd.Series(
            [reason for reasons in refresh_reasons.values() for reason in reasons]
        ).value_counts().to_dict()
        if refresh_reasons
        else {},
        "moved_counts": audit["moved_counts"],
        "codes_file": str(codes_file),
    }
    pre_summary_path = DATA_CACHE_DIR / f"repair_quant_data_lake_pre_{timestamp}.json"
    pre_summary_path.write_text(
        json.dumps(pre_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    refresh_return_code = None
    if refresh_codes:
        completed = run_a_share_refresh(
            codes_file=codes_file,
            end_date=args.end_date,
            workers=args.workers,
            retry=args.retry,
            task_timeout=args.task_timeout,
        )
        refresh_return_code = completed.returncode

    validation = collect_validation(args.end_date, clean_codes)
    post_summary = {
        **pre_summary,
        "refresh_return_code": refresh_return_code,
        "validation": validation,
    }
    post_summary_path = DATA_CACHE_DIR / f"repair_quant_data_lake_post_{timestamp}.json"
    post_summary_path.write_text(
        json.dumps(post_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(post_summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
