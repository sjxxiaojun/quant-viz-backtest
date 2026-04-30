import argparse
import csv
import json
import logging
import os
import signal
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import akshare as ak
import baostock as bs
import pandas as pd


CACHE_DIR = Path("/Users/gdxj/quant_data_lake")
LOG_DIR = Path("/Users/gdxj/quant-viz-backtest/backend/data_cache")
STANDARD_COLUMNS = [
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "pct_chg",
    "turn",
    "tradestatus",
    "pe",
    "pb",
    "ps",
    "pcf",
    "is_st",
    "stock_code",
    "stock_name",
]
ETF_PREFIXES = (
    "159",
    "510",
    "511",
    "512",
    "513",
    "515",
    "516",
    "517",
    "518",
    "520",
    "526",
    "530",
    "551",
    "560",
    "561",
    "562",
    "563",
    "588",
    "589",
)


class FetchTimeoutError(TimeoutError):
    pass


class time_limit:
    def __init__(self, seconds: int):
        self.seconds = seconds
        self.previous_handler = None

    def _handle_timeout(self, signum, frame):
        raise FetchTimeoutError(f"fetch exceeded {self.seconds}s")

    def __enter__(self):
        if self.seconds <= 0:
            return
        self.previous_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, self._handle_timeout)
        signal.alarm(self.seconds)

    def __exit__(self, exc_type, exc, tb):
        if self.seconds > 0:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, self.previous_handler)


def disable_proxies():
    for key in (
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
    ):
        os.environ[key] = ""
    os.environ["no_proxy"] = "*"
    os.environ["NO_PROXY"] = "*"


def run_with_retry(fetcher, retry: int = 3, sleep_seconds: int = 2):
    last_error = None
    for attempt in range(1, retry + 1):
        try:
            return fetcher()
        except Exception as exc:
            last_error = exc
            time.sleep(sleep_seconds * attempt)
    raise last_error


def get_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger(f"download_etf_market_{log_path.name}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def infer_exchange(code: str) -> str:
    return "sz" if code.startswith("159") else "sh"


def load_etf_universe() -> pd.DataFrame:
    disable_proxies()
    df = run_with_retry(ak.fund_etf_spot_ths)
    universe = df.rename(columns={"基金代码": "code", "基金名称": "name", "基金类型": "fund_type"})[
        ["code", "name", "fund_type"]
    ].copy()
    universe["code"] = universe["code"].astype(str).str.zfill(6)
    universe["name"] = universe["name"].astype(str).str.strip()
    universe["fund_type"] = universe["fund_type"].astype(str).str.strip()
    universe = universe[universe["code"].str.startswith(ETF_PREFIXES)]
    universe = universe.drop_duplicates(subset=["code"], keep="first")
    return universe.sort_values("code").reset_index(drop=True)


def load_existing_etf_codes(universe_codes: set[str]) -> set[str]:
    existing_codes = set()
    if not CACHE_DIR.exists():
        return existing_codes
    for path in CACHE_DIR.glob("*_full_history.parquet"):
        code = path.name.split("_")[0]
        if code in universe_codes:
            existing_codes.add(code)
    return existing_codes


def normalize_sina_df(df: pd.DataFrame, code: str, name: str) -> pd.DataFrame:
    norm = df.copy()
    norm["date"] = pd.to_datetime(norm["date"]).dt.strftime("%Y-%m-%d")
    for col in ("open", "high", "low", "close", "volume", "amount"):
        norm[col] = pd.to_numeric(norm[col], errors="coerce")

    norm["pct_chg"] = norm["close"].pct_change().fillna(0) * 100
    norm["turn"] = pd.NA
    norm["tradestatus"] = "1"
    norm["pe"] = pd.NA
    norm["pb"] = pd.NA
    norm["ps"] = pd.NA
    norm["pcf"] = pd.NA
    norm["is_st"] = "1"
    norm["stock_code"] = code
    norm["stock_name"] = name
    return norm[STANDARD_COLUMNS].sort_values("date").reset_index(drop=True)


def normalize_baostock_df(df: pd.DataFrame, code: str, name: str) -> pd.DataFrame:
    renamed = df.rename(
        columns={
            "pctChg": "pct_chg",
            "peTTM": "pe",
            "pbMRQ": "pb",
            "psTTM": "ps",
            "pcfNcfTTM": "pcf",
            "isST": "is_st",
        }
    ).copy()
    for col in ("open", "high", "low", "close", "volume", "amount", "pct_chg", "turn", "pe", "pb", "ps", "pcf"):
        if col in renamed.columns:
            renamed[col] = pd.to_numeric(renamed[col], errors="coerce")
    renamed["date"] = pd.to_datetime(renamed["date"]).dt.strftime("%Y-%m-%d")
    renamed["stock_code"] = code
    renamed["stock_name"] = name
    return renamed[STANDARD_COLUMNS].sort_values("date").reset_index(drop=True)


def fetch_with_sina(code: str, name: str, start_date: str) -> pd.DataFrame:
    disable_proxies()
    symbol = f"{infer_exchange(code)}{code}"
    df = ak.fund_etf_hist_sina(symbol=symbol)
    if df.empty:
        raise ValueError("Sina returned no rows")
    df = normalize_sina_df(df, code, name)
    return df[df["date"] >= start_date].reset_index(drop=True)


def fetch_with_baostock(code: str, name: str, start_date: str, end_date: str) -> pd.DataFrame:
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"Baostock login failed: {lg.error_msg}")
    try:
        bs_code = f"{infer_exchange(code)}.{code}"
        fields = (
            "date,open,high,low,close,volume,amount,pctChg,turn,"
            "tradestatus,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
        )
        rs = bs.query_history_k_data_plus(
            bs_code,
            fields,
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2",
        )
        if rs.error_code != "0":
            raise RuntimeError(rs.error_msg)
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            raise ValueError("Baostock returned no rows")

        rs_name = bs.query_stock_basic(code=bs_code)
        real_name = name
        if rs_name.error_code == "0" and rs_name.next():
            row = rs_name.get_row_data()
            if len(row) > 1 and row[1]:
                real_name = row[1]
        raw_df = pd.DataFrame(rows, columns=rs.fields)
        return normalize_baostock_df(raw_df, code, real_name)
    finally:
        bs.logout()


def fetch_etf_symbol(code: str, name: str, start_date: str, end_date: str, retry: int, task_timeout: int) -> dict:
    cache_path = CACHE_DIR / f"{code}_full_history.parquet"
    errors = []

    for source in ("sina", "baostock"):
        for attempt in range(1, retry + 1):
            try:
                with time_limit(task_timeout):
                    if source == "sina":
                        df = fetch_with_sina(code, name, start_date)
                    else:
                        df = fetch_with_baostock(code, name, start_date, end_date)
                if df.empty:
                    raise ValueError("normalized dataframe is empty")
                df.to_parquet(cache_path, index=False)
                return {
                    "code": code,
                    "name": name,
                    "status": "success",
                    "source": source,
                    "rows": int(len(df)),
                    "start_date": str(df["date"].min()),
                    "end_date": str(df["date"].max()),
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
        "rows": 0,
        "start_date": "",
        "end_date": "",
        "error": " | ".join(errors),
    }


def write_failures_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = ["code", "name", "status", "source", "rows", "start_date", "end_date", "error"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="补全本地 ETF parquet 数据湖")
    parser.add_argument("--start-date", default="2022-01-01")
    parser.add_argument("--end-date", default=pd.Timestamp.today().strftime("%Y-%m-%d"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retry", type=int, default=3)
    parser.add_argument("--task-timeout", type=int, default=90)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--include-existing", action="store_true")
    parser.add_argument("--codes-file", default="", help="只跑指定 ETF 代码清单")
    return parser


def main():
    disable_proxies()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    args = build_parser().parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"etf_download_{timestamp}.log"
    failed_path = LOG_DIR / f"etf_failed_{timestamp}.csv"
    summary_path = LOG_DIR / f"etf_summary_{timestamp}.json"
    logger = get_logger(log_path)

    logger.info("Loading ETF universe from THS...")
    universe = load_etf_universe()
    if args.codes_file:
        selected_codes = {
            line.strip().split(",")[0].zfill(6)
            for line in Path(args.codes_file).read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        universe = universe[universe["code"].isin(selected_codes)].copy()

    universe_codes = set(universe["code"].tolist())
    existing_codes = set() if args.include_existing else load_existing_etf_codes(universe_codes)
    tasks_df = universe[~universe["code"].isin(existing_codes)].copy()

    logger.info("Universe size: %s", len(universe))
    logger.info("Existing local ETF files: %s", len(existing_codes))
    logger.info("Missing ETF files to fetch: %s", len(tasks_df))

    if args.limit > 0:
        tasks_df = tasks_df.head(args.limit).copy()
        logger.info("Limit enabled, only fetching first %s codes.", len(tasks_df))

    if tasks_df.empty:
        summary = {
            "universe_size": len(universe),
            "existing_local_files": len(existing_codes),
            "scheduled_fetches": 0,
            "success": 0,
            "failed": 0,
            "log_path": str(log_path),
            "failed_csv": str(failed_path),
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Nothing to fetch. Summary written to %s", summary_path)
        return

    success_rows = []
    failed_rows = []
    start_ts = time.time()

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                fetch_etf_symbol,
                row.code,
                row.name,
                args.start_date,
                args.end_date,
                args.retry,
                args.task_timeout,
            ): row.code
            for row in tasks_df.itertuples(index=False)
        }
        total = len(futures)
        for index, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            if result["status"] == "success":
                success_rows.append(result)
            else:
                failed_rows.append(result)

            if index == 1 or index % 25 == 0 or result["status"] == "failed":
                logger.info(
                    "[%s/%s] %s %s via %s rows=%s err=%s",
                    index,
                    total,
                    result["code"],
                    result["status"],
                    result["source"] or "-",
                    result["rows"],
                    result["error"],
                )

    write_failures_csv(failed_path, failed_rows)
    elapsed = round(time.time() - start_ts, 2)
    summary = {
        "universe_size": len(universe),
        "existing_local_files": len(existing_codes),
        "scheduled_fetches": len(tasks_df),
        "success": len(success_rows),
        "failed": len(failed_rows),
        "elapsed_seconds": elapsed,
        "log_path": str(log_path),
        "failed_csv": str(failed_path),
        "fetched_by_source": pd.DataFrame(success_rows)["source"].value_counts().to_dict() if success_rows else {},
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Download complete in %s seconds", elapsed)
    logger.info("Success=%s Failed=%s", len(success_rows), len(failed_rows))
    logger.info("Failed csv: %s", failed_path)
    logger.info("Summary json: %s", summary_path)


if __name__ == "__main__":
    main()
