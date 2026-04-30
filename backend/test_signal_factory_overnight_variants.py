import pandas as pd

from strategies.signal_factory import (
    calculate_overnight_hold_signals_balanced,
    calculate_overnight_hold_signals_ranked,
)


def _build_history(code: str, signal_close: float, high: float, low: float, volume: float, turnover: float, extra_close: float):
    rows = []
    base_date = pd.Timestamp("2026-01-01")
    for i in range(10):
        rows.append(
            {
                "date": (base_date + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                "stock_code": code,
                "stock_name": code,
                "open": 10.0,
                "high": 10.1,
                "low": 9.9,
                "close": 10.0 + (0.01 * i),
                "volume": 1000.0,
                "amount": 10000.0,
                "amplitude": 2.0,
                "pct_chg": 0.5,
                "change": 0.05,
                "turnover_rate": 1.0,
            }
        )

    rows.append(
        {
            "date": (base_date + pd.Timedelta(days=10)).strftime("%Y-%m-%d"),
            "stock_code": code,
            "stock_name": code,
            "open": 10.2,
            "high": high,
            "low": low,
            "close": signal_close,
            "volume": volume,
            "amount": volume * signal_close,
            "amplitude": (high - low) / 10.09 * 100,
            "pct_chg": ((signal_close / 10.09) - 1) * 100,
            "change": signal_close - 10.09,
            "turnover_rate": turnover,
        }
    )
    rows.append(
        {
            "date": (base_date + pd.Timedelta(days=11)).strftime("%Y-%m-%d"),
            "stock_code": code,
            "stock_name": code,
            "open": extra_close,
            "high": extra_close,
            "low": extra_close,
            "close": extra_close,
            "volume": 1000.0,
            "amount": 10000.0,
            "amplitude": 1.0,
            "pct_chg": 0.0,
            "change": 0.0,
            "turnover_rate": 1.0,
        }
    )
    return rows


def test_balanced_variant_filters_out_high_turnover_signal():
    qualified = _build_history("AAA", signal_close=10.55, high=10.56, low=10.18, volume=1600.0, turnover=2.5, extra_close=10.65)
    crowded = _build_history("BBB", signal_close=10.60, high=10.62, low=10.18, volume=1600.0, turnover=5.2, extra_close=10.70)
    df = pd.DataFrame(qualified + crowded)

    result = calculate_overnight_hold_signals_balanced(df)
    signal_day = result[result["date"] == "2026-01-11"][["stock_code", "signal"]].sort_values("stock_code")
    assert signal_day.to_dict(orient="records") == [
        {"stock_code": "AAA", "signal": 1},
        {"stock_code": "BBB", "signal": 0},
    ]


def test_ranked_variant_keeps_only_daily_top_one():
    first = _build_history("AAA", signal_close=10.55, high=10.56, low=10.18, volume=1600.0, turnover=2.0, extra_close=10.65)
    second = _build_history("BBB", signal_close=10.48, high=10.50, low=10.18, volume=1500.0, turnover=2.0, extra_close=10.60)
    df = pd.DataFrame(first + second)

    result = calculate_overnight_hold_signals_ranked(df)
    selected = result[(result["date"] == "2026-01-11") & (result["signal"] == 1)]["stock_code"].tolist()
    assert selected == ["AAA"]
