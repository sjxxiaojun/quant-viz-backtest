import pandas as pd
import pytest

from engine import BacktestEngine, CostModel
from position_manager import PositionManager
from strategy_registry import STRATEGY_REGISTRY


ZERO_COST_MODEL = CostModel(
    commission_rate=0.0,
    commission_min=0.0,
    stamp_tax_rate=0.0,
    slippage_rate=0.0,
    close_slippage_rate=0.0,
    transfer_fee_rate=0.0,
    use_order_slicing=False,
)


def _bar(
    date,
    code,
    open_price,
    close_price,
    low=None,
    high=None,
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
    if low is not None:
        row["low"] = float(low)
    if high is not None:
        row["high"] = float(high)
    if volume is not None:
        row["volume"] = float(volume)
    if prev_close is not None:
        row["prev_close"] = float(prev_close)
    return row


def _run_backtest(rows, signal_map, cost_model=None, **engine_kwargs):
    data = pd.DataFrame(rows)

    def signal_func(date, day_data):
        return signal_map.get(date, {})

    engine = BacktestEngine(
        initial_capital=100000.0,
        cost_model=cost_model or ZERO_COST_MODEL,
        **engine_kwargs,
    )
    dates = sorted(data["date"].unique())
    return engine.run_backtest(data, signal_func, dates[0], dates[-1])


# ---------------------------------------------------------------------------
# 审计 #5：印花税分段费率 + 沪市过户费
# ---------------------------------------------------------------------------

class TestStampTaxSchedule:
    def test_default_rate_is_half_permille_after_cut_date(self):
        cm = CostModel(commission_rate=0.0, commission_min=0.0, slippage_rate=0.0, transfer_fee_rate=0.0)
        bd = cm.calculate_cost_breakdown(100000.0, is_sell=True, trade_date="2024-01-05")
        assert bd["stamp_tax"] == pytest.approx(100000.0 * 0.0005)

    def test_default_rate_uses_legacy_permille_before_cut_date(self):
        cm = CostModel(commission_rate=0.0, commission_min=0.0, slippage_rate=0.0, transfer_fee_rate=0.0)
        bd = cm.calculate_cost_breakdown(100000.0, is_sell=True, trade_date="2023-08-25")
        assert bd["stamp_tax"] == pytest.approx(100000.0 * 0.001)

    def test_cut_date_itself_uses_new_rate(self):
        cm = CostModel(commission_rate=0.0, commission_min=0.0, slippage_rate=0.0, transfer_fee_rate=0.0)
        bd = cm.calculate_cost_breakdown(100000.0, is_sell=True, trade_date="2023-08-28")
        assert bd["stamp_tax"] == pytest.approx(100000.0 * 0.0005)

    def test_explicit_custom_rate_stays_flat_across_periods(self):
        cm = CostModel(commission_rate=0.0, commission_min=0.0, slippage_rate=0.0,
                       stamp_tax_rate=0.0, transfer_fee_rate=0.0)
        assert cm.calculate_cost_breakdown(100000.0, True, trade_date="2020-01-02")["stamp_tax"] == 0.0
        cm2 = CostModel(commission_rate=0.0, commission_min=0.0, slippage_rate=0.0,
                        stamp_tax_rate=0.002, transfer_fee_rate=0.0)
        assert cm2.calculate_cost_breakdown(100000.0, True, trade_date="2020-01-02")["stamp_tax"] == pytest.approx(200.0)

    def test_explicit_before_cut_rate_wins(self):
        cm = CostModel(commission_rate=0.0, commission_min=0.0, slippage_rate=0.0,
                       transfer_fee_rate=0.0, stamp_tax_rate_before_cut=0.003)
        bd = cm.calculate_cost_breakdown(100000.0, True, trade_date="2020-01-02")
        assert bd["stamp_tax"] == pytest.approx(300.0)

    def test_no_stamp_tax_on_buy(self):
        cm = CostModel()
        assert cm.calculate_cost_breakdown(100000.0, False, trade_date="2020-01-02")["stamp_tax"] == 0.0


class TestTransferFee:
    def test_sh_stock_pays_transfer_fee_both_directions(self):
        cm = CostModel(commission_rate=0.0, commission_min=0.0, slippage_rate=0.0, stamp_tax_rate=0.0)
        buy = cm.calculate_cost_breakdown(100000.0, False, stock_code="600519")
        sell = cm.calculate_cost_breakdown(100000.0, True, stock_code="600519")
        assert buy["transfer_fee"] == pytest.approx(1.0)
        assert sell["transfer_fee"] == pytest.approx(1.0)

    def test_non_sh_stock_pays_no_transfer_fee(self):
        cm = CostModel(commission_rate=0.0, commission_min=0.0, slippage_rate=0.0, stamp_tax_rate=0.0)
        for code in ("000001", "300750", "430047", None):
            assert cm.calculate_cost_breakdown(100000.0, True, stock_code=code)["transfer_fee"] == 0.0

    def test_engine_records_transfer_fee_in_cost_stats(self):
        cm = CostModel(commission_rate=0.0, commission_min=0.0, slippage_rate=0.0,
                       stamp_tax_rate=0.0, close_slippage_rate=0.0)
        result = _run_backtest(
            [
                _bar("2026-01-01", "600519", 10, 10),
                _bar("2026-01-02", "600519", 10, 10),
                _bar("2026-01-03", "600519", 10, 10),
            ],
            {
                "2026-01-01": {"600519": 1.0},
                "2026-01-02": {},
                "2026-01-03": {},
            },
            cost_model=cm,
        )
        assert result["summary"]["cost_stats"]["transfer_fee_total"] > 0.0
        assert all("transfer_fee" in t for t in result["trades"])


# ---------------------------------------------------------------------------
# 审计 #6：收盘成交尾盘滑点 + order_slicing 显式化
# ---------------------------------------------------------------------------

class TestCloseSlippage:
    def test_close_fill_uses_close_slippage_rate(self):
        cm = CostModel(commission_rate=0.0, commission_min=0.0, stamp_tax_rate=0.0,
                       transfer_fee_rate=0.0, slippage_rate=0.0003, close_slippage_rate=0.0015)
        open_bd = cm.calculate_cost_breakdown(100000.0, False)
        close_bd = cm.calculate_cost_breakdown(100000.0, False, at_close=True)
        assert open_bd["slippage"] == pytest.approx(30.0)
        assert close_bd["slippage"] == pytest.approx(150.0)

    def test_order_slicing_defaults_off(self):
        cm = CostModel()
        assert cm.use_order_slicing is False

    def test_order_slicing_factor_is_explicit_parameter(self):
        cm = CostModel(commission_rate=0.0, commission_min=0.0, stamp_tax_rate=0.0,
                       transfer_fee_rate=0.0, slippage_rate=0.001,
                       use_order_slicing=True, order_slicing_slippage_factor=0.5)
        assert cm.calculate_cost_breakdown(100000.0, False)["slippage"] == pytest.approx(50.0)

    def test_signal_close_mode_charges_close_slippage_on_entry(self):
        cm = CostModel(commission_rate=0.0, commission_min=0.0, stamp_tax_rate=0.0,
                       transfer_fee_rate=0.0, slippage_rate=0.0, close_slippage_rate=0.001)
        result = _run_backtest(
            [
                _bar("2026-01-01", "AAA", 10.0, 10.0),
                _bar("2026-01-02", "AAA", 10.0, 10.0),
            ],
            {"2026-01-01": {"AAA": 1.0}},
            cost_model=cm,
            execution_mode="signal_close_to_next_open",
        )
        buys = [t for t in result["trades"] if t["side"] == "buy"]
        sells = [t for t in result["trades"] if t["side"] == "sell"]
        assert len(buys) == 1 and len(sells) == 1
        # 收盘买入按 close_slippage_rate 计滑点，次日开盘卖出按 slippage_rate（=0）
        assert buys[0]["slippage"] == pytest.approx(buys[0]["notional"] * 0.001)
        assert sells[0]["slippage"] == 0.0


# ---------------------------------------------------------------------------
# 审计 #7：止损/止盈日内触价
# ---------------------------------------------------------------------------

class TestIntradayRiskExits:
    def test_stop_loss_triggers_on_intraday_low_and_fills_at_stop_price(self):
        # 买入价 10，止损 -8% -> 9.2；开盘 9.8 未破位，盘中 low 9.0 触价 -> 按 9.2 成交
        result = _run_backtest(
            [
                _bar("2026-01-01", "AAA", 10, 10, low=10, high=10),
                _bar("2026-01-02", "AAA", 10, 10, low=10, high=10),
                _bar("2026-01-03", "AAA", 9.8, 9.1, low=9.0, high=9.9, prev_close=10.0),
            ],
            {
                "2026-01-01": {"AAA": 1.0},
                "2026-01-02": {"AAA": 1.0},
                "2026-01-03": {"AAA": 1.0},
            },
            stock_stop_loss=-0.08,
        )
        exits = [t for t in result["trades"] if t["side"] == "stop_loss"]
        assert len(exits) == 1
        assert exits[0]["price"] == pytest.approx(10.0 * 0.92)

    def test_stop_loss_gap_open_fills_at_open(self):
        result = _run_backtest(
            [
                _bar("2026-01-01", "AAA", 10, 10, low=10, high=10),
                _bar("2026-01-02", "AAA", 10, 10, low=10, high=10),
                _bar("2026-01-03", "AAA", 9.1, 9.1, low=8.9, high=9.2, prev_close=10.0, pct_chg=-9.0),
            ],
            {
                "2026-01-01": {"AAA": 1.0},
                "2026-01-02": {"AAA": 1.0},
                "2026-01-03": {"AAA": 1.0},
            },
            stock_stop_loss=-0.08,
        )
        # 开盘 9.1 已破 9.2（未及跌停）-> 按开盘价成交（跳空劣于触发价）
        exits = [t for t in result["trades"] if t["side"] == "stop_loss"]
        assert len(exits) == 1
        assert exits[0]["price"] == pytest.approx(9.1)

    def test_stop_loss_deferred_when_fill_price_at_limit_down(self):
        # 主板 ±10%：跌停近似阈值 9.5%。买入价 10.5，止损价 9.66；
        # 当日 prev_close 10.7，low 9.5 触价，但 9.66 相对 10.7 已跌 9.7% > 9.5% -> 顺延
        result = _run_backtest(
            [
                _bar("2026-01-01", "AAA", 10.5, 10.5, low=10.5, high=10.5),
                _bar("2026-01-02", "AAA", 10.5, 10.7, low=10.5, high=10.7),
                _bar("2026-01-03", "AAA", 10.2, 9.63, low=9.5, high=10.2, prev_close=10.7),
            ],
            {
                "2026-01-01": {"AAA": 1.0},
                "2026-01-02": {"AAA": 1.0},
                "2026-01-03": {"AAA": 1.0},
            },
            stock_stop_loss=-0.08,
        )
        assert [t["side"] for t in result["trades"]] == ["buy"]
        assert result["summary"]["execution_stats"]["blocked_limit_down_sell_count"] == 1

    def test_take_profit_triggers_on_intraday_high(self):
        # 买入价 10，止盈 +10% -> 11；开盘 10.5 未达标，盘中 high 11.2 -> 按 11 成交
        result = _run_backtest(
            [
                _bar("2026-01-01", "AAA", 10, 10, low=10, high=10),
                _bar("2026-01-02", "AAA", 10, 10, low=10, high=10),
                _bar("2026-01-03", "AAA", 10.5, 10.8, low=10.4, high=11.2, prev_close=10.0),
            ],
            {
                "2026-01-01": {"AAA": 1.0},
                "2026-01-02": {"AAA": 1.0},
                "2026-01-03": {"AAA": 1.0},
            },
            stock_stop_loss=-0.5,
            take_profit=0.10,
        )
        exits = [t for t in result["trades"] if t["side"] == "take_profit"]
        assert len(exits) == 1
        assert exits[0]["price"] == pytest.approx(11.0)

    def test_no_intraday_trigger_without_low_high_columns(self):
        # 无 low/high 数据时退化为原开盘价判定，不误触发
        result = _run_backtest(
            [
                _bar("2026-01-01", "AAA", 10, 10),
                _bar("2026-01-02", "AAA", 10, 10),
                _bar("2026-01-03", "AAA", 9.5, 9.5),
            ],
            {
                "2026-01-01": {"AAA": 1.0},
                "2026-01-02": {"AAA": 1.0},
                "2026-01-03": {"AAA": 1.0},
            },
            stock_stop_loss=-0.08,
        )
        assert [t["side"] for t in result["trades"]] == ["buy"]

    def test_summary_declares_fill_assumption(self):
        result = _run_backtest(
            [
                _bar("2026-01-01", "AAA", 10, 10),
                _bar("2026-01-02", "AAA", 10, 10),
            ],
            {"2026-01-01": {"AAA": 1.0}},
        )
        assert "risk_exit_fill_assumption" in result["summary"]["execution_model"]


# ---------------------------------------------------------------------------
# 审计 #8：ST 涨跌幅分板块 + 名称兜底 WARNING
# ---------------------------------------------------------------------------

class TestSTLimitByBoard:
    def _engine(self):
        engine = BacktestEngine(cost_model=ZERO_COST_MODEL)
        engine._reset_diagnostics()
        return engine

    def test_gem_st_uses_20cm_threshold(self):
        row = pd.Series({"stock_code": "300001", "stock_name": "ST某某", "is_st": 1})
        assert self._engine()._limit_move_threshold(row) == pytest.approx(0.195)

    def test_star_st_uses_20cm_threshold(self):
        row = pd.Series({"stock_code": "688001", "stock_name": "*ST某某", "is_st": 1})
        assert self._engine()._limit_move_threshold(row) == pytest.approx(0.195)

    def test_bse_st_uses_30cm_threshold(self):
        row = pd.Series({"stock_code": "830001", "stock_name": "ST某某", "is_st": 1})
        assert self._engine()._limit_move_threshold(row) == pytest.approx(0.295)

    def test_main_board_st_uses_5pct_threshold(self):
        row = pd.Series({"stock_code": "600001", "stock_name": "ST某某", "is_st": 1})
        assert self._engine()._limit_move_threshold(row) == pytest.approx(0.045)

    def test_st_name_fallback_only_without_is_st_field_and_warns(self, caplog):
        engine = self._engine()
        row_with_field = pd.Series({"stock_code": "600001", "stock_name": "ST某某", "is_st": 0})
        assert engine._is_st_stock(row_with_field) is False

        row_without_field = pd.Series({"stock_code": "600002", "stock_name": "ST某某"})
        with caplog.at_level("WARNING", logger="engine"):
            assert engine._is_st_stock(row_without_field) is True
        assert any("is_st" in rec.message for rec in caplog.records)

    def test_limit_move_threshold_is_configurable(self):
        engine = BacktestEngine(cost_model=ZERO_COST_MODEL, limit_move_threshold=0.098)
        row = pd.Series({"stock_code": "600001", "stock_name": "普通股", "is_st": 0})
        assert engine._limit_move_threshold(row) == pytest.approx(0.098)


# ---------------------------------------------------------------------------
# 审计 #15：新股无涨跌幅期
# ---------------------------------------------------------------------------

class TestNewStockNoLimitWindow:
    def test_gem_new_stock_first_five_days_skip_limit_check(self):
        # OLD 从面板首日就存在（老股），NEW 从第 2 个交易日起出现（近似新股）。
        rows = [
            _bar("2026-01-01", "OLD", 10, 10),
            _bar("2026-01-02", "OLD", 10, 10),
            # 新股第 1 个交易日暴涨 100%，若做常规拦截将无法买入
            _bar("2026-01-02", "300999", 20.0, 22.0, prev_close=10.0),
            _bar("2026-01-03", "OLD", 10, 10),
            _bar("2026-01-03", "300999", 22.0, 22.0, prev_close=22.0),
        ]
        result = _run_backtest(
            rows,
            {
                "2026-01-01": {"300999": 1.0},
                "2026-01-02": {},
                "2026-01-03": {},
            },
        )
        buys = [t for t in result["trades"] if t["side"] == "buy"]
        assert [t["stock_code"] for t in buys] == ["300999"]
        stats = result["summary"]["execution_stats"]
        assert stats["blocked_limit_up_buy_count"] == 0
        assert stats["limit_check_skipped_new_stock_count"] >= 1

    def test_gem_new_stock_limit_applies_after_five_days(self):
        dates = [f"2026-01-{d:02d}" for d in range(1, 10)]
        rows = [_bar(d, "OLD", 10, 10) for d in dates]
        # 新股从第 2 个面板日出现，第 7 个自身交易日（序号 6 >= 5）涨 21% 应被拦截
        for i, d in enumerate(dates[1:]):
            price = 10.0 * (1.21 ** i)
            rows.append(_bar(d, "300999", price, price, prev_close=price / 1.21))
        signal_map = {dates[i]: {"300999": 1.0} for i in range(6, 8)}
        result = _run_backtest(rows, signal_map)
        assert result["summary"]["execution_stats"]["blocked_limit_up_buy_count"] >= 1

    def test_stock_present_from_panel_start_is_not_treated_as_new(self):
        rows = [
            _bar("2026-01-01", "AAA", 10, 10),
            _bar("2026-01-02", "AAA", 11.0, 11.0, prev_close=10.0, pct_chg=10.0),
        ]
        result = _run_backtest(rows, {"2026-01-01": {"AAA": 1.0}})
        stats = result["summary"]["execution_stats"]
        assert stats["blocked_limit_up_buy_count"] == 1
        assert stats["limit_check_skipped_new_stock_count"] == 0


# ---------------------------------------------------------------------------
# 审计 #19（部分）：持仓天数按实际交易日行数计
# ---------------------------------------------------------------------------

class TestHoldingDaysTradingCalendar:
    def test_days_between_counts_only_observed_trading_dates(self):
        manager = PositionManager(
            max_positions=2,
            weight_mode="equal",
            strategy_spec=STRATEGY_REGISTRY["overnight"],
        )
        policy = manager.policy
        # 模拟春节休市：01-28（周三）后直接跳到 02-05（周四），bdate_range 会数出 6 个工作日
        for d in ["2026-01-27", "2026-01-28", "2026-02-05", "2026-02-06"]:
            policy._register_trading_date(d)
        assert policy._days_between("2026-01-27", "2026-02-06") == 3
        assert policy._days_between("2026-01-28", "2026-02-05") == 1

    def test_days_between_zero_for_same_date(self):
        manager = PositionManager(
            max_positions=1,
            weight_mode="equal",
            strategy_spec=STRATEGY_REGISTRY["overnight"],
        )
        policy = manager.policy
        policy._register_trading_date("2026-01-05")
        assert policy._days_between("2026-01-05", "2026-01-05") == 0


# ---------------------------------------------------------------------------
# 审计 #20：风险指标参数化
# ---------------------------------------------------------------------------

class TestRiskMetricParams:
    def test_default_risk_free_and_annualization(self):
        engine = BacktestEngine(cost_model=ZERO_COST_MODEL)
        assert engine.risk_free_rate == pytest.approx(0.025)
        assert engine.annualization_factor == 252

    def test_custom_params_change_sharpe(self):
        returns = pd.Series([0.01, -0.005, 0.002, 0.008, -0.001])
        base = BacktestEngine(cost_model=ZERO_COST_MODEL)
        custom = BacktestEngine(cost_model=ZERO_COST_MODEL, risk_free_rate=0.0, annualization_factor=244)
        assert base._calc_sharpe(returns) != custom._calc_sharpe(returns)

    def test_summary_reports_annualization_params(self):
        result = _run_backtest(
            [
                _bar("2026-01-01", "AAA", 10, 10),
                _bar("2026-01-02", "AAA", 10, 10),
            ],
            {"2026-01-01": {"AAA": 1.0}},
            risk_free_rate=0.02,
            annualization_factor=250,
        )
        model = result["summary"]["execution_model"]
        assert model["risk_free_rate"] == pytest.approx(0.02)
        assert model["annualization_factor"] == 250


# ---------------------------------------------------------------------------
# 审计 #21/#22（部分）：停牌持仓诊断
# ---------------------------------------------------------------------------

class TestSuspendedPositionDiagnostics:
    def test_missing_rows_counted_as_suspended_positions(self):
        rows = [
            _bar("2026-01-01", "AAA", 10, 10),
            _bar("2026-01-01", "BBB", 20, 20),
            _bar("2026-01-02", "AAA", 10, 10),
            _bar("2026-01-02", "BBB", 20, 20),
            # 01-03/01-04 AAA 无行情（停牌），持仓按最后价估值
            _bar("2026-01-03", "BBB", 20, 20),
            _bar("2026-01-04", "BBB", 20, 20),
        ]
        result = _run_backtest(
            rows,
            {
                "2026-01-01": {"AAA": 1.0},
                "2026-01-02": {"AAA": 1.0},
                "2026-01-03": {"AAA": 1.0},
                "2026-01-04": {"AAA": 1.0},
            },
        )
        summary = result["summary"]
        assert summary["suspended_positions_count"] == 1
        assert summary["execution_stats"]["stale_position_days"] == 2

    def test_no_suspended_positions_when_data_complete(self):
        result = _run_backtest(
            [
                _bar("2026-01-01", "AAA", 10, 10),
                _bar("2026-01-02", "AAA", 10, 10),
            ],
            {"2026-01-01": {"AAA": 1.0}},
        )
        assert result["summary"]["suspended_positions_count"] == 0
