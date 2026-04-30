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
BSE_PREFIXES = (
    "43",
    "83",
    "87",
    "88",
    "89",
    "92",
)
MARKET_PRIORITY = {"SH": 0, "SZ": 1, "BJ": 2}


class FetchTimeoutError(TimeoutError):
    pass


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


def get_bs_symbol(symbol: str) -> str:
    if not symbol:
        return ""
    if symbol.startswith(BSE_PREFIXES) or symbol.startswith(("4", "8")):
        return f"bj.{symbol}"
    if symbol.startswith(("6", "5", "11")):
        return f"sh.{symbol}"
    if symbol.startswith(("0", "1", "2", "3")):
        return f"sz.{symbol}"
    return f"sz.{symbol}"


def get_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("download_a_share_market")
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


def infer_market_from_code(code: str) -> str:
    if code.startswith(BSE_PREFIXES) or code.startswith(("4", "8")):
        return "BJ"
    if code.startswith(("6",)):
        return "SH"
    return "SZ"


def fetch_with_simple_retry(fetcher, retry: int = 3, sleep_seconds: int = 2) -> pd.DataFrame:
    last_error = None
    for attempt in range(1, retry + 1):
        try:
            return fetcher()
        except Exception as exc:
            last_error = exc
            time.sleep(sleep_seconds * attempt)
    raise last_error


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


def load_a_share_universe(selected_markets: set[str]) -> pd.DataFrame:
    disable_proxies()

    frames = []

    if "SH" in selected_markets:
        sh_df = fetch_with_simple_retry(ak.stock_info_sh_name_code).rename(
            columns={"证券代码": "code", "证券简称": "name"}
        )[["code", "name"]]
        sh_df["market"] = "SH"
        frames.append(sh_df)

    if "SZ" in selected_markets:
        sz_df = fetch_with_simple_retry(ak.stock_info_sz_name_code).rename(
            columns={"A股代码": "code", "A股简称": "name"}
        )[["code", "name"]]
        sz_df["market"] = "SZ"
        frames.append(sz_df)

    if "BJ" in selected_markets:
        bj_df = fetch_with_simple_retry(ak.stock_info_bj_name_code).rename(
            columns={"证券代码": "code", "证券简称": "name"}
        )[["code", "name"]]
        bj_df["market"] = "BJ"
        frames.append(bj_df)

    a_df = fetch_with_simple_retry(ak.stock_info_a_code_name).rename(
        columns={"code": "code", "name": "name"}
    )[["code", "name"]]
    a_df["market"] = a_df["code"].astype(str).str.zfill(6).map(infer_market_from_code)
    a_df = a_df[a_df["market"].isin(selected_markets)].copy()
    frames.append(a_df)

    universe = pd.concat(frames, ignore_index=True)
    universe["code"] = universe["code"].astype(str).str.zfill(6)
    universe["name"] = universe["name"].astype(str).str.strip()
    universe = universe[universe["code"].str.fullmatch(r"\d{6}")]
    universe = universe.drop_duplicates(subset=["code"], keep="first")
    return universe.sort_values(["market", "code"]).reset_index(drop=True)


def load_existing_a_share_codes(universe_codes: set[str]) -> set[str]:
    existing_codes = set()
    if not CACHE_DIR.exists():
        return existing_codes

    for path in CACHE_DIR.glob("*_full_history.parquet"):
        code = path.name.split("_")[0]
        if code in universe_codes:
            existing_codes.add(code)
    return existing_codes


def normalize_akshare_df(df: pd.DataFrame, symbol: str, stock_name: str) -> pd.DataFrame:
    renamed = df.rename(
        columns={
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "pct_chg",
            "换手率": "turn",
        }
    ).copy()

    renamed["date"] = pd.to_datetime(renamed["date"]).dt.strftime("%Y-%m-%d")
    for col in ("open", "high", "low", "close", "volume", "amount", "pct_chg", "turn"):
        if col in renamed.columns:
            renamed[col] = pd.to_numeric(renamed[col], errors="coerce")

    renamed["tradestatus"] = "1"
    renamed["pe"] = pd.NA
    renamed["pb"] = pd.NA
    renamed["ps"] = pd.NA
    renamed["pcf"] = pd.NA
    renamed["is_st"] = "1" if "ST" in stock_name.upper() else "0"
    renamed["stock_code"] = symbol
    renamed["stock_name"] = stock_name
    return renamed[STANDARD_COLUMNS].sort_values("date").reset_index(drop=True)


def normalize_baostock_df(
    df: pd.DataFrame, symbol: str, stock_name: str
) -> pd.DataFrame:
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

    for col in (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "pct_chg",
        "turn",
        "pe",
        "pb",
        "ps",
        "pcf",
    ):
        if col in renamed.columns:
            renamed[col] = pd.to_numeric(renamed[col], errors="coerce")

    renamed["date"] = pd.to_datetime(renamed["date"]).dt.strftime("%Y-%m-%d")
    renamed["stock_code"] = symbol
    renamed["stock_name"] = stock_name
    return renamed[STANDARD_COLUMNS].sort_values("date").reset_index(drop=True)


def fetch_with_baostock(
    symbol: str, stock_name: str, start_date: str, end_date: str
) -> pd.DataFrame:
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"Baostock login failed: {lg.error_msg}")

    try:
        fields = (
            "date,open,high,low,close,volume,amount,pctChg,turn,"
            "tradestatus,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
        )
        rs = bs.query_history_k_data_plus(
            get_bs_symbol(symbol),
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

        rs_name = bs.query_stock_basic(code=get_bs_symbol(symbol))
        real_name = stock_name
        if rs_name.error_code == "0" and rs_name.next():
            basic_row = rs_name.get_row_data()
            if len(basic_row) > 1 and basic_row[1]:
                real_name = basic_row[1]

        raw_df = pd.DataFrame(rows, columns=rs.fields)
        return normalize_baostock_df(raw_df, symbol, real_name)
    finally:
        bs.logout()


def fetch_with_akshare(
    symbol: str, stock_name: str, start_date: str, end_date: str
) -> pd.DataFrame:
    disable_proxies()
    df = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        adjust="qfq",
        timeout=30,
    )
    if df.empty:
        raise ValueError("AKShare returned no rows")
    return normalize_akshare_df(df, symbol, stock_name)


def fetch_symbol(
    symbol: str,
    stock_name: str,
    market: str,
    start_date: str,
    end_date: str,
    retry: int,
    task_timeout: int,
) -> dict:
    cache_path = CACHE_DIR / f"{symbol}_full_history.parquet"

    source_order = ["akshare"] if market == "BJ" else ["baostock", "akshare"]
    errors = []

    for source in source_order:
        for attempt in range(1, retry + 1):
            try:
                with time_limit(task_timeout):
                    if source == "baostock":
                        df = fetch_with_baostock(symbol, stock_name, start_date, end_date)
                    else:
                        df = fetch_with_akshare(symbol, stock_name, start_date, end_date)

                if df.empty:
                    raise ValueError("normalized dataframe is empty")

                df.to_parquet(cache_path, index=False)
                return {
                    "code": symbol,
                    "market": market,
                    "name": stock_name,
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
        "code": symbol,
        "market": market,
        "name": stock_name,
        "status": "failed",
        "source": "",
        "rows": 0,
        "start_date": "",
        "end_date": "",
        "error": " | ".join(errors),
    }


def write_failures_csv(path: Path, rows: list[dict]) -> None:
    fieldnames = [
        "code",
        "market",
        "name",
        "status",
        "source",
        "rows",
        "start_date",
        "end_date",
        "error",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="补全本地 A 股 parquet 数据湖")
    parser.add_argument("--start-date", default="2022-01-01")
    parser.add_argument(
        "--end-date",
        default=pd.Timestamp.today().strftime("%Y-%m-%d"),
    )
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--retry", type=int, default=3)
    parser.add_argument("--task-timeout", type=int, default=90)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--markets",
        default="SH,SZ,BJ",
        help="逗号分隔的市场列表，可选 SH,SZ,BJ",
    )
    parser.add_argument(
        "--include-existing",
        action="store_true",
        help="忽略本地已存在文件，强制重拉整个 universe",
    )
    parser.add_argument(
        "--codes-file",
        default="",
        help="只跑指定代码清单，每行一个 6 位代码",
    )
    return parser


def main():
    disable_proxies()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    args = build_parser().parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = LOG_DIR / f"a_share_download_{timestamp}.log"
    failed_path = LOG_DIR / f"a_share_failed_{timestamp}.csv"
    summary_path = LOG_DIR / f"a_share_summary_{timestamp}.json"
    logger = get_logger(log_path)

    logger.info("Loading A-share universe from AKShare reference tables...")
    selected_markets = {
        market.strip().upper()
        for market in args.markets.split(",")
        if market.strip()
    }
    invalid_markets = selected_markets - {"SH", "SZ", "BJ"}
    if invalid_markets:
        raise ValueError(f"Unsupported markets: {sorted(invalid_markets)}")

    universe = load_a_share_universe(selected_markets)
    universe = universe[universe["market"].isin(selected_markets)].copy()
    universe["market_rank"] = universe["market"].map(MARKET_PRIORITY)
    universe = universe.sort_values(["market_rank", "code"]).drop(columns=["market_rank"])
    if args.codes_file:
        codes_path = Path(args.codes_file)
        selected_codes = {
            line.strip().split(",")[0].zfill(6)
            for line in codes_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
        universe = universe[universe["code"].isin(selected_codes)].copy()
    universe_codes = set(universe["code"].tolist())
    existing_codes = set() if args.include_existing else load_existing_a_share_codes(universe_codes)
    tasks_df = universe[~universe["code"].isin(existing_codes)].copy()

    market_counts = universe.groupby("market")["code"].count().to_dict()
    logger.info("Universe size: %s", len(universe))
    logger.info("Universe by market: %s", market_counts)
    logger.info("Existing local A-share files: %s", len(existing_codes))
    logger.info("Missing A-share files to fetch: %s", len(tasks_df))

    if args.limit > 0:
        tasks_df = tasks_df.head(args.limit).copy()
        logger.info("Limit enabled, only fetching first %s symbols.", len(tasks_df))

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
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("Nothing to fetch. Summary written to %s", summary_path)
        return

    success_rows = []
    failed_rows = []
    start_ts = time.time()

    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                fetch_symbol,
                row.code,
                row.name,
                row.market,
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
        "fetched_by_source": pd.DataFrame(success_rows)["source"].value_counts().to_dict()
        if success_rows
        else {},
        "fetched_by_market": pd.DataFrame(success_rows)["market"].value_counts().to_dict()
        if success_rows
        else {},
    }
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    logger.info("Download complete in %s seconds", elapsed)
    logger.info("Success=%s Failed=%s", len(success_rows), len(failed_rows))
    logger.info("Failed csv: %s", failed_path)
    logger.info("Summary json: %s", summary_path)


if __name__ == "__main__":
    main()
