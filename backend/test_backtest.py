import pandas as pd

from engine import BacktestEngine, CostModel


ZERO_COST_MODEL = CostModel(
    commission_rate=0.0,
    commission_min=0.0,
    stamp_tax_rate=0.0,
    slippage_rate=0.0,
    use_order_slicing=False,
)


def _bar(date, code, open_price, close_price, pct_chg=0.0):
    return {
        "date": date,
        "stock_code": code,
        "stock_name": code,
        "open": float(open_price),
        "close": float(close_price),
        "pct_chg": float(pct_chg),
    }


def test_backtest_smoke_runs_with_signal_callback_and_benchmark():
    data = pd.DataFrame(
        [
            _bar("2026-01-01", "AAA", 10.0, 10.0),
            _bar("2026-01-02", "AAA", 10.5, 10.5),
            _bar("2026-01-03", "AAA", 11.0, 11.0),
        ]
    )
    benchmark = pd.DataFrame(
        [
            {"date": "2026-01-01", "close": 100.0},
            {"date": "2026-01-02", "close": 101.0},
            {"date": "2026-01-03", "close": 102.0},
        ]
    )

    def signal_func(date, day_data):
        if date == "2026-01-01":
            return {"AAA": 1.0}
        return {}

    engine = BacktestEngine(
        initial_capital=100000.0,
        cost_model=ZERO_COST_MODEL,
    )
    result = engine.run_backtest(
        data,
        signal_func,
        "2026-01-01",
        "2026-01-03",
        benchmark_data=benchmark,
    )

    assert [(trade["date"], trade["side"], trade["price"]) for trade in result["trades"]] == [
        ("2026-01-02", "buy", 10.5),
        ("2026-01-03", "sell", 11.0),
    ]
    assert result["summary"]["final_value"] > 100000.0
    assert len(result["benchmark_history"]) == 3


def test_signal_callback_receives_mergeable_stock_code_column():
    data = pd.DataFrame(
        [
            _bar("2026-01-01", "AAA", 10.0, 10.0),
            _bar("2026-01-02", "AAA", 10.5, 10.5),
            _bar("2026-01-02", "BBB", 20.0, 20.0),
        ]
    )
    signal_rows = pd.DataFrame([{"stock_code": "AAA", "signal": 1, "score": 1.0}])

    def signal_func(date, day_data):
        merged = pd.merge(
            day_data.drop(columns=["signal", "score"], errors="ignore"),
            signal_rows,
            on="stock_code",
            how="inner",
        )
        if date == "2026-01-01" and not merged.empty:
            return {"AAA": 1.0}
        return {}

    engine = BacktestEngine(
        initial_capital=100000.0,
        cost_model=ZERO_COST_MODEL,
    )

    result = engine.run_backtest(data, signal_func, "2026-01-01", "2026-01-02")

    assert result["trades"][0]["side"] == "buy"
