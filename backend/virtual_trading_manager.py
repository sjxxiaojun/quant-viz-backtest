import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from pathlib import Path
import logging
import json
import random

from data_manager import DataFetchError, DataManager, PoolDataFetchError
from position_manager import HoldingInfo, PositionManager
from strategy_registry import STRATEGY_REGISTRY
from strategy_versioning import StrategyVersionStore

logger = logging.getLogger("VirtualTradingManager")

VIRTUAL_A_SHARE_SAMPLE_SIZE = 300
VIRTUAL_WARMUP_DAYS = 260
VIRTUAL_UNIVERSE_VERSION = "full_market_prescreen_v1"
VIRTUAL_FEE_RATE = 0.002
VIRTUAL_MAX_VOLUME_PARTICIPATION = 0.10


class VirtualTradingManager:
    def __init__(self, db_path: Path, data_manager: DataManager):
        self.db_path = db_path
        self.data_manager = data_manager
        self.pools = self._load_pools()
        self.strategy_version_store = StrategyVersionStore(db_path)
        self._ensure_tables()

    def _get_conn(self):
        return sqlite3.connect(self.db_path)

    def _ensure_tables(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                strategy_id TEXT PRIMARY KEY,
                strategy_name TEXT,
                cash REAL,
                total_value REAL,
                start_value REAL,
                last_update TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                strategy_id TEXT,
                symbol TEXT,
                shares INTEGER,
                cost_price REAL,
                current_price REAL,
                entry_date TEXT,
                entry_price REAL,
                PRIMARY KEY (strategy_id, symbol)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                strategy_id TEXT,
                date TEXT,
                symbol TEXT,
                side TEXT,
                price REAL,
                shares INTEGER,
                fee REAL,
                msg TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                strategy_id TEXT,
                date TEXT,
                total_value REAL,
                cash REAL,
                PRIMARY KEY (strategy_id, date)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS execution_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS strategy_reports (
                strategy_id TEXT PRIMARY KEY,
                date TEXT,
                status TEXT,
                pool TEXT,
                universe_label TEXT,
                universe_method TEXT,
                universe_size INTEGER,
                raw_signal_count INTEGER,
                selected_signal_count INTEGER,
                selected_symbols TEXT,
                message TEXT
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_trade_log_strategy_date ON trade_log(strategy_id, date, id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_stats_strategy_date ON daily_stats(strategy_id, date)")
        cursor.execute("PRAGMA table_info(positions)")
        position_columns = {row[1] for row in cursor.fetchall()}
        if "entry_date" not in position_columns:
            cursor.execute("ALTER TABLE positions ADD COLUMN entry_date TEXT")
        if "entry_price" not in position_columns:
            cursor.execute("ALTER TABLE positions ADD COLUMN entry_price REAL")
        conn.commit()
        conn.close()

    def _load_pools(self) -> Dict[str, List[str]]:
        pool_path = Path(__file__).with_name("pools.json")
        try:
            with pool_path.open("r", encoding="utf-8") as f:
                pools = json.load(f)
        except Exception as exc:
            logger.warning(f"Failed to load virtual trading pools: {exc}")
            return {}
        return {
            name: self._dedupe_symbols(values)
            for name, values in pools.items()
            if isinstance(values, list)
        }

    def _dedupe_symbols(self, symbols: List[str]) -> List[str]:
        seen = set()
        ordered = []
        for symbol in symbols:
            code = str(symbol or "").strip()
            if code.isdigit() and len(code) < 6:
                code = code.zfill(6)
            if not code or code in seen:
                continue
            seen.add(code)
            ordered.append(code)
        return ordered

    def _resolve_strategy_pool_symbols(
        self,
        pool: str,
        target_date: Optional[str] = None,
        warmup_start: Optional[str] = None,
    ) -> tuple[List[str], Dict[str, object]]:
        if pool == "etf":
            symbols = self.pools.get("etf", []) or self.data_manager.list_local_codes("etf")
            return symbols, {
                "universe_label": f"ETF 本地池（{len(symbols)}）",
                "universe_method": "predefined_etf_pool",
                "local_universe_size": len(symbols),
            }

        local_count = len(self.data_manager.list_local_codes("a_share"))
        symbols: List[str] = []
        metadata: Dict[str, object] = {}
        selector = getattr(self.data_manager, "select_local_a_share_symbols", None)
        if callable(selector):
            try:
                symbols = selector(
                    VIRTUAL_A_SHARE_SAMPLE_SIZE,
                    min_end_date=target_date,
                    min_start_date=warmup_start,
                )
                metadata = getattr(self.data_manager, "get_last_symbol_selection_metadata", lambda: {})()
            except Exception as exc:
                logger.warning(f"Virtual trading full-market prescreen failed for pool={pool}: {exc}")
                symbols = []
        if not symbols:
            local_symbols = self.data_manager.list_local_codes("a_share")
            symbols = local_symbols[:VIRTUAL_A_SHARE_SAMPLE_SIZE]
            metadata = {"selection_method": "local_a_share_fallback"}

        return symbols, {
            "universe_label": f"A股全市场轻量预筛样本（{len(symbols)}/{local_count}）",
            "universe_method": metadata.get("selection_method") or "full_market_prescreen",
            "local_universe_size": local_count,
            "requested_sample_size": VIRTUAL_A_SHARE_SAMPLE_SIZE,
            "legacy_pool": pool,
        }

    def _symbols_for_strategy_pool(self, pool: str) -> List[str]:
        return self._resolve_strategy_pool_symbols(pool)[0]

    def _active_accounts(self) -> List[tuple[Dict, object]]:
        accounts = self.get_accounts()
        active_accounts = []
        for acc in accounts:
            strategy_id = acc["strategy_id"]
            if self.strategy_version_store.get_active_version_id(strategy_id) or self.strategy_version_store.get_version(strategy_id):
                spec = self.strategy_version_store.resolve_strategy_spec(strategy_id)
            else:
                spec = STRATEGY_REGISTRY.get(strategy_id)
            if spec:
                active_accounts.append((acc, spec))
        return active_accounts

    def _symbols_with_data_on_day(self, symbols: List[str], target_date: str) -> tuple[List[str], List[str]]:
        available = []
        missing = []
        for symbol in symbols:
            try:
                cache_path = self.data_manager.get_cache_path(symbol)
                if not cache_path.exists():
                    missing.append(symbol)
                    continue
                dates = pd.read_parquet(cache_path, columns=["date"])
                if target_date in set(dates["date"].astype(str).tolist()):
                    available.append(symbol)
                else:
                    missing.append(symbol)
            except Exception:
                missing.append(symbol)
        return available, missing

    def _get_meta(self, cursor, key: str) -> Optional[str]:
        cursor.execute("SELECT value FROM execution_meta WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None

    def _set_meta(self, cursor, key: str, value: str) -> None:
        cursor.execute(
            "INSERT OR REPLACE INTO execution_meta (key, value) VALUES (?, ?)",
            (key, value),
        )

    def _should_refresh_universe(self, cursor) -> bool:
        return self._get_meta(cursor, "virtual_universe_version") != VIRTUAL_UNIVERSE_VERSION

    def _has_strategy_state(self, cursor) -> bool:
        for table in ("positions", "trade_log", "daily_stats"):
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            if cursor.fetchone()[0] > 0:
                return True
        return False

    def _clear_strategy_state(self, cursor, strategy_ids: List[str]) -> None:
        if not strategy_ids:
            return
        placeholders = ",".join("?" for _ in strategy_ids)
        cursor.execute(f"DELETE FROM positions WHERE strategy_id IN ({placeholders})", strategy_ids)
        cursor.execute(f"DELETE FROM trade_log WHERE strategy_id IN ({placeholders})", strategy_ids)
        cursor.execute(f"DELETE FROM daily_stats WHERE strategy_id IN ({placeholders})", strategy_ids)
        cursor.execute(f"DELETE FROM strategy_reports WHERE strategy_id IN ({placeholders})", strategy_ids)

    def _record_strategy_report(
        self,
        cursor,
        strategy_id: str,
        date: str,
        status: str,
        pool: str,
        pool_info: Dict[str, object],
        decision_info: Optional[Dict[str, object]] = None,
        message: str = "",
    ) -> None:
        decision_info = decision_info or {}
        selected_symbols = decision_info.get("selected_codes") or []
        if not selected_symbols and status == "bootstrapped":
            selected_symbols = []
        cursor.execute(
            """
            INSERT OR REPLACE INTO strategy_reports (
                strategy_id, date, status, pool, universe_label, universe_method, universe_size,
                raw_signal_count, selected_signal_count, selected_symbols, message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                strategy_id,
                date,
                status,
                pool,
                str(pool_info.get("universe_label") or ""),
                str(pool_info.get("universe_method") or ""),
                int(pool_info.get("loaded_symbols") or pool_info.get("available") or pool_info.get("requested") or 0),
                int(decision_info.get("raw_signal_count") or 0),
                int(decision_info.get("selected_signal_count") or len(selected_symbols) or 0),
                json.dumps(list(selected_symbols), ensure_ascii=False),
                message,
            ),
        )

    def _load_pool_data_for_day(self, pool_symbols: List[str], warmup_start: str, day: str) -> tuple[pd.DataFrame, Dict, Dict]:
        available_symbols, missing_on_day = self._symbols_with_data_on_day(pool_symbols, day)
        info = {
            "requested": len(pool_symbols),
            "available": len(available_symbols),
            "missing_on_day": missing_on_day[:20],
            "missing_on_day_count": len(missing_on_day),
            "dropped_for_history_gap": [],
            "dropped_for_history_gap_count": 0,
        }
        if not available_symbols:
            return pd.DataFrame(), {}, info

        try:
            df, sources = self.data_manager.get_stock_pool_data(available_symbols, warmup_start, day, allow_mock=False)
        except PoolDataFetchError as exc:
            failed_symbols = set(exc.failures.keys())
            retry_symbols = [symbol for symbol in available_symbols if symbol not in failed_symbols]
            info["dropped_for_history_gap"] = sorted(failed_symbols)[:20]
            info["dropped_for_history_gap_count"] = len(failed_symbols)
            if not retry_symbols:
                return pd.DataFrame(), {}, info
            df, sources = self.data_manager.get_stock_pool_data(retry_symbols, warmup_start, day, allow_mock=False)
        except DataFetchError as exc:
            info["dropped_for_history_gap"] = [exc.symbol]
            info["dropped_for_history_gap_count"] = 1
            return pd.DataFrame(), {}, info

        if df.empty:
            return pd.DataFrame(), sources, info
        day_symbols = set(df.loc[df["date"] == day, "stock_code"].astype(str).tolist())
        if day_symbols:
            df = df[df["stock_code"].astype(str).isin(day_symbols)].copy()
        info["loaded_symbols"] = len(day_symbols)
        return df, sources, info

    def _should_bootstrap_accounts(self, cursor, target_date: str) -> bool:
        cursor.execute("SELECT COUNT(*) FROM accounts")
        account_count = cursor.fetchone()[0]
        if account_count == 0:
            return False
        cursor.execute("SELECT MIN(last_update) FROM accounts")
        row = cursor.fetchone()
        min_last_update = row[0] if row and row[0] else ""
        if min_last_update >= target_date:
            return False
        cursor.execute("SELECT COUNT(*) FROM positions")
        position_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM trade_log")
        trade_count = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM accounts
            WHERE ABS(cash - start_value) < 0.01
              AND ABS(total_value - start_value) < 0.01
            """
        )
        untouched_accounts = cursor.fetchone()[0]
        return position_count == 0 and trade_count == 0 and untouched_accounts == account_count

    def _accounts_needing_initial_bootstrap(
        self,
        active_accounts: List[tuple[Dict, object]],
    ) -> List[tuple[Dict, object]]:
        return [
            (acc, spec)
            for acc, spec in active_accounts
            if not str(acc.get("last_update") or "").strip()
        ]

    def _bootstrap_accounts(
        self,
        cursor,
        target_date: str,
        active_accounts: List[tuple[Dict, object]],
        *,
        mode: str = "bootstrap",
        reset_state: bool = False,
    ) -> Dict:
        warmup_start = (datetime.strptime(target_date, "%Y-%m-%d") - timedelta(days=VIRTUAL_WARMUP_DAYS)).strftime("%Y-%m-%d")
        if reset_state:
            self._clear_strategy_state(cursor, [acc["strategy_id"] for acc, _ in active_accounts])
        pool_data_cache = {}
        pool_info = {}
        for pool in sorted({spec.pool for _, spec in active_accounts}):
            pool_symbols, selection_info = self._resolve_strategy_pool_symbols(pool, target_date, warmup_start)
            df, _, info = self._load_pool_data_for_day(pool_symbols, warmup_start, target_date)
            info.update(selection_info)
            pool_info[pool] = info
            if not df.empty:
                pool_data_cache[pool] = df

        reports = []
        for acc, spec in active_accounts:
            strategy_id = acc["strategy_id"]
            df = pool_data_cache.get(spec.pool)
            if df is None or df.empty:
                reports.append({
                    "strategy_id": strategy_id,
                    "status": "skipped",
                    "reason": f"{spec.pool} 股票池在 {target_date} 无可用真实行情",
                    "universe": pool_info.get(spec.pool, {}),
                })
                self._record_strategy_report(
                    cursor,
                    strategy_id,
                    target_date,
                    "skipped",
                    spec.pool,
                    pool_info.get(spec.pool, {}),
                    message=f"{spec.pool} 股票池在 {target_date} 无可用真实行情",
                )
                cursor.execute(
                    "UPDATE accounts SET last_update = ? WHERE strategy_id = ?",
                    (target_date, strategy_id),
                )
                continue

            try:
                df_with_signals = spec.func(df.copy())
                pos_manager = PositionManager(max_positions=5, strategy_spec=spec)
                target_weights = {}
                trading_days = sorted(day for day in df["date"].dropna().astype(str).unique().tolist() if day <= target_date)
                for day in trading_days:
                    day_data = df[df["date"] == day]
                    day_signals = df_with_signals[df_with_signals["date"] == day]
                    if day_data.empty or day_signals.empty:
                        continue
                    target_weights = pos_manager.generate_target_weights(
                        day,
                        day_data,
                        day_signals,
                        current_positions=None,
                    )

                target_day_data = df[df["date"] == target_date]
                selected = self._seed_positions_from_weights(
                    cursor,
                    strategy_id,
                    target_date,
                    target_weights,
                    target_day_data,
                    float(acc["start_value"] or acc["total_value"] or 100000.0),
                )
                reports.append({
                    "strategy_id": strategy_id,
                    "status": "bootstrapped" if selected else "cash",
                    "selected_symbols": selected,
                    "decision": pos_manager.last_decision_info,
                    "universe": pool_info.get(spec.pool, {}),
                    "message": "已按历史窗口选股并用目标日收盘价建仓" if selected else "历史窗口未形成持仓信号，账户保持现金",
                })
                self._record_strategy_report(
                    cursor,
                    strategy_id,
                    target_date,
                    "bootstrapped" if selected else "cash",
                    spec.pool,
                    pool_info.get(spec.pool, {}),
                    pos_manager.last_decision_info,
                    "已按历史窗口选股并用目标日收盘价建仓" if selected else "历史窗口未形成持仓信号，账户保持现金",
                )
            except Exception as exc:
                logger.error(f"Bootstrap failed for {strategy_id}: {exc}")
                reports.append({
                    "strategy_id": strategy_id,
                    "status": "failed",
                    "reason": str(exc),
                })
                self._record_strategy_report(
                    cursor,
                    strategy_id,
                    target_date,
                    "failed",
                    spec.pool,
                    pool_info.get(spec.pool, {}),
                    message=str(exc),
                )

        self._set_meta(cursor, "virtual_universe_version", VIRTUAL_UNIVERSE_VERSION)
        return {
            "status": "success",
            "message": f"已完成{'全市场样本刷新' if mode == 'universe_refresh' else '初始仿真建仓'}，目标日期 {target_date}",
            "date": target_date,
            "mode": mode,
            "pool_info": pool_info,
            "strategy_reports": reports,
        }

    def _seed_positions_from_weights(self, cursor, strategy_id: str, date: str, target_weights: Dict[str, float], day_data: pd.DataFrame, account_value: float) -> List[str]:
        cursor.execute("DELETE FROM positions WHERE strategy_id = ?", (strategy_id,))
        price_map = day_data.set_index("stock_code")["close"].to_dict() if not day_data.empty else {}
        row_map = day_data.set_index("stock_code", drop=False).to_dict(orient="index") if not day_data.empty else {}
        cash = float(account_value)
        selected = []

        for code, weight in sorted(target_weights.items(), key=lambda item: item[1], reverse=True):
            price = float(price_map.get(code, 0.0) or 0.0)
            if price <= 0:
                continue
            row = row_map.get(code, {})
            if self._trade_block_reason(row, "close", "buy") is not None:
                continue
            target_value = account_value * float(weight or 0.0) / (1.0 + VIRTUAL_FEE_RATE)
            shares = int(target_value / price / 100) * 100
            shares = self._cap_order_shares(row, shares)
            if shares <= 0:
                continue
            cost = shares * price
            fee = cost * VIRTUAL_FEE_RATE
            if cash < cost + fee:
                continue
            cash -= cost + fee
            cursor.execute(
                """
                INSERT OR REPLACE INTO positions (
                    strategy_id, symbol, shares, cost_price, current_price, entry_date, entry_price
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (strategy_id, code, shares, price, price, date, price),
            )
            cursor.execute(
                "INSERT INTO trade_log (strategy_id, date, symbol, side, price, shares, fee, msg) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (strategy_id, date, code, "BUY", price, shares, fee, "初始建仓：历史窗口选股，目标日收盘价成交"),
            )
            selected.append(code)

        final_pos_value = 0.0
        for code in selected:
            cursor.execute("SELECT shares, current_price FROM positions WHERE strategy_id = ? AND symbol = ?", (strategy_id, code))
            row = cursor.fetchone()
            if row:
                final_pos_value += float(row[0]) * float(row[1])
        final_total_value = cash + final_pos_value
        cursor.execute(
            "UPDATE accounts SET cash = ?, total_value = ?, last_update = ? WHERE strategy_id = ?",
            (cash, final_total_value, date, strategy_id),
        )
        cursor.execute(
            "INSERT OR REPLACE INTO daily_stats (strategy_id, date, total_value, cash) VALUES (?, ?, ?, ?)",
            (strategy_id, date, final_total_value, cash),
        )
        return selected

    def get_accounts(self) -> List[Dict]:
        conn = self._get_conn()
        try:
            # 获取账户基本信息
            accounts_df = pd.read_sql("SELECT * FROM accounts", conn)
            # 获取持仓信息用于快速统计
            positions_df = pd.read_sql("SELECT * FROM positions", conn)
            reports_df = pd.read_sql("SELECT * FROM strategy_reports", conn)
            reports = {
                row["strategy_id"]: row
                for _, row in reports_df.iterrows()
            } if not reports_df.empty else {}
            
            res = []
            for _, acc in accounts_df.iterrows():
                strategy_id = acc['strategy_id']
                report = reports.get(strategy_id)
                # 计算今日盈亏 (简化版：由于我们还没有今日价格，这里先返回总资产)
                # 前端会根据 start_value 计算累计盈亏
                
                # 获取前 3 大重仓
                strat_pos = positions_df[positions_df['strategy_id'] == strategy_id]
                if not strat_pos.empty:
                    strat_pos = strat_pos.copy()
                    strat_pos["market_value"] = strat_pos["shares"] * strat_pos["current_price"]
                    strat_pos["weight"] = strat_pos["market_value"] / float(acc["total_value"] or 1.0)
                    strat_pos = strat_pos.sort_values('market_value', ascending=False)
                top_3 = strat_pos.head(3)['symbol'].tolist() if not strat_pos.empty else []
                top_details = []
                for _, pos in (strat_pos.head(5).iterrows() if not strat_pos.empty else []):
                    top_details.append({
                        "symbol": pos["symbol"],
                        "name": self.data_manager.get_stock_name(pos["symbol"]),
                        "shares": int(pos["shares"]),
                        "cost_price": float(pos["cost_price"]),
                        "current_price": float(pos["current_price"]),
                        "market_value": float(pos["market_value"]),
                        "weight": float(pos["weight"]),
                        "entry_date": pos.get("entry_date"),
                        "entry_price": float(pos["entry_price"]) if pd.notna(pos.get("entry_price")) else None,
                    })
                start_value = float(acc["start_value"] or 0.0)
                total_value = float(acc["total_value"] or 0.0)
                return_rate = (total_value / start_value - 1) * 100 if start_value > 0 else 0.0
                
                res.append({
                    "strategy_id": strategy_id,
                    "name": acc['strategy_name'],
                    "total_value": acc['total_value'],
                    "cash": acc['cash'],
                    "start_value": acc['start_value'],
                    "last_update": acc['last_update'],
                    "top_holdings": top_3,
                    "top_holding_details": top_details,
                    "strategy_pool": report["pool"] if report is not None else None,
                    "universe_label": report["universe_label"] if report is not None else None,
                    "universe_method": report["universe_method"] if report is not None else None,
                    "universe_size": int(report["universe_size"]) if report is not None and pd.notna(report["universe_size"]) else None,
                    "raw_signal_count": int(report["raw_signal_count"]) if report is not None and pd.notna(report["raw_signal_count"]) else None,
                    "selected_signal_count": int(report["selected_signal_count"]) if report is not None and pd.notna(report["selected_signal_count"]) else None,
                    "empty_reason": report["message"] if report is not None else None,
                    "return_rate": return_rate
                })
            
            # 按收益率排序 (龟兔赛跑排名)
            return sorted(res, key=lambda x: x['return_rate'], reverse=True)
        finally:
            conn.close()

    def get_trade_log(
        self,
        strategy_id: Optional[str] = None,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict]:
        limit = int(limit or 100)
        offset = int(offset or 0)
        if limit < 1:
            limit = 1
        if limit > 2000:
            limit = 2000
        if offset < 0:
            offset = 0
        conn = self._get_conn()
        try:
            query = "SELECT * FROM trade_log"
            params = []
            if strategy_id:
                query += " WHERE strategy_id = ?"
                params.append(strategy_id)
            query += " ORDER BY date DESC, id DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])
            
            df = pd.read_sql(query, conn, params=params)
            return df.to_dict(orient='records')
        finally:
            conn.close()

    def execute_daily(self) -> Dict:
        """
        执行模拟盘撮合，支持追赶模式（自动补齐所有缺失交易日）。
        """
        # 1. 确定当前进度与终点
        target_date = self.data_manager.get_last_trading_day()
        conn = self._get_conn()
        cursor = conn.cursor()
        active_accounts = self._active_accounts()
        if self._should_bootstrap_accounts(cursor, target_date):
            result = self._bootstrap_accounts(cursor, target_date, active_accounts)
            conn.commit()
            conn.close()
            return result
        bootstrap_accounts = self._accounts_needing_initial_bootstrap(active_accounts)
        if bootstrap_accounts:
            result = self._bootstrap_accounts(
                cursor,
                target_date,
                bootstrap_accounts,
                mode="bootstrap",
                reset_state=True,
            )
            conn.commit()
            conn.close()
            return result
        if active_accounts and self._should_refresh_universe(cursor):
            if not self._has_strategy_state(cursor):
                result = self._bootstrap_accounts(
                    cursor,
                    target_date,
                    active_accounts,
                    mode="universe_refresh",
                    reset_state=True,
                )
                conn.commit()
                conn.close()
                return result
            self._set_meta(cursor, "virtual_universe_version", VIRTUAL_UNIVERSE_VERSION)

        cursor.execute("SELECT MIN(last_update) FROM accounts") # 取最慢的那个
        row = cursor.fetchone()
        last_update = row[0] if row and row[0] else "2026-04-22"
        
        if last_update >= target_date:
            conn.close()
            return {"status": "skipped", "message": f"所有策略均已更新至最新交易日 ({target_date})。", "date": target_date}

        # 2. 获取期间所有交易日 (使用 DataManager 或 Baostock)
        # 这里简单起见，从 DataManager 获取 list_local_codes("a_share") 随便一个文件的索引
        try:
            sample_code = self.data_manager.list_local_codes("a_share")[0]
            df_sample = pd.read_parquet(self.data_manager.get_cache_path(sample_code))
            missing_days = df_sample[(df_sample['date'] > last_update) & (df_sample['date'] <= target_date)]['date'].unique().tolist()
            missing_days.sort()
        except Exception as e:
            logger.error(f"Failed to calculate missing days: {e}")
            conn.close()
            raise RuntimeError(f"无法确定待补齐的交易日序列: {e}")

        if not missing_days:
            conn.close()
            return {"status": "skipped", "message": "未发现待补齐的交易日数据。", "date": target_date}

        logger.info(f"检测到待补齐日期序列: {missing_days}")
        
        daily_reports = []
        skipped_reports = []

        # 3. 循环执行每一天
        for day in missing_days:
            logger.info(f">>> 正在执行日期补齐: {day} ...")

            active_accounts = self._active_accounts()

            warmup_start = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=VIRTUAL_WARMUP_DAYS)).strftime("%Y-%m-%d")
            pool_data_cache = {}
            skipped_pools = {}
            for pool in sorted({spec.pool for _, spec in active_accounts}):
                pool_symbols, selection_info = self._resolve_strategy_pool_symbols(pool, day, warmup_start)
                if not pool_symbols:
                    logger.warning(f"日期 {day} 策略池 {pool} 未找到可用标的，跳过该池。")
                    skipped_pools[pool] = "未找到可用标的"
                    continue

                df, _, pool_info = self._load_pool_data_for_day(pool_symbols, warmup_start, day)
                pool_info.update(selection_info)
                if pool_info.get("missing_on_day_count") or pool_info.get("dropped_for_history_gap_count"):
                    skipped_pools[pool] = pool_info
                if not df.empty:
                    pool_data_cache[pool] = df

            processed_strategies = 0
            pending_shadow_observations = []
            for acc, spec in active_accounts:
                strategy_id = acc['strategy_id']

                try:
                    df = pool_data_cache.get(spec.pool)
                    if df is None or df.empty:
                        continue

                    if str(acc.get("last_update") or "") >= day:
                        continue

                    # 计算信号
                    df_with_signals = spec.func(df.copy())
                    day_signals = df_with_signals[df_with_signals['date'] == day]
                    day_data = df[df['date'] == day]

                    # 获取当前真实持仓
                    cursor.execute("""
                        SELECT symbol, shares, cost_price, current_price, entry_date, entry_price
                        FROM positions
                        WHERE strategy_id = ?
                    """, (strategy_id,))
                    current_pos_rows = cursor.fetchall()
                    current_positions = {}
                    initial_holdings = {}
                    for row in current_pos_rows:
                        symbol, shares, cost_price, current_price, entry_date, entry_price = row
                        resolved_entry_date = entry_date or acc.get("last_update") or day
                        resolved_entry_price = entry_price if entry_price is not None else cost_price
                        current_positions[symbol] = MockPosition(
                            shares,
                            cost_price,
                            current_price=current_price,
                            entry_date=resolved_entry_date,
                            entry_price=resolved_entry_price,
                        )
                        initial_holdings[symbol] = HoldingInfo(
                            code=symbol,
                            entry_date=resolved_entry_date,
                            entry_price=float(resolved_entry_price or 0.0),
                        )

                    # 生成目标权重
                    pos_manager = PositionManager(max_positions=5, strategy_spec=spec)
                    pos_manager.seed_holdings(initial_holdings)
                    target_weights = pos_manager.generate_target_weights(day, day_data, day_signals, current_positions=current_positions)

                    # 撮合：计算 Target vs Current (差额调仓)
                    self._match_orders(cursor, strategy_id, day, target_weights, current_positions, day_data, acc['cash'], acc['total_value'])
                    self._record_strategy_report(
                        cursor,
                        strategy_id,
                        day,
                        "traded" if target_weights else "cash",
                        spec.pool,
                        skipped_pools.get(spec.pool, {}) if isinstance(skipped_pools.get(spec.pool), dict) else {"requested": len(day_data["stock_code"].unique())},
                        pos_manager.last_decision_info,
                        "已按最新信号调仓" if target_weights else "当日未形成持仓信号，账户保持现金",
                    )
                    
                    # 记录每日快照
                    cursor.execute("SELECT cash, total_value FROM accounts WHERE strategy_id = ?", (strategy_id,))
                    row = cursor.fetchone()
                    if row:
                        cursor.execute("""
                            INSERT OR REPLACE INTO daily_stats (strategy_id, date, total_value, cash)
                            VALUES (?, ?, ?, ?)
                        """, (strategy_id, day, row[1], row[0]))
                        if self.strategy_version_store.get_version(strategy_id):
                            pending_shadow_observations.append(
                                {
                                    "version_id": strategy_id,
                                    "date": day,
                                    "total_value": float(row[1] or 0.0),
                                    "cash": float(row[0] or 0.0),
                                    "selected_symbols": list(target_weights.keys()),
                                }
                            )

                    processed_strategies += 1

                except Exception as e:
                    logger.error(f"Strategy {strategy_id} execution failed on {day}: {e}")
                    failure = {
                        "date": day,
                        "strategy_id": strategy_id,
                        "reason": str(e),
                    }
                    self._record_strategy_report(
                        cursor,
                        strategy_id,
                        day,
                        "failed",
                        spec.pool,
                        skipped_pools.get(spec.pool, {})
                        if isinstance(skipped_pools.get(spec.pool), dict)
                        else {
                            "requested": len(
                                pool_data_cache.get(spec.pool, pd.DataFrame()).get("stock_code", [])
                            )
                        },
                        message=str(e),
                    )
                    skipped_reports.append(failure)

            conn.commit()
            for observation in pending_shadow_observations:
                self.strategy_version_store.record_shadow_observation(**observation)
            if processed_strategies > 0:
                daily_reports.append(day)
            else:
                skipped_reports.append({
                    "date": day,
                    "reason": "no_strategy_processed",
                    "skipped_pools": skipped_pools,
                })

        conn.close()
        failed_strategies = [
            item
            for item in skipped_reports
            if isinstance(item, dict) and item.get("strategy_id") and item.get("reason")
        ]
        if not daily_reports:
            if failed_strategies:
                return {
                    "status": "failed",
                    "message": "没有策略执行成功，至少一个策略运行失败。",
                    "date": last_update,
                    "processed_days": [],
                    "skipped_days": skipped_reports,
                    "failed_strategies": failed_strategies,
                }
            return {
                "status": "skipped",
                "message": "没有可执行交易日，策略池数据未完全就绪或无可用策略。",
                "date": last_update,
                "processed_days": [],
                "skipped_days": skipped_reports,
            }
        return {
            "status": "partial" if failed_strategies else "success",
            "message": f"成功追赶 {len(daily_reports)} 个交易日", 
            "date": daily_reports[-1] if daily_reports else last_update,
            "processed_days": daily_reports,
            "skipped_days": skipped_reports,
            "failed_strategies": failed_strategies,
        }

    def _match_orders(self, cursor, strategy_id, date, target_weights, current_positions, day_data, cash, total_value):
        """
        专业差额调仓逻辑：计算目标股数与当前股数的差值，优先执行卖出以释放资金。
        """
        price_map = day_data.set_index('stock_code')['close'].to_dict()
        row_map = day_data.set_index("stock_code", drop=False).to_dict(orient="index")

        # 先逐日盯市。即使当天没有成交，持仓价格、账户净值和 daily_stats 也必须推进。
        for code, pos in current_positions.items():
            price = price_map.get(code)
            if price and price > 0:
                pos.current_price = price
                cursor.execute(
                    "UPDATE positions SET current_price = ? WHERE strategy_id = ? AND symbol = ?",
                    (price, strategy_id, code),
                )
        
        # 1. 计算当前最新持仓市值 (按今日收盘价)
        current_market_value = 0
        for code, pos in current_positions.items():
            price = price_map.get(code, pos.current_price)
            current_market_value += pos.shares * price
        
        # 实时总资产 (今日收盘价计算)
        live_total_value = cash + current_market_value
        
        # 2. 计算目标持仓股数
        target_shares = {}
        for code, weight in target_weights.items():
            price = price_map.get(code)
            if not price or price <= 0: continue

            target_val = live_total_value * weight / (1.0 + VIRTUAL_FEE_RATE)
            # 向上取整一手 (100股)，或者按权重严谨计算
            shares = int(target_val / price / 100) * 100
            if shares > 0:
                target_shares[code] = shares

        # 3. 找出差异并执行
        # A. 卖出逻辑 (当前有但目标无，或者当前 > 目标)
        sell_orders = []
        buy_orders = []
        
        for code, pos in current_positions.items():
            curr_s = pos.shares
            targ_s = target_shares.get(code, 0)
            if curr_s > targ_s:
                sell_orders.append((code, curr_s - targ_s))

        for code, targ_s in target_shares.items():
            curr_s = current_positions.get(code).shares if code in current_positions else 0
            if targ_s > curr_s:
                buy_orders.append((code, targ_s - curr_s))
        
        # 执行卖出
        for code, diff_shares in sell_orders:
            price = price_map.get(code)
            if not price: continue
            row = row_map.get(code, {})
            pos = current_positions.get(code)
            if pos and self._is_t1_sell_blocked(pos, date):
                logger.info(f"T+1 blocks {strategy_id} from selling {code} on {date}")
                continue
            block_reason = self._trade_block_reason(row, "close", "sell")
            if block_reason is not None:
                logger.info(f"Tradability blocks {strategy_id} SELL {code} on {date}: {block_reason}")
                continue
            filled_shares = self._cap_order_shares(row, diff_shares)
            if filled_shares <= 0:
                logger.info(f"Capacity blocks {strategy_id} SELL {code} on {date}: requested={diff_shares}")
                continue
            
            amount = filled_shares * price
            fee = amount * VIRTUAL_FEE_RATE
            cash += (amount - fee)
            
            # 更新/删除持仓
            new_shares = current_positions[code].shares - filled_shares if code in current_positions else 0
            if new_shares > 0:
                cursor.execute("UPDATE positions SET shares = ?, current_price = ? WHERE strategy_id = ? AND symbol = ?",
                             (new_shares, price, strategy_id, code))
                current_positions[code].shares = new_shares
                current_positions[code].current_price = price
            else:
                cursor.execute("DELETE FROM positions WHERE strategy_id = ? AND symbol = ?", (strategy_id, code))
                current_positions.pop(code, None)
            
            fill_note = "部分成交" if filled_shares < diff_shares else "成交"
            cursor.execute("INSERT INTO trade_log (strategy_id, date, symbol, side, price, shares, fee, msg) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (strategy_id, date, code, 'SELL', price, filled_shares, fee, f"调仓减仓{fill_note} (剩余 {new_shares})"))

        # 执行买入 (受限于可用现金)
        for code, diff_shares in buy_orders:
            price = price_map.get(code)
            if not price: continue
            row = row_map.get(code, {})
            block_reason = self._trade_block_reason(row, "close", "buy")
            if block_reason is not None:
                logger.info(f"Tradability blocks {strategy_id} BUY {code} on {date}: {block_reason}")
                continue
            filled_shares = self._cap_order_shares(row, diff_shares)
            if filled_shares <= 0:
                logger.info(f"Capacity blocks {strategy_id} BUY {code} on {date}: requested={diff_shares}")
                continue
            
            cost = filled_shares * price
            fee = cost * VIRTUAL_FEE_RATE
            total_cost = cost + fee
            
            if cash >= total_cost:
                cash -= total_cost
                # 更新/新增持仓
                if code in current_positions:
                    # 摊薄成本 (简单算术平均)
                    old_pos = current_positions[code]
                    new_total_shares = old_pos.shares + filled_shares
                    new_avg_cost = (old_pos.shares * old_pos.cost_price + cost) / new_total_shares
                    cursor.execute("UPDATE positions SET shares = ?, cost_price = ?, current_price = ? WHERE strategy_id = ? AND symbol = ?",
                                 (new_total_shares, new_avg_cost, price, strategy_id, code))
                    old_pos.shares = new_total_shares
                    old_pos.cost_price = new_avg_cost
                    old_pos.current_price = price
                else:
                    cursor.execute("""
                        INSERT INTO positions (
                            strategy_id, symbol, shares, cost_price, current_price, entry_date, entry_price
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (strategy_id, code, filled_shares, price, price, date, price))
                    current_positions[code] = MockPosition(
                        filled_shares,
                        price,
                        current_price=price,
                        entry_date=date,
                        entry_price=price,
                    )
                
                fill_note = "部分成交" if filled_shares < diff_shares else "成交"
                cursor.execute("INSERT INTO trade_log (strategy_id, date, symbol, side, price, shares, fee, msg) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                             (strategy_id, date, code, 'BUY', price, filled_shares, fee, f"调仓增仓{fill_note}"))
            else:
                # 现金不足，跳过或部分成交
                logger.warning(f"Cash insufficient for {strategy_id} to buy {code}: needs {total_cost:.2f}, has {cash:.2f}")

        # 4. 更新账户状态
        final_pos_value = sum(
            pos.shares * (price_map.get(code, pos.current_price) or pos.current_price)
            for code, pos in current_positions.items()
        )
        final_total_value = cash + final_pos_value
        
        cursor.execute("UPDATE accounts SET cash = ?, total_value = ?, last_update = ? WHERE strategy_id = ?",
                     (cash, final_total_value, date, strategy_id))

    def _safe_float(self, value) -> Optional[float]:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _is_st_stock(self, row: Dict) -> bool:
        raw_is_st = row.get("is_st")
        if raw_is_st is not None and not pd.isna(raw_is_st):
            text = str(raw_is_st).strip().lower()
            if text in {"1", "1.0", "true", "yes", "y", "st"}:
                return True
            if text in {"0", "0.0", "false", "no", "n", ""}:
                return False
        return "ST" in str(row.get("stock_name", "") or "").upper() or "退" in str(row.get("stock_name", "") or "")

    def _limit_threshold(self, row: Dict) -> float:
        if self._is_st_stock(row):
            return 0.045
        code = str(row.get("stock_code", "") or "")
        if code.startswith(("300", "301", "688", "689")):
            return 0.195
        if code.startswith(("43", "83", "87", "88", "92")):
            return 0.295
        return 0.095

    def _prev_close(self, row: Dict) -> Optional[float]:
        prev_close = self._safe_float(row.get("prev_close"))
        if prev_close and prev_close > 0:
            return prev_close

        close_price = self._safe_float(row.get("close"))
        change = self._safe_float(row.get("change"))
        if close_price is not None and change is not None:
            inferred = close_price - change
            if inferred > 0:
                return inferred

        pct_chg = self._safe_float(row.get("pct_chg"))
        if close_price is not None and pct_chg is not None:
            denominator = 1.0 + pct_chg / 100.0
            if denominator > 0:
                inferred = close_price / denominator
                if inferred > 0:
                    return inferred
        return None

    def _hits_price_limit(self, row: Dict, price_field: str, direction: str) -> bool:
        prev_close = self._prev_close(row)
        price = self._safe_float(row.get(price_field))
        if prev_close is None or price is None:
            return False
        move_pct = (price - prev_close) / prev_close
        threshold = self._limit_threshold(row)
        if direction == "up":
            return move_pct >= threshold
        if direction == "down":
            return move_pct <= -threshold
        return False

    def _trade_block_reason(self, row: Dict, price_field: str, side: str) -> Optional[str]:
        price = self._safe_float(row.get(price_field))
        if price is None or price <= 0:
            return "invalid_price"

        tradestatus = row.get("tradestatus")
        if tradestatus is not None and not pd.isna(tradestatus):
            status = str(tradestatus).strip().lower()
            if status and status not in {"1", "1.0", "true", "trading", "trade", "active", "open", "交易", "正常"}:
                return "halted"

        volume = self._safe_float(row.get("volume"))
        if volume is not None and volume <= 0:
            return "no_volume"

        if side == "buy" and self._hits_price_limit(row, price_field, "up"):
            return "limit_up"
        if side == "sell" and self._hits_price_limit(row, price_field, "down"):
            return "limit_down"
        return None

    def _cap_order_shares(self, row: Dict, requested_shares: int) -> int:
        requested_shares = int(requested_shares or 0)
        if requested_shares <= 0:
            return 0
        volume = self._safe_float(row.get("volume"))
        if volume is None:
            return requested_shares
        if volume <= 0:
            return 0
        max_shares = int((volume * VIRTUAL_MAX_VOLUME_PARTICIPATION) // 100) * 100
        if max_shares <= 0:
            return 0
        return min(requested_shares, max_shares)

    def _is_t1_sell_blocked(self, pos, date: str) -> bool:
        return bool(getattr(pos, "entry_date", None) and pos.entry_date == date)

    def get_equity_history(self, strategy_id: str) -> List[Dict]:
        conn = self._get_conn()
        try:
            df = pd.read_sql("SELECT date, total_value FROM daily_stats WHERE strategy_id = ? ORDER BY date ASC", conn, params=(strategy_id,))
            return df.to_dict(orient='records')
        finally:
            conn.close()

    def get_performance_stats(self, strategy_id: str) -> Dict:
        conn = self._get_conn()
        try:
            df = pd.read_sql("SELECT date, total_value FROM daily_stats WHERE strategy_id = ? ORDER BY date ASC", conn, params=(strategy_id,))
            if df.empty: return {}
            
            # 计算指标
            df['returns'] = df['total_value'].pct_change()
            
            # 累计收益
            total_return = (df['total_value'].iloc[-1] / df['total_value'].iloc[0] - 1)
            
            # 年化收益 (假设 252 交易日)
            days = len(df)
            ann_return = (1 + total_return) ** (252 / days) - 1 if days > 0 else 0
            
            # 夏普比率 (无风险利率 2%)
            rf = 0.02 / 252
            sharpe = (df['returns'].mean() - rf) / df['returns'].std() * (252**0.5) if df['returns'].std() > 0 else 0
            
            # 最大回撤
            df['cummax'] = df['total_value'].cummax()
            df['drawdown'] = (df['total_value'] / df['cummax'] - 1)
            max_drawdown = df['drawdown'].min()
            
            return {
                "total_return": total_return * 100,
                "annualized_return": ann_return * 100,
                "sharpe_ratio": sharpe,
                "max_drawdown": max_drawdown * 100,
                "win_rate": (df['returns'] > 0).mean() * 100,
                "volatility": df['returns'].std() * (252**0.5) * 100
            }
        finally:
            conn.close()

def random_sample_if_needed(lst, n):
    import random
    if len(lst) <= n: return lst
    return random.sample(lst, n)

class MockPosition:
    def __init__(self, shares, cost_price, current_price=None, entry_date=None, entry_price=None):
        self.shares = shares
        self.cost_price = cost_price
        self.current_price = current_price if current_price is not None else cost_price
        self.entry_date = entry_date
        self.entry_price = entry_price if entry_price is not None else cost_price
