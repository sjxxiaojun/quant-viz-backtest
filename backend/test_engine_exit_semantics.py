import pandas as pd

from engine import BacktestEngine, CostModel, Position


ZERO_COST_MODEL = CostModel(
    commission_rate=0.0,
    commission_min=0.0,
    stamp_tax_rate=0.0,
    slippage_rate=0.0,
    use_order_slicing=False,
)


def _bar(
    date,
    code,
    open_price,
    close_price,
    pct_chg=0.0,
    stock_name=None,
    volume=None,
    tradestatus="1",
    is_st=0,
    prev_close=None,
):
    row = {
        "date": date,
        "stock_code": code,
        "stock_name": stock_name or code,
        "open": float(open_price),
        "close": float(close_price),
        "pct_chg": float(pct_chg),
        "tradestatus": tradestatus,
        "is_st": is_st,
    }
    if volume is not None:
        row["volume"] = float(volume)
    if prev_close is not None:
        row["prev_close"] = float(prev_close)
    return {
        **row,
    }


def _run_backtest(rows, signal_map, **engine_kwargs):
    data = pd.DataFrame(rows)

    def signal_func(date, day_data):
        return signal_map.get(date, {})

    engine = BacktestEngine(
        initial_capital=100000.0,
        cost_model=ZERO_COST_MODEL,
        stock_stop_loss=-0.08,
        **engine_kwargs,
    )
    dates = sorted(data["date"].unique())
    return engine.run_backtest(data, signal_func, dates[0], dates[-1])


def test_exit_01_empty_target_exits_on_next_open():
    result = _run_backtest(
        [
            _bar("2026-01-01", "AAA", 10, 10),
            _bar("2026-01-02", "AAA", 10, 10),
            _bar("2026-01-03", "AAA", 11, 11),
        ],
        {
            "2026-01-01": {"AAA": 1.0},
            "2026-01-02": {},
            "2026-01-03": {},
        },
    )

    assert [(trade["date"], trade["side"]) for trade in result["trades"]] == [
        ("2026-01-02", "buy"),
        ("2026-01-03", "sell"),
    ]
    assert result["final_positions"] == []


def test_overnight_01_signal_executes_on_next_session_open():
    result = _run_backtest(
        [
            _bar("2026-01-01", "AAA", 10, 10),
            _bar("2026-01-02", "AAA", 10.5, 10.5),
        ],
        {
            "2026-01-01": {"AAA": 1.0},
            "2026-01-02": {"AAA": 1.0},
        },
    )

    assert len(result["trades"]) == 1
    assert result["trades"][0]["date"] == "2026-01-02"
    assert result["trades"][0]["side"] == "buy"
    assert result["trades"][0]["price"] == 10.5


def test_overnight_close_mode_buys_on_signal_close_and_sells_next_open():
    result = _run_backtest(
        [
            _bar("2026-01-01", "AAA", 9.8, 10.0),
            _bar("2026-01-02", "AAA", 10.5, 10.6),
            _bar("2026-01-03", "AAA", 10.2, 10.3),
        ],
        {
            "2026-01-01": {"AAA": 1.0},
            "2026-01-02": {"AAA": 1.0},
        },
        execution_mode="signal_close_to_next_open",
    )

    assert [(trade["date"], trade["side"], trade["price"]) for trade in result["trades"]] == [
        ("2026-01-01", "buy", 10.0),
        ("2026-01-02", "sell", 10.5),
        ("2026-01-02", "buy", 10.6),
        ("2026-01-03", "sell", 10.2),
    ]
    assert result["final_positions"] == []


def test_overnight_close_mode_uses_open_move_for_limit_exit_check():
    result = _run_backtest(
        [
            _bar("2026-01-01", "AAA", 9.8, 10.0),
            _bar("2026-01-02", "AAA", 9.7, 9.0, pct_chg=-10.0),
        ],
        {
            "2026-01-01": {"AAA": 1.0},
            "2026-01-02": {},
        },
        execution_mode="signal_close_to_next_open",
    )

    assert [(trade["date"], trade["side"], trade["price"]) for trade in result["trades"]] == [
        ("2026-01-01", "buy", 10.0),
        ("2026-01-02", "sell", 9.7),
    ]
    assert result["final_positions"] == []


def test_stop_loss_01_no_same_day_reentry_after_risk_exit():
    result = _run_backtest(
        [
            _bar("2026-01-01", "AAA", 10, 10),
            _bar("2026-01-02", "AAA", 10, 10),
            _bar("2026-01-03", "AAA", 8.5, 8.5, pct_chg=-9.0),
        ],
        {
            "2026-01-01": {"AAA": 1.0},
            "2026-01-02": {"AAA": 1.0},
            "2026-01-03": {"AAA": 1.0},
        },
    )

    assert [(trade["date"], trade["side"]) for trade in result["trades"]] == [
        ("2026-01-02", "buy"),
        ("2026-01-03", "stop_loss"),
    ]
    assert result["final_positions"] == []


def test_engine_01_legacy_portfolio_circuit_breaker_does_not_pause_trading():
    result = _run_backtest(
        [
            _bar("2026-01-01", "AAA", 10, 10),
            _bar("2026-01-01", "BBB", 10, 10),
            _bar("2026-01-02", "AAA", 10, 9.4),
            _bar("2026-01-02", "BBB", 10, 10),
            _bar("2026-01-03", "AAA", 9.4, 9.4),
            _bar("2026-01-03", "BBB", 10, 10),
        ],
        {
            "2026-01-01": {"AAA": 1.0},
            "2026-01-02": {"BBB": 1.0},
            "2026-01-03": {"BBB": 1.0},
        },
        portfolio_circuit_breaker=-0.05,
    )

    assert [(trade["date"], trade["stock_code"], trade["side"]) for trade in result["trades"]] == [
        ("2026-01-02", "AAA", "buy"),
        ("2026-01-03", "AAA", "sell"),
        ("2026-01-03", "BBB", "buy"),
    ]
    assert result["summary"]["closed_trade_breakdown"] == {
        "sell": 1,
        "stop_loss": 0,
        "take_profit": 0,
    }
    assert all(trade["side"] != "circuit_break" for trade in result["trades"])


def test_stats_01_closed_trade_stats_cover_individual_exit_sides():
    result = _run_backtest(
        [
            _bar("2026-01-01", "SELL", 10, 10),
            _bar("2026-01-01", "STOP", 10, 10),
            _bar("2026-01-01", "TAKE", 10, 10),
            _bar("2026-01-01", "CBRK", 10, 10),
            _bar("2026-01-02", "SELL", 10, 10),
            _bar("2026-01-02", "STOP", 10, 10),
            _bar("2026-01-02", "TAKE", 10, 10),
            _bar("2026-01-02", "CBRK", 10, 10),
            _bar("2026-01-03", "SELL", 10.5, 10.5),
            _bar("2026-01-03", "STOP", 8.5, 8.5, pct_chg=-9.0),
            _bar("2026-01-03", "TAKE", 12, 12, pct_chg=10),
            _bar("2026-01-03", "CBRK", 10, 10),
            _bar("2026-01-04", "CBRK", 5, 5, pct_chg=-9.0),
        ],
        {
            "2026-01-01": {
                "SELL": 0.25,
                "STOP": 0.25,
                "TAKE": 0.25,
                "CBRK": 0.25,
            },
            "2026-01-02": {
                "STOP": 1 / 3,
                "TAKE": 1 / 3,
                "CBRK": 1 / 3,
            },
            "2026-01-03": {"CBRK": 1.0},
            "2026-01-04": {},
        },
        take_profit=0.10,
        portfolio_circuit_breaker=-0.05,
    )

    summary = result["summary"]
    assert summary["total_trades"] == 4
    assert summary["closed_trade_breakdown"] == {
        "sell": 1,
        "stop_loss": 2,
        "take_profit": 1,
    }
    assert [(trade["date"], trade["stock_code"], trade["side"]) for trade in result["trades"]] == [
        ("2026-01-02", "SELL", "buy"),
        ("2026-01-02", "STOP", "buy"),
        ("2026-01-02", "TAKE", "buy"),
        ("2026-01-02", "CBRK", "buy"),
        ("2026-01-03", "STOP", "stop_loss"),
        ("2026-01-03", "TAKE", "take_profit"),
        ("2026-01-03", "SELL", "sell"),
        ("2026-01-04", "CBRK", "stop_loss"),
    ]
    assert summary["trade_stats"]["round_trip_count"] == 4
    assert summary["cost_stats"]["total_cost"] == 0.0
    assert summary["execution_stats"]["buy_fill_rate"] == 1.0


def test_execution_01_halted_and_no_volume_orders_are_rejected():
    result = _run_backtest(
        [
            _bar("2026-01-01", "HALT", 10, 10),
            _bar("2026-01-01", "ZERO", 10, 10),
            _bar("2026-01-02", "HALT", 10, 10, tradestatus="0", volume=100000),
            _bar("2026-01-02", "ZERO", 10, 10, volume=0),
        ],
        {
            "2026-01-01": {"HALT": 0.5, "ZERO": 0.5},
            "2026-01-02": {"HALT": 0.5, "ZERO": 0.5},
        },
    )

    assert result["trades"] == []
    stats = result["summary"]["execution_stats"]
    assert stats["buy_attempts"] == 2
    assert stats["blocked_halt_trade_count"] == 1
    assert stats["blocked_no_volume_trade_count"] == 1


def test_execution_02_volume_participation_partially_fills_buy_order():
    result = _run_backtest(
        [
            _bar("2026-01-01", "AAA", 10, 10),
            _bar("2026-01-02", "AAA", 10, 10, volume=500),
        ],
        {
            "2026-01-01": {"AAA": 1.0},
            "2026-01-02": {"AAA": 1.0},
        },
        max_volume_participation=0.20,
    )

    assert [(trade["side"], trade["qty"], trade["requested_qty"], trade["fill_status"]) for trade in result["trades"]] == [
        ("buy", 100, 9800, "partial")
    ]
    assert result["final_positions"][0]["quantity"] == 100
    assert result["summary"]["execution_stats"]["partial_fill_count"] == 1


def test_execution_03_volume_participation_partially_fills_sell_and_keeps_remainder():
    result = _run_backtest(
        [
            _bar("2026-01-01", "AAA", 10, 10),
            _bar("2026-01-02", "AAA", 10, 10, volume=1_000_000),
            _bar("2026-01-03", "AAA", 10, 10, volume=500),
        ],
        {
            "2026-01-01": {"AAA": 1.0},
            "2026-01-02": {},
            "2026-01-03": {},
        },
        max_volume_participation=0.20,
    )

    assert [(trade["side"], trade["qty"], trade["requested_qty"], trade["fill_status"]) for trade in result["trades"]] == [
        ("buy", 9800, 9800, "filled"),
        ("sell", 100, 9800, "partial"),
    ]
    assert result["final_positions"][0]["quantity"] == 9700
    assert result["summary"]["trade_stats"]["round_trip_count"] == 1


def test_execution_04_st_limit_down_blocks_sell_at_five_percent():
    result = _run_backtest(
        [
            _bar("2026-01-01", "STAA", 10, 10, stock_name="ST测试", is_st=1),
            _bar("2026-01-02", "STAA", 10, 10, stock_name="ST测试", is_st=1, volume=1_000_000),
            _bar("2026-01-03", "STAA", 9.5, 9.5, stock_name="ST测试", is_st=1, prev_close=10.0, volume=1_000_000),
        ],
        {
            "2026-01-01": {"STAA": 1.0},
            "2026-01-02": {},
            "2026-01-03": {},
        },
    )

    assert [(trade["date"], trade["side"]) for trade in result["trades"]] == [
        ("2026-01-02", "buy")
    ]
    assert result["final_positions"][0]["stock_code"] == "STAA"
    assert result["summary"]["execution_stats"]["blocked_limit_down_sell_count"] == 1


def test_execution_05_t1_blocks_same_day_liquidation():
    engine = BacktestEngine(
        initial_capital=100000.0,
        cost_model=ZERO_COST_MODEL,
    )
    engine._reset_diagnostics()
    engine.portfolio.positions["AAA"] = Position(
        "AAA",
        "AAA",
        1000,
        10.0,
        market_value=10000.0,
        entry_date="2026-01-02",
    )
    day_data = pd.DataFrame(
        [
            _bar("2026-01-02", "AAA", 10, 10, volume=1_000_000),
        ]
    )

    engine._liquidate_positions("2026-01-02", day_data, side="sell", price_field="open")

    assert "AAA" in engine.portfolio.positions
    assert engine.trades == []
    assert engine.execution_stats["t1_sell_block_count"] == 1


def test_execution_06_overnight_partial_open_exit_is_not_sold_again_at_close():
    result = _run_backtest(
        [
            _bar("2026-01-01", "AAA", 10.0, 10.0, volume=1_000_000),
            _bar("2026-01-01", "BBB", 20.0, 20.0, volume=1_000_000),
            _bar("2026-01-02", "AAA", 10.0, 10.0, volume=500),
            _bar("2026-01-02", "BBB", 20.0, 20.0, volume=1_000_000),
            _bar("2026-01-03", "AAA", 10.0, 10.0, volume=1_000_000),
            _bar("2026-01-03", "BBB", 20.0, 20.0, volume=1_000_000),
        ],
        {
            "2026-01-01": {"AAA": 1.0},
            "2026-01-02": {"BBB": 1.0},
        },
        execution_mode="signal_close_to_next_open",
        max_volume_participation=0.20,
    )

    assert [(trade["date"], trade["stock_code"], trade["side"], trade["qty"], trade["fill_status"]) for trade in result["trades"]] == [
        ("2026-01-01", "AAA", "buy", 9800, "filled"),
        ("2026-01-02", "AAA", "sell", 100, "partial"),
        ("2026-01-02", "BBB", "buy", 100, "filled"),
        ("2026-01-03", "AAA", "sell", 9700, "filled"),
        ("2026-01-03", "BBB", "sell", 100, "filled"),
    ]
    assert result["summary"]["trade_stats"]["round_trip_count"] == 3
