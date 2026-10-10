"""Versioned paper accounts using the exact BacktestEngine daily ledger.

Legacy SQLite is never opened by this service. Account/day updates are transactional.
"""
import dataclasses
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from engine import BacktestEngine, Portfolio, Position, Lot
from position_manager import PositionManager
from research_contracts import ENGINE_VERSION, RUNTIME_DIR, TradingCalendar, persist_snapshot, DataContractError
from strategy_registry import STRATEGY_REGISTRY


def dump_engine(engine, pending):
    return {"engine_config": {"stock_stop_loss": engine.stock_stop_loss, "take_profit": engine.take_profit, "cost_model": dataclasses.asdict(engine.cost_model)}, "cash": engine.portfolio.cash, "initial_capital": engine.initial_capital,
            "positions": {c: dataclasses.asdict(p) for c, p in engine.portfolio.positions.items()},
            "dividend_receivables": engine.portfolio.dividend_receivables,
            "history": engine.portfolio.history, "trades": engine.trades, "pending": pending,
            "cost_stats": engine.cost_stats, "execution_stats": engine.execution_stats,
            "turnover_amount": engine.turnover_amount, "round_trips": engine.round_trips,
            "open_round_trips": engine._open_round_trips}


def restore_engine(state):
    config = dict(state.get("engine_config", {}))
    if "cost_model" in config:
        from engine import CostModel
        config["cost_model"] = CostModel(**config["cost_model"])
    engine = BacktestEngine(initial_capital=state["initial_capital"], **config)
    engine._reset_diagnostics()
    engine.portfolio.cash = state["cash"]
    engine.portfolio.history = state["history"]
    engine.portfolio.dividend_receivables = state.get("dividend_receivables", [])
    for code, value in state["positions"].items():
        value = dict(value)
        value["lots"] = [Lot(**lot) for lot in value["lots"]]
        engine.portfolio.positions[code] = Position(**value)
    for attr in ["trades", "cost_stats", "execution_stats", "turnover_amount", "round_trips"]:
        setattr(engine, attr, state[attr])
    engine._open_round_trips = state["open_round_trips"]
    return engine


class VirtualTradingV2:
    def __init__(self, manager, execution_data, version_store, pools, path=None, calendar=None):
        self.manager, self.execution_data, self.version_store, self.pools = manager, execution_data, version_store, pools
        self.path = Path(path or RUNTIME_DIR / "virtual_v2.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.calendar = calendar or TradingCalendar()
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS accounts_v2 (strategy_id TEXT PRIMARY KEY, name TEXT, version_id TEXT, symbols TEXT, last_update TEXT, state TEXT, snapshot_id TEXT)")

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def get_accounts(self):
        with self.connect() as conn:
            records = conn.execute("SELECT * FROM accounts_v2 ORDER BY strategy_id").fetchall()
        accounts = []
        for row in records:
            state = json.loads(row["state"])
            engine = restore_engine(state)
            value = engine.portfolio.total_value
            accounts.append({"strategy_id": row["strategy_id"], "account_id": f"v2:{row['strategy_id']}",
                             "engine_version": ENGINE_VERSION, "name": row["name"], "cash": engine.portfolio.cash,
                             "total_value": value, "start_value": engine.initial_capital, "last_update": row["last_update"],
                             "return_rate": value / engine.initial_capital - 1, "top_holdings": list(engine.portfolio.positions),
                             "data_snapshot_id": row["snapshot_id"], "strategy_version": row["version_id"],
                             "top_holding_details": [{"symbol": c, "name": p.stock_name, "shares": p.quantity, "cost_price": p.avg_price, "current_price": p.market_value / p.quantity, "market_value": p.market_value} for c,p in engine.portfolio.positions.items()]})
        return accounts

    def _state(self, strategy_id):
        with self.connect() as conn:
            row = conn.execute("SELECT state FROM accounts_v2 WHERE strategy_id=?", (strategy_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def get_trade_log(self, strategy_id=None, limit=100, offset=0):
        trades = []
        for acc in self.get_accounts():
            if strategy_id and strategy_id != acc["strategy_id"]:
                continue
            state = self._state(acc["strategy_id"])
            for i, t in enumerate(state["trades"]):
                trades.append({**t, "id": i, "strategy_id": acc["strategy_id"], "symbol": t["stock_code"], "shares": t["qty"], "fee": t["cost"], "msg": "daily-v2 shared ledger"})
        trades.sort(key=lambda t: (t["date"], t["strategy_id"], t["id"]), reverse=True)
        return trades[max(0, offset):max(0, offset) + max(1, min(limit, 1000))]

    def get_equity_history(self, strategy_id):
        state = self._state(strategy_id)
        return [{"date": r["date"], "total_value": r["total_value"]} for r in state["history"]] if state else []

    def get_performance_stats(self, strategy_id):
        state = self._state(strategy_id)
        if not state or not state["history"]:
            return {}
        summary = restore_engine(state)._generate_report()["summary"]
        return {"total_return": summary["final_value"] / summary["initial_capital"] - 1,
                "annualized_return": summary["annual_return"], "sharpe_ratio": summary["sharpe_ratio"],
                "max_drawdown": summary["max_drawdown"], "win_rate": summary["win_rate"], "volatility": 0}

    def execute_daily(self):
        target = self.calendar.latest_completed()
        reports = []
        for strategy_id, registered in STRATEGY_REGISTRY.items():
            with self.connect() as conn:
                row = conn.execute("SELECT * FROM accounts_v2 WHERE strategy_id=?", (strategy_id,)).fetchone()
            if row and row["last_update"] >= target:
                continue
            try:
                spec = self.version_store.resolve_strategy_spec(strategy_id)
                version = self.version_store.get_active_version_id(strategy_id)
                if row and row["version_id"] != version:
                    archive_id = strategy_id + "@" + str(row["version_id"] or "builtin") + "@" + row["last_update"]
                    with self.connect() as conn:
                        conn.execute("UPDATE accounts_v2 SET strategy_id=?, name=name || '（已归档）' WHERE strategy_id=?", (archive_id, strategy_id))
                    row = None
                if spec is None:
                    raise DataContractError("策略未注册")
                if spec.requires_artifact:
                    from factor_lab.strategy import get_factor_lab_artifact_readiness
                    pinned = self.version_store.get_version(version) if version else None
                    artifact_dir = Path(pinned["artifact_ref"]) if pinned else None
                    readiness = get_factor_lab_artifact_readiness(artifact_dir) if artifact_dir else get_factor_lab_artifact_readiness()
                    if not readiness.get("ready"):
                        raise DataContractError("ML产物尚未通过causal-wf-v2评估")
                last = row["last_update"] if row else target
                symbols = json.loads(row["symbols"]) if row else list(self.pools.get(spec.pool, self.pools.get("core", [])))
                if not symbols:
                    raise DataContractError("没有股票池")
                warmup = (datetime.strptime(last, "%Y-%m-%d") - timedelta(days=400)).strftime("%Y-%m-%d")
                df, sources = self.manager.get_stock_pool_data(symbols, warmup, target, allow_mock=False)
                df = self.execution_data.prepare(df)
                signals = spec.func(df)
                pos_manager = PositionManager(max_positions=5, weight_mode="equal", max_hold_days=spec.default_max_hold_days, strategy_spec=spec)
                pos_manager.policy._observed_dates = self.calendar.dates(warmup, last)
                if row:
                    state = json.loads(row["state"])
                    from position_manager import HoldingInfo
                    pos_manager.seed_holdings({c: HoldingInfo(**h) for c,h in state.get("policy_holdings", {}).items()})
                    engine = restore_engine(state)
                    pending = state["pending"]
                    days = self.calendar.dates(last, target)[1:]
                else:
                    engine = BacktestEngine(take_profit=spec.default_take_profit)
                    engine._reset_diagnostics()
                    pending = None
                    days = [target]
                for day in days:
                    bars = df[df.date == day]
                    if set(bars.stock_code) != set(symbols):
                        raise DataContractError(f"{day} 数据不完整，账户停留在上一完整交易日")
                    if row:
                        engine.step(day, bars, pending)
                    else:
                        engine.portfolio.record_state(day, [])
                    pending = pos_manager.generate_target_weights(day, bars, signals[signals.date == day], current_positions=engine.portfolio.positions)
                    snapshot = persist_snapshot(df[df.date <= day], {"strategy_id": strategy_id, "strategy_version": version}, {"symbols": symbols, "frozen_at": last})
                    state = dump_engine(engine, pending)
                    state["policy_holdings"] = {c: dataclasses.asdict(h) for c,h in pos_manager.holdings.items()}
                    with self.connect() as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        current = conn.execute("SELECT last_update FROM accounts_v2 WHERE strategy_id=?", (strategy_id,)).fetchone()
                        if current and current[0] >= day:
                            break
                        conn.execute("INSERT OR REPLACE INTO accounts_v2 VALUES (?,?,?,?,?,?,?)", (strategy_id, spec.name, version, json.dumps(symbols), day, json.dumps(state, allow_nan=False), snapshot))
                    reports.append({"strategy_id": strategy_id, "date": day, "status": "updated"})
                    row = {"last_update": day}
            except Exception as exc:
                reports.append({"strategy_id": strategy_id, "date": target, "status": "blocked", "error": str(exc)})
        blocked = [r for r in reports if r["status"] == "blocked"]
        return {"status": "partial" if blocked else "succeeded", "date": target, "engine_version": ENGINE_VERSION,
                "reports": reports, "blocked_accounts": len(blocked), "message": "旧账户保持原账；新版账户按完整日线逐日撮合。"}
