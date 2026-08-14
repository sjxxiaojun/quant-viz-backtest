"""limit_up_doji 事件信号的构造序列测试。

设计语义：昨日涨停（昨日 close/前日 close - 1 > 9.5%），当日为缩量十字星
（小实体、量能较昨日显著萎缩、低点不深破昨日收盘），于当日收盘后发出 signal=1。
"""
import pandas as pd

from strategies.signal_factory import calculate_limit_up_doji_signals


def _make_rows(code, bars):
    """bars: list of (open, high, low, close, volume)"""
    rows = []
    base_date = pd.Timestamp("2026-01-01")
    for i, (o, h, l, c, v) in enumerate(bars):
        rows.append(
            {
                "date": (base_date + pd.Timedelta(days=i)).strftime("%Y-%m-%d"),
                "stock_code": code,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v,
            }
        )
    return rows


def test_signal_fires_on_doji_day_after_limit_up():
    bars = [
        (10.0, 10.1, 9.9, 10.0, 10000.0),   # day0 平盘
        (10.0, 10.1, 9.9, 10.0, 10000.0),   # day1 平盘
        (10.0, 10.1, 9.9, 10.0, 10000.0),   # day2 平盘
        (10.5, 11.0, 10.4, 11.0, 30000.0),  # day3 涨停 (+10%)
        (11.05, 11.30, 10.95, 11.08, 15000.0),  # day4 缩量十字星 (量 15000 < 30000*0.7)
    ]
    result = calculate_limit_up_doji_signals(pd.DataFrame(_make_rows("AAA", bars)))
    signals = result.sort_values("date")["signal"].tolist()

    # 涨停日当天不触发，十字星日触发
    assert signals == [0, 0, 0, 0, 1]


def test_same_day_limit_up_doji_does_not_fire():
    """当日自身 +10% 的跳空十字星（无昨日涨停）不得触发——旧实现的 shift 错位会误报。"""
    bars = [
        (10.0, 10.1, 9.9, 10.0, 10000.0),
        (10.0, 10.1, 9.9, 10.0, 10000.0),
        (10.0, 10.1, 9.9, 10.0, 10000.0),
        (10.98, 11.10, 10.90, 11.0, 6000.0),  # 跳空 +10% 缩量小实体，但昨日未涨停
    ]
    result = calculate_limit_up_doji_signals(pd.DataFrame(_make_rows("BBB", bars)))
    assert result["signal"].tolist() == [0, 0, 0, 0]


def test_no_signal_when_volume_not_shrinking():
    bars = [
        (10.0, 10.1, 9.9, 10.0, 10000.0),
        (10.5, 11.0, 10.4, 11.0, 30000.0),          # 涨停
        (11.05, 11.30, 10.95, 11.08, 28000.0),      # 十字星但未缩量 (28000 >= 30000*0.7)
    ]
    result = calculate_limit_up_doji_signals(pd.DataFrame(_make_rows("CCC", bars)))
    assert result["signal"].tolist() == [0, 0, 0]


def test_no_signal_when_low_breaks_prev_close():
    bars = [
        (10.0, 10.1, 9.9, 10.0, 10000.0),
        (10.5, 11.0, 10.4, 11.0, 30000.0),          # 涨停
        (11.0, 11.10, 10.60, 11.02, 15000.0),       # 低点 10.60 < 11.0*0.98=10.78，深回踩
    ]
    result = calculate_limit_up_doji_signals(pd.DataFrame(_make_rows("DDD", bars)))
    assert result["signal"].tolist() == [0, 0, 0]
