"""Versioned, auditable daily research data contracts. No legacy cache is rewritten."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from data_provider import cache_lock, fetch_provider
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ENGINE_VERSION = "daily-v3"
EVALUATION_VERSION = "causal-wf-v2"
SHANGHAI = ZoneInfo("Asia/Shanghai")
RUNTIME_DIR = Path(os.getenv("QUANT_RUNTIME_DIR", str(Path(__file__).parent / "runtime")))


def market_now():
    return datetime.now(SHANGHAI)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, default=str, allow_nan=False))
    tmp.replace(path)


class DataContractError(ValueError):
    pass


class TradingCalendar:
    def __init__(self, path=None):
        self.path = Path(path or RUNTIME_DIR / "trade_calendar.json")

    def dates(self, start, end):
        if self.path.exists():
            dates = json.loads(self.path.read_text())
        else:
            frame = fetch_provider('akshare', 'tool_trade_date_hist_sina')
            dates = sorted(pd.to_datetime(frame["trade_date"]).dt.strftime("%Y-%m-%d").tolist())
            self.path.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(self.path, dates)
        if not dates or str(end) > dates[-1]:
            raise DataContractError("交易日历未覆盖请求日期，请更新日历。")
        return [d for d in dates if str(start) <= d <= str(end)]

    def latest_completed(self):
        now = market_now()
        end = (now.date() if now.hour >= 16 else now.date() - timedelta(days=1)).isoformat()
        dates = self.dates((now.date() - timedelta(days=30)).isoformat(), end)
        if not dates:
            raise DataContractError("无法确定最近已完成交易日。")
        return dates[-1]


def historical_universe(manager, limit, as_of):
    """Freeze a liquidity sample using only observations known before the run starts."""
    rows = []
    candidates = {}
    for directory in [manager.cache_dir, *sorted(manager.cache_dir.glob("_removed*"))]:
        for path in sorted(directory.glob("*_full_history.parquet")):
            candidates.setdefault(path.name.split("_")[0], path)
    for symbol, path in sorted(candidates.items()):
        if manager.is_etf_symbol(symbol):
            continue
        try:
            f = pd.read_parquet(path)
            f = f[f["date"].astype(str) <= as_of].sort_values("date").tail(20)
            if len(f) < 20 or (pd.Timestamp(as_of) - pd.Timestamp(f.iloc[-1]["date"])).days > 14:
                continue
            amount = pd.to_numeric(f["amount"], errors="coerce")
            liquidity = float(amount.median())
            if liquidity > 0:
                rows.append((symbol, liquidity))
        except (OSError, ValueError, KeyError):
            continue
    rows.sort(key=lambda row: (-row[1], row[0]))
    symbols = [r[0] for r in rows[:limit]]
    if not symbols:
        raise DataContractError("回测开始前没有覆盖至少20个交易日的可验证股票池。")
    return symbols, {
        "selection_method": "historical_liquidity_v2", "availability_cutoff": as_of,
        "method_cn": "开始前20个交易日成交额中位数，固定研究样本",
        "survivorship_bias_free": False,
        "historical_membership_note": "含可读取的隔离历史文件；历史上市/退市成员资料未完整认证。",
        "eligible_symbols": len(rows), "selected_symbols": len(symbols),
        "is_budget_sample": len(rows) > len(symbols), "frozen_symbols": symbols,
    }


class ExecutionDataService:
    def __init__(self, manager, root=None):
        self.manager = manager
        self.root = Path(root or RUNTIME_DIR / "raw")

    def _load_actions(self, symbol, years):
        with cache_lock(self.root / 'actions' / f'{symbol}.json'):
            return self._load_actions_locked(symbol, years)

    def _load_actions_locked(self, symbol, years):
        """BaoStock reports per-share dividends and actual payout/share-listing dates."""
        path = self.root / "actions" / f"{symbol}.json"
        cached = json.loads(path.read_text()) if path.exists() else {"years": [], "actions": []}
        recent = time.time() - float(cached.get("checked_at", 0)) < 3600
        verified = set(cached["years"]) | (set(cached.get("recent_years", [])) if recent else set())
        missing = set(years) - verified
        if not missing:
            return cached["actions"]
        for year in sorted(missing):
            provider_rows = fetch_provider('baostock', 'dividends', symbol=("sh." if symbol.startswith("6") else "sz.") + symbol, year=year)
            for row in provider_rows.to_dict('records'):
                date = row.get("dividOperateDate")
                if not date:
                    continue
                cash = float(row.get("dividCashPsBeforeTax") or 0)
                shares = float(row.get("dividStocksPs") or 0) + float(row.get("dividReserveToStockPs") or 0)
                if cash and not row.get("dividPayDate"):
                    raise DataContractError(f"{symbol} {date} 缺少实际派息日")
                if shares and not row.get("dividStockMarketDate"):
                    raise DataContractError(f"{symbol} {date} 缺少红股上市日")
                cached["actions"].append({"stock_code": symbol, "date": date, "cash_dividend_per_share": cash, "share_multiplier": 1 + shares,
                    "dividend_pay_date": row.get("dividPayDate", ""), "share_available_date": row.get("dividStockMarketDate", ""), "source": "BAOSTOCK_DIVIDEND"})
            if year < market_now().year:
                cached["years"].append(year)
        # Refreshes of the current year replace identical events instead of paying twice.
        events = {(a["stock_code"], a["date"]): a for a in cached["actions"]}
        cached["actions"] = list(events.values())
        cached["years"] = sorted(set(cached["years"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        cached["checked_at"] = time.time()
        cached["recent_years"] = sorted(set(years))
        atomic_json(path, cached)
        return cached["actions"]

    def _load_raw(self, symbol, start, end):
        with cache_lock(self.root / f'{symbol}.parquet'):
            return self._load_raw_locked(symbol, start, end)

    def _load_raw_locked(self, symbol, start, end):
        path = self.root / f"{symbol}.parquet"
        if path.exists():
            f = pd.read_parquet(path)
            if f.date.min() <= start and f.date.max() >= end:
                return f
        operation = 'fund_etf_hist_em' if self.manager.is_etf_symbol(symbol) else 'stock_zh_a_hist'
        try:
            f = fetch_provider('akshare', operation, symbol=symbol, start_date=start.replace('-', ''), end_date=end.replace('-', ''), adjust='')
        except Exception:
            if self.manager.is_etf_symbol(symbol):
                raise
            f = fetch_provider('baostock', 'history', symbol=('sh.' if symbol.startswith('6') else 'sz.') + symbol, start=start, end=end, adjustflag='3')
            f = f.rename(columns={'pctChg': 'pct_chg', 'preclose': 'prev_close'})
        f = f.rename(columns={"日期": "date", "开盘": "open", "最高": "high", "最低": "low", "收盘": "close", "涨跌幅": "pct_chg"})
        if f.empty:
            raise DataContractError(f"{symbol} 未获取到未复权价格。")
        f["date"] = pd.to_datetime(f.date).dt.strftime("%Y-%m-%d")
        for column in ('open', 'high', 'low', 'close', 'pct_chg', 'prev_close'):
            if column in f:
                f[column] = pd.to_numeric(f[column], errors='coerce')
        if 'prev_close' not in f:
            f['prev_close'] = f.close / (1 + f.pct_chg / 100)
        self.root.mkdir(parents=True, exist_ok=True)
        if path.exists():
            f = pd.concat([pd.read_parquet(path), f]).drop_duplicates("date", keep="last").sort_values("date")
        tmp = path.with_name(path.stem + "." + uuid.uuid4().hex + ".tmp.parquet")
        f.to_parquet(tmp, index=False)
        tmp.replace(path)
        return f

    def prepare(self, frame, allow_approximate=False):
        f = frame.copy()
        required = [f"raw_{p}" for p in ("open", "high", "low", "close", "prev_close")]
        if all(c in f for c in required):
            pass
        elif allow_approximate:
            for p in ("open", "high", "low", "close", "prev_close"):
                f[f"raw_{p}"] = f[p] if p in f else f.groupby("stock_code").close.shift(1)
            f.attrs["approximate_execution"] = True
        else:
            pieces = []
            for symbol, group in f.groupby("stock_code", sort=True):
                try:
                    raw = self._load_raw(symbol, str(group.date.min()), str(group.date.max()))
                except Exception as exc:
                    raise DataContractError(f"{symbol} 缺少未复权成交价格：{exc}") from exc
                raw = raw[["date", "open", "high", "low", "close", "prev_close"]].rename(columns={p: f"raw_{p}" for p in ("open", "high", "low", "close", "prev_close")})
                pieces.append(group.merge(raw, on="date", how="left", validate="many_to_one"))
            f = pd.concat(pieces, ignore_index=True)
        if f[required].isna().any().any() or (f[required] <= 0).any().any():
            raise DataContractError("未复权OHLC/除权参考价缺失或无效，拒绝推测成交。")
        f["adjustment_factor"] = f.close / f.raw_close
        instruments_path = self.root / "instruments.json"
        instruments = json.loads(instruments_path.read_text()) if instruments_path.exists() else {}
        settlement = f.stock_code.map(lambda c: instruments.get(str(c), {}).get("settlement_days", 0 if str(c).startswith(("511", "513", "518")) else 1))
        f["settlement_days"] = pd.to_numeric(f["settlement_days"], errors="coerce").fillna(settlement) if "settlement_days" in f else settlement
        for field in ("price_limit_pct", "listing_date"):
            declared = f.stock_code.map(lambda c: instruments.get(str(c), {}).get(field))
            if declared.notna().any():
                f[field] = f[field].fillna(declared) if field in f else declared
        # Company actions are explicit, never inferred from adjusted-price jumps.
        action_path = self.root / "corporate_actions.json"
        actions = json.loads(action_path.read_text()) if action_path.exists() else []
        lookup = {(str(a["stock_code"]), str(a["date"])): a for a in actions}
        verified_action_symbols = set()
        if not allow_approximate and self.manager is not None:
            for symbol, group in f.groupby("stock_code"):
                if not self.manager.is_etf_symbol(symbol):
                    try:
                        for a in self._load_actions(str(symbol), set(pd.to_datetime(group.date).dt.year)):
                            lookup.setdefault((a["stock_code"], a["date"]), a)
                        verified_action_symbols.add(str(symbol))
                    except Exception as exc:
                        raise DataContractError(f"{symbol} 无法验证公司行动：{exc}") from exc
        for c, default in [("cash_dividend_per_share", 0.0), ("share_multiplier", 1.0), ("dividend_pay_date", ""), ("share_available_date", "")]:
            if c not in f:
                f[c] = default
        for i, row in f.iterrows():
            a = lookup.get((str(row.stock_code), str(row.date)))
            if a:
                for c in ("cash_dividend_per_share", "share_multiplier", "dividend_pay_date", "share_available_date"):
                    if c in a:
                        f.at[i, c] = a[c]
        changes = f.sort_values(["stock_code", "date"]).groupby("stock_code").adjustment_factor.pct_change().abs() > 0.002
        known = (f.cash_dividend_per_share > 0) | (f.share_multiplier != 1)
        # Legacy caches can mix adjustment bases/providers on isolated dates.
        # Once actions are verified, strict indicators are built entirely from
        # raw bars and those actions, never from the obsolete adjusted series.
        unverified = ~f.stock_code.astype(str).isin(verified_action_symbols)
        if not allow_approximate and (changes.reindex(f.index, fill_value=False) & ~known & unverified).any():
            raise DataContractError("检测到复权因子变化但没有公司行动记录，请补充 corporate_actions.json；拒绝虚构分红或拆股。")
        if not allow_approximate:
            # A download-day qfq base incorporates later actions. Build a causal
            # total-return indicator series from raw bars and actions known on each day.
            f = f.sort_values(["stock_code", "date"]).copy()
            prior_raw = f.groupby('stock_code').raw_close.shift(1)
            unknown_reference_change = (f.raw_prev_close / prior_raw - 1).abs() > .002
            if (unknown_reference_change & ~known.reindex(f.index)).any():
                raise DataContractError('未复权除权参考价发生变化但缺少公司行动，拒绝执行。')
            if known.reindex(f.index).any():
                from decimal import Decimal, ROUND_HALF_UP
                for index in f.index[known.reindex(f.index)]:
                    if pd.isna(prior_raw.loc[index]):
                        raise DataContractError('公司行动日之前缺少未复权收盘价，请补齐预热数据。')
                    if f.at[index, 'share_multiplier'] <= 0 or f.at[index, 'cash_dividend_per_share'] < 0:
                        raise DataContractError('不支持的公司行动参数')
                    # Cash dividends/bonus shares only; rights issues require
                    # an explicit supported action, never an inferred factor.
                    reference = (prior_raw.loc[index] - f.at[index, 'cash_dividend_per_share']) / f.at[index, 'share_multiplier']
                    f.at[index, 'raw_prev_close'] = float(Decimal(str(reference)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
                    if f.at[index, 'raw_prev_close'] <= 0:
                        raise DataContractError('公司行动后的参考价无效')
            increments = f.share_multiplier + f.cash_dividend_per_share / f.raw_close
            f["adjustment_factor"] = increments.groupby(f.stock_code).cumprod()
            for field in ("open", "high", "low", "close"):
                f[f"download_adjusted_{field}"] = f[field]
                f[field] = f[f"raw_{field}"] * f.adjustment_factor
            f["prev_close"] = f.groupby("stock_code").close.shift(1).fillna(f.raw_prev_close * f.adjustment_factor)
            f["pct_chg"] = (f.close / f.prev_close - 1) * 100
            f["intraday_ret"] = f.close / f.open - 1
            f["open_gap"] = f.open / f.prev_close - 1
            f["amplitude"] = (f.high - f.low) / f.prev_close * 100
            f.attrs["adjust"] = "causal_total_return"
        return f


def snapshot_fingerprint(frame, manifest):
    if frame is None or frame.empty:
        return 'unavailable'
    keys = [key for key in ('date', 'stock_code') if key in frame]
    canonical = frame.sort_values(keys).reset_index(drop=True) if keys else frame.reset_index(drop=True)
    values = pd.util.hash_pandas_object(canonical.reindex(sorted(canonical.columns), axis=1), index=False).values.tobytes()
    return hashlib.sha256(values + json.dumps(manifest, sort_keys=True, default=str).encode()).hexdigest()


def persist_snapshot(frame, request, universe, root=None):
    root = Path(root or RUNTIME_DIR / "snapshots")
    canonical = frame.sort_values(["date", "stock_code"]).reset_index(drop=True)
    manifest = {"engine_version": ENGINE_VERSION, "request": request, "universe": universe}
    digest = snapshot_fingerprint(canonical, manifest)
    root.mkdir(parents=True, exist_ok=True)
    if not ((root / f"{digest}.parquet").exists() and (root / f"{digest}.json").exists()):
        tmp = root / f"{digest}.{uuid.uuid4().hex}.tmp.parquet"
        canonical.to_parquet(tmp, index=False)
        tmp.replace(root / f"{digest}.parquet")
        atomic_json(root / f"{digest}.json", manifest)
    return digest
