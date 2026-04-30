from types import SimpleNamespace

import pandas as pd

import virtual_trading_manager as vtm_module
from virtual_trading_manager import VirtualTradingManager


def _spec(pool="core", strategy_func=None, signal_type="stateful", holding_policy="sell_on_minus_one"):
    def default_strategy_func(df):
        out = df.copy()
        out["signal"] = 0
        out["score"] = 0.0
        return out

    resolved_func = strategy_func or default_strategy_func

    return SimpleNamespace(
        pool=pool,
        func=resolved_func,
        signal_type=signal_type,
        holding_policy=holding_policy,
        default_max_hold_days=None,
        default_take_profit=None,
        execution_mode="next_open_rebalance",
    )


class FakeDataManager:
    def __init__(self, tmp_path, close_price=10.0, local_codes=None, selected_codes=None):
        self.sample_path = tmp_path / "000001_full_history.parquet"
        pd.DataFrame({"date": ["2026-01-01", "2026-01-02"]}).to_parquet(self.sample_path, index=False)
        self.close_price = close_price
        self.pool_calls = []
        self.local_codes = local_codes or ["000001"]
        self.selected_codes = selected_codes or self.local_codes

    def get_last_trading_day(self):
        return "2026-01-02"

    def list_local_codes(self, asset_type="a_share"):
        if asset_type == "etf":
            return ["510300", "510500", "510880"]
        return list(self.local_codes)

    def select_local_a_share_symbols(self, sample_size, min_end_date=None, min_start_date=None):
        return list(self.selected_codes)[:sample_size]

    def get_last_symbol_selection_metadata(self):
        return {"selection_method": "test_deterministic_universe"}

    def get_cache_path(self, symbol):
        return self.sample_path

    def get_stock_name(self, symbol):
        return f"名称{symbol}"

    def check_data_integrity(self, symbols, target_date):
        return True, "ok"

    def get_stock_pool_data(self, symbols, start_date, end_date, allow_mock=True):
        self.pool_calls.append(tuple(symbols))
        rows = [
            {
                "date": "2026-01-02",
                "stock_code": symbol,
                "stock_name": symbol,
                "open": self.close_price,
                "high": self.close_price,
                "low": self.close_price,
                "close": self.close_price,
                "volume": 1000.0,
                "amount": 1000.0 * self.close_price,
                "pct_chg": 0.0,
            }
            for symbol in symbols
        ]
        return pd.DataFrame(rows), {symbol: "CACHE" for symbol in symbols}


def _buy_signal(symbol="000001", score=1.0):
    def strategy_func(df):
        out = df.copy()
        out["signal"] = 0
        out["score"] = 0.0
        out.loc[out["stock_code"] == symbol, "signal"] = 1
        out.loc[out["stock_code"] == symbol, "score"] = score
        return out

    return strategy_func


def _insert_account(manager, strategy_id, last_update="2026-01-01", cash=100000.0, total_value=100000.0):
    conn = manager._get_conn()
    try:
        conn.execute(
            """
            INSERT INTO accounts (strategy_id, strategy_name, cash, total_value, start_value, last_update)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (strategy_id, strategy_id, cash, total_value, 100000.0, last_update),
        )
        conn.commit()
    finally:
        conn.close()


def test_execute_daily_loads_each_strategy_pool_once_per_day(tmp_path, monkeypatch):
    fake_data = FakeDataManager(tmp_path, local_codes=["000001", "000002"])
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    manager.pools = {"core": ["000001", "000002"]}
    _insert_account(manager, "strategy_a")
    _insert_account(manager, "strategy_b")

    registry = {
        "strategy_a": _spec("core"),
        "strategy_b": _spec("core"),
    }
    monkeypatch.setattr(vtm_module, "STRATEGY_REGISTRY", registry)

    result = manager.execute_daily()

    assert result["status"] == "success"
    assert fake_data.pool_calls == [("000001", "000002")]


def test_execute_daily_uses_named_etf_pool_instead_of_all_local_etfs(tmp_path, monkeypatch):
    fake_data = FakeDataManager(tmp_path)
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    manager.pools = {"etf": ["510300"]}
    _insert_account(manager, "etf_strategy")

    monkeypatch.setattr(vtm_module, "STRATEGY_REGISTRY", {"etf_strategy": _spec("etf")})

    result = manager.execute_daily()

    assert result["status"] == "success"
    assert fake_data.pool_calls == [("510300",)]


def test_execute_daily_rehydrates_stateful_position_and_marks_to_market(tmp_path, monkeypatch):
    fake_data = FakeDataManager(tmp_path, close_price=12.0)
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    manager.pools = {"core": ["000001"]}
    _insert_account(manager, "stateful", cash=1000.0, total_value=2000.0)

    conn = manager._get_conn()
    try:
        conn.execute(
            """
            INSERT INTO positions (
                strategy_id, symbol, shares, cost_price, current_price, entry_date, entry_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("stateful", "000001", 100, 10.0, 10.0, "2026-01-01", 10.0),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(vtm_module, "STRATEGY_REGISTRY", {"stateful": _spec("core")})

    result = manager.execute_daily()

    conn = manager._get_conn()
    try:
        position = conn.execute(
            "SELECT shares, cost_price, current_price, entry_date, entry_price FROM positions WHERE strategy_id = ? AND symbol = ?",
            ("stateful", "000001"),
        ).fetchone()
        account = conn.execute(
            "SELECT cash, total_value, last_update FROM accounts WHERE strategy_id = ?",
            ("stateful",),
        ).fetchone()
        sells = conn.execute(
            "SELECT COUNT(*) FROM trade_log WHERE strategy_id = ? AND side = 'SELL'",
            ("stateful",),
        ).fetchone()[0]
        daily_total = conn.execute(
            "SELECT total_value FROM daily_stats WHERE strategy_id = ? AND date = ?",
            ("stateful", "2026-01-02"),
        ).fetchone()[0]
    finally:
        conn.close()

    assert result["status"] == "success"
    assert position == (100, 10.0, 12.0, "2026-01-01", 10.0)
    assert account == (1000.0, 2200.0, "2026-01-02")
    assert daily_total == 2200.0
    assert sells == 0


def test_execute_daily_reports_skipped_when_no_pool_is_ready(tmp_path, monkeypatch):
    fake_data = FakeDataManager(tmp_path, local_codes=["000001"], selected_codes=["000002"])
    missing_path = tmp_path / "000002_full_history.parquet"
    fake_data.get_cache_path = lambda symbol: fake_data.sample_path if symbol == "000001" else missing_path
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    manager.pools = {"core": ["000002"]}
    _insert_account(manager, "stateful")
    conn = manager._get_conn()
    try:
        conn.execute(
            "INSERT INTO daily_stats (strategy_id, date, total_value, cash) VALUES (?, ?, ?, ?)",
            ("stateful", "2026-01-01", 100000.0, 100000.0),
        )
        conn.execute(
            "INSERT INTO trade_log (strategy_id, date, symbol, side, price, shares, fee, msg) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("stateful", "2026-01-01", "000001", "INFO", 0.0, 0, 0.0, "disable bootstrap for catch-up test"),
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(vtm_module, "STRATEGY_REGISTRY", {"stateful": _spec("core")})

    result = manager.execute_daily()

    conn = manager._get_conn()
    try:
        last_update = conn.execute(
            "SELECT last_update FROM accounts WHERE strategy_id = ?",
            ("stateful",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert result["status"] == "skipped"
    assert result["processed_days"] == []
    assert result["skipped_days"][0]["skipped_pools"]["core"]["missing_on_day_count"] == 1
    assert last_update == "2026-01-01"


def test_execute_daily_bootstraps_empty_accounts_to_latest_close(tmp_path, monkeypatch):
    fake_data = FakeDataManager(tmp_path, close_price=10.0, local_codes=["000001", "000002"])
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    manager.pools = {"core": ["000001", "000002"]}
    _insert_account(manager, "ranker")

    def strategy_func(df):
        out = df.copy()
        out["signal"] = 0
        out["score"] = 0.0
        out.loc[out["stock_code"] == "000002", "signal"] = 1
        out.loc[out["stock_code"] == "000002", "score"] = 1.0
        return out

    spec = SimpleNamespace(
        pool="core",
        func=strategy_func,
        signal_type="ranking",
        holding_policy="hold_while_selected",
        default_max_hold_days=None,
        default_take_profit=None,
        execution_mode="next_open_rebalance",
    )
    monkeypatch.setattr(vtm_module, "STRATEGY_REGISTRY", {"ranker": spec})

    result = manager.execute_daily()

    conn = manager._get_conn()
    try:
        position = conn.execute(
            "SELECT symbol, shares, cost_price, current_price, entry_date FROM positions WHERE strategy_id = ?",
            ("ranker",),
        ).fetchone()
        account = conn.execute(
            "SELECT last_update FROM accounts WHERE strategy_id = ?",
            ("ranker",),
        ).fetchone()[0]
        trades = conn.execute("SELECT COUNT(*) FROM trade_log WHERE strategy_id = ?", ("ranker",)).fetchone()[0]
    finally:
        conn.close()

    assert result["mode"] == "bootstrap"
    assert result["date"] == "2026-01-02"
    assert position[0] == "000002"
    assert position[2:] == (10.0, 10.0, "2026-01-02")
    assert account == "2026-01-02"
    assert trades == 1


def test_execute_daily_skips_accounts_already_updated_for_day(tmp_path, monkeypatch):
    fake_data = FakeDataManager(tmp_path, close_price=10.0, local_codes=["000001"])
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    manager.pools = {"core": ["000001"]}
    _insert_account(manager, "current", last_update="2026-01-02")
    _insert_account(manager, "lagging", last_update="2026-01-01")

    conn = manager._get_conn()
    try:
        conn.execute(
            "INSERT INTO trade_log (strategy_id, date, symbol, side, price, shares, fee, msg) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("lagging", "2026-01-01", "INFO", "INFO", 0.0, 0, 0.0, "disable bootstrap"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO execution_meta (key, value) VALUES (?, ?)",
            ("virtual_universe_version", vtm_module.VIRTUAL_UNIVERSE_VERSION),
        )
        conn.commit()
    finally:
        conn.close()

    spec = _spec(strategy_func=_buy_signal("000001"))
    monkeypatch.setattr(vtm_module, "STRATEGY_REGISTRY", {"current": spec, "lagging": spec})

    result = manager.execute_daily()

    conn = manager._get_conn()
    try:
        current_trades = conn.execute(
            "SELECT COUNT(*) FROM trade_log WHERE strategy_id = ? AND date = ? AND side = 'BUY'",
            ("current", "2026-01-02"),
        ).fetchone()[0]
        lagging_trades = conn.execute(
            "SELECT COUNT(*) FROM trade_log WHERE strategy_id = ? AND date = ? AND side = 'BUY'",
            ("lagging", "2026-01-02"),
        ).fetchone()[0]
    finally:
        conn.close()

    assert result["status"] == "success"
    assert current_trades == 0
    assert lagging_trades == 1


def test_execute_daily_bootstraps_new_null_update_account_without_replaying_current_accounts(tmp_path, monkeypatch):
    fake_data = FakeDataManager(tmp_path, close_price=10.0, local_codes=["000001"])
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    manager.pools = {"core": ["000001"]}
    _insert_account(manager, "current", last_update="2026-01-02")
    _insert_account(manager, "shadow", last_update=None)

    conn = manager._get_conn()
    try:
        conn.execute(
            "INSERT INTO daily_stats (strategy_id, date, total_value, cash) VALUES (?, ?, ?, ?)",
            ("current", "2026-01-02", 100000.0, 100000.0),
        )
        conn.execute(
            "INSERT OR REPLACE INTO execution_meta (key, value) VALUES (?, ?)",
            ("virtual_universe_version", vtm_module.VIRTUAL_UNIVERSE_VERSION),
        )
        conn.commit()
    finally:
        conn.close()

    spec = _spec(
        strategy_func=_buy_signal("000001"),
        signal_type="ranking",
        holding_policy="hold_while_selected",
    )
    monkeypatch.setattr(vtm_module, "STRATEGY_REGISTRY", {"current": spec, "shadow": spec})

    result = manager.execute_daily()

    conn = manager._get_conn()
    try:
        shadow_update = conn.execute(
            "SELECT last_update FROM accounts WHERE strategy_id = ?",
            ("shadow",),
        ).fetchone()[0]
        shadow_trades = conn.execute(
            "SELECT COUNT(*) FROM trade_log WHERE strategy_id = ? AND side = 'BUY'",
            ("shadow",),
        ).fetchone()[0]
        current_trades = conn.execute(
            "SELECT COUNT(*) FROM trade_log WHERE strategy_id = ? AND side = 'BUY'",
            ("current",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert result["status"] == "success"
    assert result["mode"] == "bootstrap"
    assert shadow_update == "2026-01-02"
    assert shadow_trades == 1
    assert current_trades == 0


def test_match_orders_reserves_fees_for_full_weight_buy(tmp_path):
    fake_data = FakeDataManager(tmp_path, close_price=10.0)
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    _insert_account(manager, "full_weight")

    conn = manager._get_conn()
    try:
        day_data = pd.DataFrame([{"date": "2026-01-02", "stock_code": "000001", "close": 10.0}])
        manager._match_orders(
            conn.cursor(),
            "full_weight",
            "2026-01-02",
            {"000001": 1.0},
            {},
            day_data,
            cash=100000.0,
            total_value=100000.0,
        )
        conn.commit()
        position = conn.execute(
            "SELECT shares FROM positions WHERE strategy_id = ? AND symbol = ?",
            ("full_weight", "000001"),
        ).fetchone()
        account = conn.execute(
            "SELECT cash, total_value FROM accounts WHERE strategy_id = ?",
            ("full_weight",),
        ).fetchone()
    finally:
        conn.close()

    assert position == (9900,)
    assert account[0] > 0
    assert account[1] > 0


def test_match_orders_uses_target_weight_order_when_cash_is_limited(tmp_path):
    fake_data = FakeDataManager(tmp_path, close_price=10.0)
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    _insert_account(manager, "ordered", cash=50000.0, total_value=100000.0)

    conn = manager._get_conn()
    try:
        day_data = pd.DataFrame(
            [
                {"date": "2026-01-02", "stock_code": "000001", "close": 10.0},
                {"date": "2026-01-02", "stock_code": "000002", "close": 10.0},
            ]
        )
        manager._match_orders(
            conn.cursor(),
            "ordered",
            "2026-01-02",
            {"000002": 1.0, "000001": 1.0},
            {},
            day_data,
            cash=50000.0,
            total_value=100000.0,
        )
        conn.commit()
        held = [
            row[0]
            for row in conn.execute(
                "SELECT symbol FROM positions WHERE strategy_id = ? ORDER BY symbol",
                ("ordered",),
            ).fetchall()
        ]
    finally:
        conn.close()

    assert held == ["000002"]


def test_match_orders_rejects_halted_and_no_volume_buys(tmp_path):
    fake_data = FakeDataManager(tmp_path, close_price=10.0)
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    _insert_account(manager, "tradability")

    conn = manager._get_conn()
    try:
        day_data = pd.DataFrame(
            [
                {
                    "date": "2026-01-02",
                    "stock_code": "000001",
                    "close": 10.0,
                    "volume": 0.0,
                    "tradestatus": "1",
                },
                {
                    "date": "2026-01-02",
                    "stock_code": "000002",
                    "close": 10.0,
                    "volume": 100000.0,
                    "tradestatus": "0",
                },
            ]
        )
        manager._match_orders(
            conn.cursor(),
            "tradability",
            "2026-01-02",
            {"000001": 0.5, "000002": 0.5},
            {},
            day_data,
            cash=100000.0,
            total_value=100000.0,
        )
        conn.commit()
        position_count = conn.execute(
            "SELECT COUNT(*) FROM positions WHERE strategy_id = ?",
            ("tradability",),
        ).fetchone()[0]
        trade_count = conn.execute(
            "SELECT COUNT(*) FROM trade_log WHERE strategy_id = ?",
            ("tradability",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert position_count == 0
    assert trade_count == 0


def test_match_orders_caps_buy_by_volume_participation(tmp_path, monkeypatch):
    monkeypatch.setattr(vtm_module, "VIRTUAL_MAX_VOLUME_PARTICIPATION", 0.20)
    fake_data = FakeDataManager(tmp_path, close_price=10.0)
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    _insert_account(manager, "capacity")

    conn = manager._get_conn()
    try:
        day_data = pd.DataFrame(
            [
                {
                    "date": "2026-01-02",
                    "stock_code": "000001",
                    "close": 10.0,
                    "volume": 500.0,
                    "tradestatus": "1",
                },
            ]
        )
        manager._match_orders(
            conn.cursor(),
            "capacity",
            "2026-01-02",
            {"000001": 1.0},
            {},
            day_data,
            cash=100000.0,
            total_value=100000.0,
        )
        conn.commit()
        position = conn.execute(
            "SELECT shares FROM positions WHERE strategy_id = ? AND symbol = ?",
            ("capacity", "000001"),
        ).fetchone()
        trade = conn.execute(
            "SELECT shares, msg FROM trade_log WHERE strategy_id = ? AND symbol = ?",
            ("capacity", "000001"),
        ).fetchone()
    finally:
        conn.close()

    assert position == (100,)
    assert trade[0] == 100
    assert "部分成交" in trade[1]


def test_match_orders_respects_t1_sell_block(tmp_path):
    fake_data = FakeDataManager(tmp_path, close_price=10.0)
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    _insert_account(manager, "t1", cash=90000.0, total_value=100000.0)

    conn = manager._get_conn()
    try:
        conn.execute(
            """
            INSERT INTO positions (
                strategy_id, symbol, shares, cost_price, current_price, entry_date, entry_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("t1", "000001", 1000, 10.0, 10.0, "2026-01-02", 10.0),
        )
        day_data = pd.DataFrame(
            [
                {
                    "date": "2026-01-02",
                    "stock_code": "000001",
                    "close": 10.0,
                    "volume": 100000.0,
                    "tradestatus": "1",
                },
            ]
        )
        manager._match_orders(
            conn.cursor(),
            "t1",
            "2026-01-02",
            {},
            {"000001": vtm_module.MockPosition(1000, 10.0, current_price=10.0, entry_date="2026-01-02")},
            day_data,
            cash=90000.0,
            total_value=100000.0,
        )
        conn.commit()
        position = conn.execute(
            "SELECT shares FROM positions WHERE strategy_id = ? AND symbol = ?",
            ("t1", "000001"),
        ).fetchone()
        sell_count = conn.execute(
            "SELECT COUNT(*) FROM trade_log WHERE strategy_id = ? AND side = 'SELL'",
            ("t1",),
        ).fetchone()[0]
    finally:
        conn.close()

    assert position == (1000,)
    assert sell_count == 0


def test_match_orders_keeps_target_for_held_limit_up_stock_before_selling_diff(tmp_path):
    fake_data = FakeDataManager(tmp_path, close_price=11.0)
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    _insert_account(manager, "limit_up_reduce", cash=89000.0, total_value=100000.0)

    conn = manager._get_conn()
    try:
        conn.execute(
            """
            INSERT INTO positions (
                strategy_id, symbol, shares, cost_price, current_price, entry_date, entry_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("limit_up_reduce", "000001", 1000, 10.0, 11.0, "2026-01-01", 10.0),
        )
        day_data = pd.DataFrame(
            [
                {
                    "date": "2026-01-02",
                    "stock_code": "000001",
                    "close": 11.0,
                    "prev_close": 10.0,
                    "pct_chg": 10.0,
                    "volume": 100000.0,
                    "tradestatus": "1",
                },
            ]
        )
        manager._match_orders(
            conn.cursor(),
            "limit_up_reduce",
            "2026-01-02",
            {"000001": 0.05},
            {"000001": vtm_module.MockPosition(1000, 10.0, current_price=11.0, entry_date="2026-01-01")},
            day_data,
            cash=89000.0,
            total_value=100000.0,
        )
        conn.commit()
        position = conn.execute(
            "SELECT shares FROM positions WHERE strategy_id = ? AND symbol = ?",
            ("limit_up_reduce", "000001"),
        ).fetchone()
        sell = conn.execute(
            "SELECT shares FROM trade_log WHERE strategy_id = ? AND side = 'SELL'",
            ("limit_up_reduce",),
        ).fetchone()
    finally:
        conn.close()

    assert position == (400,)
    assert sell == (600,)


def test_execute_daily_records_strategy_failures_in_response_and_reports(tmp_path, monkeypatch):
    fake_data = FakeDataManager(tmp_path, local_codes=["000001"])
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    manager.pools = {"core": ["000001"]}
    _insert_account(manager, "broken")

    conn = manager._get_conn()
    try:
        conn.execute(
            "INSERT INTO trade_log (strategy_id, date, symbol, side, price, shares, fee, msg) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("broken", "2026-01-01", "INFO", "INFO", 0.0, 0, 0.0, "disable bootstrap"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO execution_meta (key, value) VALUES (?, ?)",
            ("virtual_universe_version", vtm_module.VIRTUAL_UNIVERSE_VERSION),
        )
        conn.commit()
    finally:
        conn.close()

    def broken_strategy(df):
        raise ValueError("boom")

    monkeypatch.setattr(vtm_module, "STRATEGY_REGISTRY", {"broken": _spec(strategy_func=broken_strategy)})

    result = manager.execute_daily()

    conn = manager._get_conn()
    try:
        report = conn.execute(
            "SELECT status, message FROM strategy_reports WHERE strategy_id = ? AND date = ?",
            ("broken", "2026-01-02"),
        ).fetchone()
    finally:
        conn.close()

    assert result["status"] == "failed"
    assert result["failed_strategies"][0]["strategy_id"] == "broken"
    assert report == ("failed", "boom")


def test_accounts_tolerate_zero_start_value(tmp_path):
    fake_data = FakeDataManager(tmp_path)
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    _insert_account(manager, "bad", cash=0.0, total_value=0.0)
    conn = manager._get_conn()
    try:
        conn.execute("UPDATE accounts SET start_value = 0 WHERE strategy_id = ?", ("bad",))
        conn.commit()
    finally:
        conn.close()

    accounts = manager.get_accounts()

    assert accounts[0]["return_rate"] == 0.0


def test_accounts_can_use_intraday_snapshot_price_overlay(tmp_path):
    fake_data = FakeDataManager(tmp_path)
    manager = VirtualTradingManager(tmp_path / "vt.db", fake_data)
    _insert_account(manager, "live", cash=1000.0, total_value=11000.0)
    conn = manager._get_conn()
    try:
        conn.execute(
            """
            INSERT INTO positions (
                strategy_id, symbol, shares, cost_price, current_price, entry_date, entry_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("live", "000001", 1000, 10.0, 10.0, "2026-01-02", 10.0),
        )
        conn.commit()
    finally:
        conn.close()

    accounts = manager.get_accounts(
        price_overrides={"000001": 12.0},
        valuation_meta={"captured_at": "2026-01-02T10:30:00", "snapshot_id": "snapshot-unit"},
    )

    assert accounts[0]["valuation_source"] == "intraday_snapshot"
    assert accounts[0]["total_value"] == 13000.0
    assert accounts[0]["eod_total_value"] == 11000.0
    assert accounts[0]["snapshot_coverage"] == 1.0
    assert accounts[0]["top_holding_details"][0]["current_price"] == 12.0
    assert accounts[0]["top_holding_details"][0]["eod_price"] == 10.0
