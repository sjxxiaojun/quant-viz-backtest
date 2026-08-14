"""engine.py 定点回归测试：

A. 印花税豁免——A股 ETF/LOF/基金份额与债券（含可转债）卖出免征证券交易印花税，
   个股（沪/深/科创/创业/北交所）照章计征。
B. 止损执行时序——盘中触价（low/high）止损排在按开盘价调仓**之后**，
   盘中才知道的现金不能为同日开盘买单融资；开盘价即可判定的跳空止损仍在调仓之前。
"""
import pandas as pd
import pytest

from engine import BacktestEngine, CostModel


ZERO_COST_MODEL = CostModel(
    commission_rate=0.0,
    commission_min=0.0,
    stamp_tax_rate=0.0,
    slippage_rate=0.0,
    close_slippage_rate=0.0,
    transfer_fee_rate=0.0,
    use_order_slicing=False,
)

# 只留印花税的成本模型，便于直接读数
STAMP_ONLY_MODEL = CostModel(
    commission_rate=0.0,
    commission_min=0.0,
    slippage_rate=0.0,
    close_slippage_rate=0.0,
    transfer_fee_rate=0.0,
)


def _bar(date, code, open_price, close_price, low=None, high=None, prev_close=None):
    row = {
        "date": date,
        "stock_code": code,
        "stock_name": code,
        "open": float(open_price),
        "close": float(close_price),
        "pct_chg": 0.0,
        "tradestatus": "1",
        "is_st": 0,
    }
    if low is not None:
        row["low"] = float(low)
    if high is not None:
        row["high"] = float(high)
    if prev_close is not None:
        row["prev_close"] = float(prev_close)
    return row


def _run_backtest(rows, signal_map, cost_model=None, initial_capital=100000.0, **engine_kwargs):
    data = pd.DataFrame(rows)
    engine = BacktestEngine(
        initial_capital=initial_capital,
        cost_model=cost_model or ZERO_COST_MODEL,
        **engine_kwargs,
    )
    dates = sorted(data["date"].unique())
    return engine.run_backtest(
        data, lambda date, day_data: signal_map.get(date, {}), dates[0], dates[-1]
    )


# ---------------------------------------------------------------------------
# A. 印花税豁免：ETF / LOF / 债券免征，个股照征
# ---------------------------------------------------------------------------

EXEMPT_CODES = [
    ("510050", "沪 ETF 上证50"),
    ("512880", "沪 ETF 证券"),
    ("515790", "沪 ETF 光伏"),
    ("563300", "沪 ETF 中证2000"),
    ("588000", "科创50 ETF"),
    ("501050", "沪 LOF"),
    ("159915", "深 ETF 创业板"),
    ("159919", "深 ETF 沪深300"),
    ("161725", "深 LOF 中证白酒"),
    ("110059", "沪 可转债"),
    ("113016", "沪 可转债"),
    ("123001", "深 可转债"),
    ("128036", "深 可转债"),
]

TAXED_CODES = [
    ("600519", "沪主板"),
    ("601398", "沪主板"),
    ("688981", "科创板"),
    ("000001", "深主板"),
    ("002594", "深中小板"),
    ("300750", "创业板"),
    ("301021", "创业板"),
    ("830799", "北交所"),
    ("920002", "北交所"),
]


class TestStampTaxExemption:
    @pytest.mark.parametrize("code,label", EXEMPT_CODES)
    def test_funds_and_bonds_pay_no_stamp_tax_on_sell(self, code, label):
        breakdown = STAMP_ONLY_MODEL.calculate_cost_breakdown(
            100000.0, is_sell=True, trade_date="2024-01-05", stock_code=code
        )
        assert breakdown["stamp_tax"] == 0.0, f"{code} {label} 不应被征印花税"
        assert breakdown["total"] == 0.0

    @pytest.mark.parametrize("code,label", TAXED_CODES)
    def test_stocks_still_pay_stamp_tax_on_sell(self, code, label):
        breakdown = STAMP_ONLY_MODEL.calculate_cost_breakdown(
            100000.0, is_sell=True, trade_date="2024-01-05", stock_code=code
        )
        assert breakdown["stamp_tax"] == pytest.approx(50.0), f"{code} {label} 应照章计征"

    def test_exemption_holds_before_the_2023_rate_cut(self):
        # 2023-08-28 之前个股 0.1%，ETF 依然 0
        etf = STAMP_ONLY_MODEL.calculate_cost_breakdown(
            100000.0, True, trade_date="2022-05-06", stock_code="510050"
        )
        stock = STAMP_ONLY_MODEL.calculate_cost_breakdown(
            100000.0, True, trade_date="2022-05-06", stock_code="600519"
        )
        assert etf["stamp_tax"] == 0.0
        assert stock["stamp_tax"] == pytest.approx(100.0)

    def test_buy_side_unaffected(self):
        for code in ("510050", "600519"):
            assert STAMP_ONLY_MODEL.calculate_cost_breakdown(
                100000.0, False, stock_code=code
            )["stamp_tax"] == 0.0

    def test_exchange_prefixed_and_suffixed_codes_are_recognized(self):
        for code in ("sh.510050", "510050.SH", "sz.159915", "159915.SZ"):
            assert STAMP_ONLY_MODEL.calculate_cost_breakdown(
                100000.0, True, stock_code=code
            )["stamp_tax"] == 0.0
        for code in ("sh.600519", "600519.SH"):
            assert STAMP_ONLY_MODEL.calculate_cost_breakdown(
                100000.0, True, stock_code=code
            )["stamp_tax"] == pytest.approx(50.0)

    def test_unknown_or_missing_code_falls_back_to_taxed(self):
        # 未知/占位代码保持原有保守行为（按股票计税），不会静默漏征
        for code in (None, "", "AAA", "12345", "1234567"):
            assert STAMP_ONLY_MODEL.calculate_cost_breakdown(
                100000.0, True, stock_code=code
            )["stamp_tax"] == pytest.approx(50.0)

    def test_sh_etf_pays_no_transfer_fee_while_sh_stock_does(self):
        model = CostModel(commission_rate=0.0, commission_min=0.0, slippage_rate=0.0,
                          stamp_tax_rate=0.0)
        assert model.calculate_cost_breakdown(100000.0, True, stock_code="510050")["transfer_fee"] == 0.0
        assert model.calculate_cost_breakdown(100000.0, True, stock_code="600519")["transfer_fee"] == pytest.approx(1.0)

    def test_backtest_charges_no_stamp_tax_when_selling_etf(self):
        rows = [
            *[_bar(d, "510050", 3.0, 3.0) for d in ("2026-01-01", "2026-01-02", "2026-01-03")],
            *[_bar(d, "600519", 3.0, 3.0) for d in ("2026-01-01", "2026-01-02", "2026-01-03")],
        ]
        etf_only = _run_backtest(
            rows,
            {"2026-01-01": {"510050": 0.9}, "2026-01-02": {}},
            cost_model=STAMP_ONLY_MODEL,
        )
        stock_only = _run_backtest(
            rows,
            {"2026-01-01": {"600519": 0.9}, "2026-01-02": {}},
            cost_model=STAMP_ONLY_MODEL,
        )
        etf_sells = [t for t in etf_only["trades"] if t["side"] == "sell"]
        stock_sells = [t for t in stock_only["trades"] if t["side"] == "sell"]
        assert etf_sells and stock_sells, "两组都必须真的卖出过"
        assert etf_only["summary"]["cost_stats"]["stamp_tax_total"] == 0.0
        assert stock_only["summary"]["cost_stats"]["stamp_tax_total"] == pytest.approx(
            stock_sells[0]["notional"] * 0.0005
        )


# ---------------------------------------------------------------------------
# B. 止损执行时序：盘中触价止损的现金不得为同日开盘买单融资
# ---------------------------------------------------------------------------

def _intraday_stop_panel(stop_day_open=9.6, stop_day_low=9.0):
    """AAA 于 d2 开盘建仓 @10，d3 开盘未破位、盘中最低触发 -8% 止损（9.2）。"""
    return [
        _bar("2026-01-01", "AAA", 10, 10, low=10, high=10),
        _bar("2026-01-01", "BBB", 10, 10, low=10, high=10),
        _bar("2026-01-01", "CCC", 10, 10, low=10, high=10),
        _bar("2026-01-02", "AAA", 10, 10, low=10, high=10),
        _bar("2026-01-02", "BBB", 10, 10, low=10, high=10),
        _bar("2026-01-02", "CCC", 10, 10, low=10, high=10),
        _bar("2026-01-03", "AAA", stop_day_open, 9.1, low=stop_day_low, high=stop_day_open,
             prev_close=10.0),
        _bar("2026-01-03", "BBB", 10, 10, low=10, high=10, prev_close=10.0),
        _bar("2026-01-03", "CCC", 10, 10, low=10, high=10, prev_close=10.0),
        _bar("2026-01-04", "BBB", 10, 10, low=10, high=10, prev_close=10.0),
        _bar("2026-01-04", "CCC", 10, 10, low=10, high=10, prev_close=10.0),
    ]


SIGNALS_STOP_DAY_BUY = {
    "2026-01-01": {"AAA": 0.99},                 # d2 开盘满仓买 AAA -> 现金只剩 2000
    "2026-01-02": {"AAA": 0.5, "BBB": 0.5},      # d3 开盘买 BBB（与 AAA 止损同日）
    "2026-01-03": {"BBB": 0.5, "CCC": 0.5},      # d4 开盘买 CCC
}


class TestIntradayStopCannotFinanceSameDayOpenBuy:
    def test_same_day_open_buy_is_limited_to_pre_stop_cash(self):
        result = _run_backtest(_intraday_stop_panel(), SIGNALS_STOP_DAY_BUY,
                               stock_stop_loss=-0.08)
        by_day = {}
        for t in result["trades"]:
            by_day.setdefault(t["date"], []).append(t)

        # d2 满仓建仓：98,000 元买入，剩余现金 2,000
        assert [(t["stock_code"], t["side"], t["notional"]) for t in by_day["2026-01-02"]] == [
            ("AAA", "buy", 98000.0)
        ]

        stop_day = by_day["2026-01-03"]
        sides = [(t["stock_code"], t["side"]) for t in stop_day]
        # 关键断言 1：当日买单排在盘中止损**之前**
        assert sides == [("BBB", "buy"), ("AAA", "stop_loss")]
        # 关键断言 2：买入金额只用得上开盘时点已有的 2,000 现金（2000*0.98 -> 100 股）
        buy = stop_day[0]
        assert buy["qty"] == 100
        assert buy["notional"] == pytest.approx(1000.0)
        assert buy["notional"] <= 2000.0, "盘中止损释放的现金不得为同日开盘买单融资"
        # 止损确实按 min(open, stop_price)=9.2 成交，释放 90,160 元
        stop = stop_day[1]
        assert stop["price"] == pytest.approx(9.2)
        assert stop["notional"] == pytest.approx(9800 * 9.2)

    def test_stop_proceeds_become_available_the_next_day(self):
        result = _run_backtest(_intraday_stop_panel(), SIGNALS_STOP_DAY_BUY,
                               stock_stop_loss=-0.08)
        next_day = [t for t in result["trades"] if t["date"] == "2026-01-04"]
        assert [(t["stock_code"], t["side"]) for t in next_day] == [("CCC", "buy")]
        # 现金只是延后可用，不是被吞掉：次日买入 46,000 元
        assert next_day[0]["notional"] == pytest.approx(46000.0)

    def test_gap_open_stop_still_settles_before_the_open_rebalance(self):
        # 开盘 9.15 已破 9.2（-8.5%，未及跌停）：开盘价即可判定，现金当日开盘可用
        result = _run_backtest(_intraday_stop_panel(stop_day_open=9.15, stop_day_low=9.0),
                               SIGNALS_STOP_DAY_BUY, stock_stop_loss=-0.08)
        stop_day = [t for t in result["trades"] if t["date"] == "2026-01-03"]
        assert [(t["stock_code"], t["side"]) for t in stop_day] == [
            ("AAA", "stop_loss"), ("BBB", "buy")
        ]
        assert stop_day[0]["price"] == pytest.approx(9.15)
        # 跳空止损释放的 88,200 元当日即可用于开盘买单（远超 2,000 元的期初现金）
        assert stop_day[1]["notional"] > 40000.0

    def test_no_same_day_reentry_after_gap_open_stop(self):
        signals = {
            "2026-01-01": {"AAA": 0.99},
            "2026-01-02": {"AAA": 0.5, "BBB": 0.5},   # d3 信号仍含 AAA
        }
        result = _run_backtest(_intraday_stop_panel(stop_day_open=9.15, stop_day_low=9.0),
                               signals, stock_stop_loss=-0.08)
        stop_day = [t for t in result["trades"] if t["date"] == "2026-01-03"]
        assert ("AAA", "buy") not in [(t["stock_code"], t["side"]) for t in stop_day]
        assert result["summary"]["execution_stats"]["blocked_reentry_after_stop_count"] == 1

    def test_trigger_is_evaluated_exactly_once_per_day(self):
        # 一次盘中触发只能计一次 sell_attempts / sell_fills（两个阶段不得重复评估）
        result = _run_backtest(
            _intraday_stop_panel(),
            {"2026-01-01": {"AAA": 0.99}, "2026-01-02": {"AAA": 0.99}},
            stock_stop_loss=-0.08,
        )
        stats = result["summary"]["execution_stats"]
        assert stats["sell_attempts"] == 1
        assert stats["sell_fills"] == 1
        assert [t["side"] for t in result["trades"]] == ["buy", "stop_loss"]

    def test_summary_declares_execution_timing(self):
        result = _run_backtest(
            _intraday_stop_panel(),
            {"2026-01-01": {"AAA": 0.99}},
            stock_stop_loss=-0.08,
        )
        model = result["summary"]["execution_model"]
        assert model["execution_mode"] == "next_open_rebalance"
        assert model["intraday_risk_exit_cash_available_same_day"] is False
        assert "AFTER the open-price rebalance" in model["risk_exit_timing_assumption"]
        assert model["daily_sequence"] == [
            "1_mark_positions_to_today_open",
            "2_gap_open_risk_exits_at_today_open",
            "3_rebalance_yesterday_signals_at_today_open",
            "4_intraday_touch_risk_exits_after_open_rebalance",
            "5_mark_to_close_and_record_state",
            "6_generate_signals_from_today_close_for_next_open",
        ]
        assert "stamp_tax_exempt_instruments" in model

    def test_signal_close_mode_declares_its_own_sequence(self):
        result = _run_backtest(
            _intraday_stop_panel(),
            {"2026-01-01": {"AAA": 0.5}, "2026-01-02": {"AAA": 0.5}},
            execution_mode="signal_close_to_next_open",
        )
        model = result["summary"]["execution_model"]
        assert model["execution_mode"] == "signal_close_to_next_open"
        assert model["daily_sequence"][0] == "1_exit_overnight_positions_at_today_open"

    def test_unknown_phase_is_rejected(self):
        engine = BacktestEngine(cost_model=ZERO_COST_MODEL)
        engine._reset_diagnostics()
        with pytest.raises(ValueError):
            engine._check_price_risk_exits("2026-01-03", pd.DataFrame(), phase="whenever")
