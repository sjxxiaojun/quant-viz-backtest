import logging
import pandas as pd
import numpy as np
import inspect
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# A股印花税（仅卖出计征）：财政部、税务总局公告 2023 年第 39 号，
# 自 2023-08-28 起证券交易印花税税率由 0.1% 减半至 0.05%。
STAMP_TAX_CUT_DATE = "2023-08-28"
STAMP_TAX_RATE_CURRENT = 0.0005   # 2023-08-28（含）之后
STAMP_TAX_RATE_LEGACY = 0.001     # 2023-08-28 之前

# A股过户费：沪深北统一按成交金额0.001%双向收取（2022-04-29起），此前按市场分段。
SH_TRANSFER_FEE_RATE = 0.00001

# 《中华人民共和国印花税法》（2022-07-01 施行）规定：证券交易印花税的征税范围是
# 「转让在依法设立的证券交易所上市交易的股票和以股票为基础发行的存托凭证」，
# 且对出让方单边计征。基金份额（ETF / LOF / 封闭式基金）与债券（含可转债、
# 可交换债）不在征税范围内，卖出**免征**印花税。
#
# 本仓库的 stock_code 统一为不带交易所前后缀的 6 位数字码
# （见 data_manager._normalize_symbol 与 data_manager.ETF_PREFIXES）。据此判别：
#   "5" 开头 —— 沪市基金：51/56/58 为 ETF（510/511/512/513/515/516/517/518、
#               560/561/562/563、588/589），50/52/53/55 为封基/LOF/跨境 ETF；
#               沪市股票只有 60/68 开头（B 股 900），不存在 5 开头的股票。
#   "1" 开头 —— 深市基金 15/16/18（159 为 ETF，16x 为 LOF，15x 含分级份额）
#               与沪深债券 10/11/12/13/14（沪可转债 110/113、深可转债 12x）；
#               沪深北三市都不存在 1 开头的股票。
# 其余（沪 60/68、深 00/30、北交所 43/83/87/88/92、B 股 200/900）照章计征。
STAMP_TAX_EXEMPT_CODE_PREFIXES = ("1", "5")

@dataclass
class CostModel:
    commission_rate: float = 0.0003
    commission_min: float = 5.0
    stamp_tax_rate: float = STAMP_TAX_RATE_CURRENT
    slippage_rate: float = 0.0003 # Reduced to 0.03% (Institutional Grade)
    # 订单拆分（algo slicing）对冲击成本的折减是执行假设而非市场规则，
    # 必须显式开启；折减系数同样显式参数化。
    use_order_slicing: bool = False
    order_slicing_slippage_factor: float = 0.5
    # 尾盘（收盘价）成交滑点：尾盘竞价/扫货时收盘价与实际可得均价偏差
    # 显著大于日内 VWAP 执行，独立参数化。
    close_slippage_rate: float = 0.0015
    # 股票过户费（买卖双向，沪深北按成交日费率）。
    transfer_fee_rate: float = SH_TRANSFER_FEE_RATE
    # 显式指定 2023-08-28 之前的印花税率；为 None 时：
    # - stamp_tax_rate 等于法定现行默认值 0.0005 -> 按法定分段自动取 0.001；
    # - stamp_tax_rate 为自定义值（含 0）-> 全区间使用该自定义值（向后兼容）。
    stamp_tax_rate_before_cut: Optional[float] = None

    def _resolve_stamp_tax_rate(self, trade_date: Optional[str]) -> float:
        if trade_date is not None and str(trade_date)[:10] < STAMP_TAX_CUT_DATE:
            if self.stamp_tax_rate_before_cut is not None:
                return self.stamp_tax_rate_before_cut
            if self.stamp_tax_rate == STAMP_TAX_RATE_CURRENT:
                return STAMP_TAX_RATE_LEGACY
        return self.stamp_tax_rate

    @staticmethod
    def _normalized_code(stock_code: Optional[str]) -> str:
        """归一化为 6 位纯数字代码；兼容 'sh.600519' / '600519.SH' 等带前后缀写法。

        无法归一化为 6 位数字（如测试里的占位代码 'AAA'）时返回空串，
        调用方按「非豁免品种」处理，即保持原有的按股票计税行为。
        """
        text = str(stock_code or "").strip()
        if "." in text:
            digits = [part for part in text.split(".") if part.isdigit()]
            text = digits[0] if digits else ""
        return text if len(text) == 6 and text.isdigit() else ""

    @classmethod
    def is_stamp_tax_exempt(cls, stock_code: Optional[str]) -> bool:
        """ETF/LOF/基金份额与债券（含可转债）卖出免征证券交易印花税。"""
        code = cls._normalized_code(stock_code)
        return bool(code) and code.startswith(STAMP_TAX_EXEMPT_CODE_PREFIXES)

    @classmethod
    def _is_sh_stock(cls, stock_code: Optional[str]) -> bool:
        """股票过户费（保留旧方法名兼容调用方）；基金/债券不适用。"""
        code = cls._normalized_code(stock_code)
        return bool(code) and not cls.is_stamp_tax_exempt(code)

    def calculate_cost_breakdown(
        self,
        amount: float,
        is_sell: bool,
        trade_date: Optional[str] = None,
        stock_code: Optional[str] = None,
        at_close: bool = False,
    ) -> Dict[str, float]:
        commission = max(amount * self.commission_rate, self.commission_min)
        # 印花税：仅卖出计征，且 ETF/LOF/基金份额与债券（含可转债）免征。
        stamp_tax = (
            amount * self._resolve_stamp_tax_rate(trade_date)
            if is_sell and not self.is_stamp_tax_exempt(stock_code)
            else 0.0
        )
        transfer_rate = self.transfer_fee_rate
        if transfer_rate == SH_TRANSFER_FEE_RATE and trade_date and str(trade_date) < "2022-04-29":
            transfer_rate = .000025 if self._normalized_code(stock_code).startswith(("43", "83", "87", "88", "92")) else .00002
        transfer_fee = amount * transfer_rate if self._is_sh_stock(stock_code) else 0.0
        base_slippage_rate = self.close_slippage_rate if at_close else self.slippage_rate
        effective_slippage = (
            base_slippage_rate * self.order_slicing_slippage_factor
            if self.use_order_slicing
            else base_slippage_rate
        )
        slippage = amount * effective_slippage
        total = commission + stamp_tax + transfer_fee + slippage
        return {
            "commission": float(commission),
            "stamp_tax": float(stamp_tax),
            "transfer_fee": float(transfer_fee),
            "slippage": float(slippage),
            "total": float(total),
        }

    def calculate_total_cost(
        self,
        amount: float,
        is_sell: bool,
        trade_date: Optional[str] = None,
        stock_code: Optional[str] = None,
        at_close: bool = False,
    ) -> float:
        return self.calculate_cost_breakdown(
            amount, is_sell, trade_date=trade_date, stock_code=stock_code, at_close=at_close
        )["total"]

@dataclass
class Lot:
    quantity: int
    price: float
    entry_date: str
    available_from: Optional[str] = None


@dataclass
class Position:
    stock_code: str
    stock_name: str
    quantity: int
    avg_price: float
    market_value: float = 0.0
    industry: Optional[str] = None
    entry_date: Optional[str] = None
    lots: List[Lot] = field(default_factory=list)
    deferred_intent: Optional[str] = None

    def __post_init__(self):
        if not self.lots and self.quantity > 0:
            self.lots = [
                Lot(
                    quantity=self.quantity,
                    price=self.avg_price,
                    entry_date=self.entry_date or "1970-01-01",
                    available_from=self.entry_date or "1970-01-01",
                )
            ]

    def available_quantity(self, current_date: str, enforce_t1: bool = True) -> int:
        if not enforce_t1:
            return sum(lot.quantity for lot in self.lots if not lot.available_from or lot.available_from <= current_date) if self.lots else self.quantity
        if not self.lots:
            return self.quantity if (self.entry_date and self.entry_date < current_date) else 0
        return sum(lot.quantity for lot in self.lots if lot.entry_date < current_date and (not lot.available_from or lot.available_from <= current_date))

class Portfolio:
    def __init__(self, initial_capital: float = 1000000.0):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.history: List[Dict] = []
        self.dividend_receivables: List[Dict] = []
        
    @property
    def total_value(self) -> float:
        market_value = sum(pos.market_value for pos in self.positions.values())
        return self.cash + market_value + sum(r["amount"] for r in self.dividend_receivables)

    def record_state(self, date: str, daily_trades: List[Dict]):
        state = {
            'date': date,
            'cash': self.cash,
            'total_value': self.total_value,
            'num_positions': len(self.positions),
            'positions': {code: {'name': pos.stock_name, 'val': pos.market_value} for code, pos in self.positions.items()},
            'daily_trades': daily_trades
        }
        self.history.append(state)

class BacktestEngine:
    CLOSED_TRADE_SIDES = {'sell', 'stop_loss', 'take_profit'}
    # 风险退出（止损/止盈）的两个执行时点：
    # - OPEN：只用当日开盘价即可判定（跳空破位/跳空达标），与开盘调仓同一时点，
    #   释放的现金当日开盘可用（与 _rebalance 内部"先卖后买"一致）。
    # - INTRADAY：需要当日 low/high 才能判定的盘中触价，只有盘中才知道，
    #   必须排在按开盘价执行的调仓之后，否则会用盘中信息为同日开盘买单融资。
    RISK_EXIT_PHASE_OPEN = "open"
    RISK_EXIT_PHASE_INTRADAY = "intraday"
    # A股主板 ±10% 涨跌幅。9.5% 是"触板"近似阈值：开盘涨跌幅达到该阈值即视为
    # 无法成交。语义说明：真实市场只有"封板"（一字板/大封单）才完全不可成交，
    # "触板"（价格摸到涨跌停但盘中有开板）仍可能部分成交；本阈值把触板一律按
    # 不可成交处理，属于保守近似，可通过构造参数 limit_move_threshold 调整。
    LIMIT_MOVE_THRESHOLD: float = 0.095
    # 创业板(300/301)/科创板(688/689) ±20%，注册制下含 ST 股同为 ±20%。
    GEM_STAR_LIMIT_MOVE: float = 0.195
    # 北交所(43/83/87/88/92) ±30%，含 ST 股同为 ±30%。
    BSE_LIMIT_MOVE: float = 0.295
    # 仅主板 ST/*ST 股为 ±5%。
    ST_MAIN_BOARD_LIMIT_MOVE: float = 0.045
    # 创业板/科创板新股上市前 5 个交易日不设涨跌幅限制。
    GEM_STAR_NO_LIMIT_DAYS: int = 5
    # 主板新股首日按发行价 +44%/-36% 有效申报价范围（近似为不做常规涨跌停拦截）；
    # 北交所新股首日无涨跌幅限制。
    OTHER_BOARD_NO_LIMIT_DAYS: int = 1

    def __init__(
        self,
        initial_capital: float = 1000000.0,
        cost_model: Optional[CostModel] = None,
        stock_stop_loss: float = -0.08,       # 个股止损线：-8%
        take_profit: Optional[float] = None,  # 个股止盈线，例如 0.1 表示 +10%
        portfolio_circuit_breaker: Optional[float] = None,  # Deprecated/no-op: kept for old callers.
        circuit_breaker_reset: Optional[float] = None,      # Deprecated/no-op: kept for old callers.
        execution_mode: str = "next_open_rebalance",
        max_volume_participation: Optional[float] = 0.10,
        enforce_tradability: bool = True,
        enforce_t1: bool = True,
        limit_move_threshold: Optional[float] = None,  # 主板涨跌停"触板"近似阈值，None 用类默认 0.095
        risk_free_rate: float = 0.025,        # 年化无风险利率（Sharpe 用）
        annualization_factor: int = 252,      # 年化交易日天数
    ):
        self.initial_capital = initial_capital
        self.cost_model = cost_model or CostModel()
        self.portfolio = Portfolio(initial_capital)
        self.trades = []
        self.stock_stop_loss = stock_stop_loss
        self.take_profit = take_profit
        self.portfolio_circuit_breaker = portfolio_circuit_breaker
        self.circuit_breaker_reset = circuit_breaker_reset
        self.execution_mode = execution_mode
        self.max_volume_participation = max_volume_participation
        self.enforce_tradability = enforce_tradability
        self.enforce_t1 = enforce_t1
        self.limit_move_threshold = (
            limit_move_threshold if limit_move_threshold is not None else self.LIMIT_MOVE_THRESHOLD
        )
        self.risk_free_rate = risk_free_rate
        self.annualization_factor = annualization_factor
        self._st_name_fallback_warned: Set[str] = set()
        # 新股无涨跌幅期近似：以数据面板中该代码首次出现日起算交易日序号。
        self._code_first_date: Dict[str, str] = {}
        self._global_date_index: Dict[str, int] = {}
        self._panel_first_date: Optional[str] = None

    def _reset_diagnostics(self):
        self.execution_stats = {
            "buy_attempts": 0,
            "buy_fills": 0,
            "sell_attempts": 0,
            "sell_fills": 0,
            "blocked_limit_up_buy_count": 0,
            "blocked_limit_down_sell_count": 0,
            "blocked_halt_trade_count": 0,
            "blocked_no_volume_trade_count": 0,
            "blocked_invalid_price_count": 0,
            "blocked_volume_limit_count": 0,
            "blocked_reentry_after_stop_count": 0,
            "delayed_exit_count": 0,
            "insufficient_cash_buy_count": 0,
            "zero_qty_buy_count": 0,
            "partial_fill_count": 0,
            "t1_sell_block_count": 0,
            "volume_limited_share_count": 0,
            # 新股无涨跌幅期内跳过涨跌停拦截的次数（单列，便于审计）。
            "limit_check_skipped_new_stock_count": 0,
            # 持仓期间无行情数据（停牌或数据缺行）的持仓·日累计数。
            "stale_position_days": 0,
        }
        self.cost_stats = {
            "commission_total": 0.0,
            "stamp_tax_total": 0.0,
            "transfer_fee_total": 0.0,
            "slippage_total": 0.0,
            "total_cost": 0.0,
        }
        self.turnover_amount = 0.0
        self.round_trips: List[Dict] = []
        self._open_round_trips: Dict[str, Dict] = {}
        self._suspended_position_codes: Set[str] = set()

    def _record_cost_breakdown(self, breakdown: Dict[str, float]):
        self.cost_stats["commission_total"] += breakdown["commission"]
        self.cost_stats["stamp_tax_total"] += breakdown["stamp_tax"]
        self.cost_stats["transfer_fee_total"] += breakdown.get("transfer_fee", 0.0)
        self.cost_stats["slippage_total"] += breakdown["slippage"]
        self.cost_stats["total_cost"] += breakdown["total"]

    def _row_for_code(self, day_data: pd.DataFrame, code: str) -> Optional[pd.Series]:
        if day_data.empty:
            return None
        if "stock_code" in day_data.index.names:
            try:
                row = day_data.loc[code]
            except KeyError:
                return None
            if isinstance(row, pd.DataFrame):
                return row.iloc[-1]
            return row

        stock_rows = day_data[day_data["stock_code"] == code]
        if stock_rows.empty:
            return None
        return stock_rows.iloc[-1]

    def _mark_positions_to_price(self, day_data: pd.DataFrame, price_field: str):
        for code, pos in self.portfolio.positions.items():
            stock_row = self._row_for_code(day_data, code)
            if stock_row is not None and pd.notna(stock_row.get(price_field)):
                pos.market_value = pos.quantity * stock_row[price_field]
            elif price_field == "close":
                # 停牌/缺行按最后已知价估值（A股惯例），仅记录诊断计数，
                # 供 summary 的 suspended_positions_count 使用。
                self._suspended_position_codes.add(code)
                self.execution_stats["stale_position_days"] += 1

    def _signal_day_data(self, day_data: pd.DataFrame) -> pd.DataFrame:
        if "stock_code" in day_data.index.names:
            return day_data.reset_index(drop=True)
        return day_data

    def run_backtest(self, data: pd.DataFrame, signal_func, start_date: str, end_date: str, benchmark_data: Optional[pd.DataFrame] = None) -> Dict:
        self.portfolio = Portfolio(self.initial_capital)
        self.trades = []
        self.benchmark_data = benchmark_data
        self._reset_diagnostics()
        
        data = data.sort_values(['date', 'stock_code']).copy()
        self._indicator_by_date = {d: g for d, g in data.groupby("date", sort=False)}
        for field in ("open", "high", "low", "close", "prev_close"):
            if f"raw_{field}" in data:
                data[field] = data[f"raw_{field}"]
        data_by_date = {
            date: group.set_index("stock_code", drop=False)
            for date, group in data.groupby("date", sort=False)
        }
        all_dates = sorted(data_by_date.keys())
        test_dates = [d for d in all_dates if d >= start_date and d <= end_date]

        # 近似上市天数：以该代码在数据面板中的首个日期为"上市日"，交易日序号
        # 用全局日期序列下标差近似（停牌日会轻微高估序号，可接受）。
        self._global_date_index = {d: i for i, d in enumerate(all_dates)}
        self._code_first_date = data.groupby("stock_code")["date"].min().to_dict()
        self._panel_first_date = all_dates[0] if all_dates else None
        
        if self.execution_mode == "signal_close_to_next_open":
            return self._run_signal_close_to_next_open(data_by_date, signal_func, test_dates)

        pending_signals: Optional[Dict[str, float]] = None
        
        for date in test_dates:
            day_data = data_by_date.get(date, pd.DataFrame())
            self.step(date, day_data, pending_signals)
            pending_signals = self._invoke_signal_func(signal_func, date, day_data) or {}

        return self._generate_report()

    def step(self, date, day_data, pending_signals=None):
        """The same daily ledger transition is used by backtests and v2 accounts."""
        if "stock_code" not in day_data.index.names:
            day_data = day_data.set_index("stock_code", drop=False)
        for field in ("open", "high", "low", "close", "prev_close"):
            if f"raw_{field}" in day_data:
                day_data = day_data.copy()
                day_data[field] = day_data[f"raw_{field}"]
        self._t0_codes = set(day_data.loc[pd.to_numeric(day_data.get("settlement_days", pd.Series(1, index=day_data.index)), errors="coerce").eq(0), "stock_code"].astype(str))
        self._apply_company_actions(date, day_data)
        previous = len(self.trades)
        self._mark_positions_to_price(day_data, "open")
        blocked = self._check_price_risk_exits(date, day_data, phase=self.RISK_EXIT_PHASE_OPEN)
        if pending_signals is not None:
            self._rebalance(date, day_data, pending_signals, blocked)
        self._check_price_risk_exits(date, day_data, phase=self.RISK_EXIT_PHASE_INTRADAY)
        self._mark_positions_to_price(day_data, "close")
        self.portfolio.record_state(date, self.trades[previous:])

    def _apply_company_actions(self, date, day_data):
        due = [r for r in self.portfolio.dividend_receivables if r.get("pay_date") and r["pay_date"] <= date]
        self.portfolio.cash += sum(r["amount"] for r in due)
        self.portfolio.dividend_receivables = [r for r in self.portfolio.dividend_receivables if r not in due]
        for code, pos in self.portfolio.positions.items():
            row = self._row_for_code(day_data, code)
            if row is None:
                continue
            dividend = self._safe_float(row.get("cash_dividend_per_share")) or 0.0
            multiplier = self._safe_float(row.get("share_multiplier")) or 1.0
            if dividend:
                if code in self._open_round_trips:
                    info = self._open_round_trips[code]
                    info["dividend_amount"] = info.get("dividend_amount", 0.0) + pos.quantity * dividend
                self.portfolio.dividend_receivables.append({"amount": pos.quantity * dividend, "pay_date": str(row.get("dividend_pay_date") or ""), "stock_code": code})
            if multiplier != 1:
                if multiplier <= 0 or any(abs(lot.quantity * multiplier - round(lot.quantity * multiplier)) > 1e-8 for lot in pos.lots):
                    raise ValueError("公司行动包含无法处理的零碎股，需要明确现金补偿记录。")
                original_quantity = pos.quantity
                for lot in pos.lots:
                    lot.price /= multiplier
                extra = round(original_quantity * (multiplier - 1))
                if extra < 0:
                    raise ValueError("反向合股需要明确零碎股补偿记录。")
                pos.lots.append(Lot(quantity=extra, price=pos.avg_price / multiplier, entry_date=date,
                                    available_from=str(row.get("share_available_date") or date)))
                pos.quantity = sum(lot.quantity for lot in pos.lots)
                pos.avg_price /= multiplier
                if code in self._open_round_trips:
                    self._open_round_trips[code]["qty"] = pos.quantity
                    self._open_round_trips[code]["entry_price"] /= multiplier
        # Same-day payment is available at today's open only when explicitly supplied.
        due = [r for r in self.portfolio.dividend_receivables if r.get("pay_date") and r["pay_date"] <= date]
        self.portfolio.cash += sum(r["amount"] for r in due)
        self.portfolio.dividend_receivables = [r for r in self.portfolio.dividend_receivables if r not in due]

    def _run_signal_close_to_next_open(self, data_by_date: Dict[str, pd.DataFrame], signal_func, test_dates: List[str]) -> Dict:
        if not test_dates:
            return {}

        last_date = test_dates[-1]
        for date in test_dates:
            day_data = data_by_date.get(date, pd.DataFrame())
            prev_trade_count = len(self.trades)
            open_exit_codes: Set[str] = set(self.portfolio.positions.keys())
            residual_exit_codes: Set[str] = set()

            # 1. Exit overnight positions at today's open.
            if self.portfolio.positions:
                self._liquidate_positions(date, day_data, side="sell", price_field="open")
                residual_exit_codes = open_exit_codes.intersection(self.portfolio.positions.keys())

            # 2. Enter new overnight positions at today's close, except on the last date.
            if date != last_date:
                close_signals = self._invoke_signal_func(signal_func, date, day_data) or {}
                if close_signals:
                    self._rebalance_close(date, day_data, close_signals, skip_exit_codes=residual_exit_codes)

            # 3. Mark positions to market at today's close for end-of-day portfolio state.
            self._mark_positions_to_price(day_data, "close")

            today_trades = self.trades[prev_trade_count:]
            self.portfolio.record_state(date, today_trades)

        return self._generate_report()

    def _invoke_signal_func(self, signal_func, date: str, day_data: pd.DataFrame) -> Dict[str, float]:
        signal_day_data = getattr(self, "_indicator_by_date", {}).get(date, self._signal_day_data(day_data))
        try:
            signature = inspect.signature(signal_func)
            params = list(signature.parameters.values())
            has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in params)
            positional_params = [
                p for p in params
                if p.kind in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
            ]
            if has_varargs or len(positional_params) >= 3:
                return signal_func(date, signal_day_data, self.portfolio.positions)
        except (TypeError, ValueError):
            pass
        return signal_func(date, signal_day_data)

    def _get_prev_close(self, stock_row: pd.Series) -> Optional[float]:
        prev_close = stock_row.get("prev_close")
        if pd.notna(prev_close) and float(prev_close) > 0:
            return float(prev_close)

        change = stock_row.get("change")
        close_price = stock_row.get("close")
        if pd.notna(change) and pd.notna(close_price):
            inferred_prev_close = float(close_price) - float(change)
            if inferred_prev_close > 0:
                return inferred_prev_close

        pct_chg = stock_row.get("pct_chg")
        if pd.notna(pct_chg) and pd.notna(close_price):
            denominator = 1.0 + (float(pct_chg) / 100.0)
            if denominator > 0:
                inferred_prev_close = float(close_price) / denominator
                if inferred_prev_close > 0:
                    return inferred_prev_close

        return None

    def _safe_float(self, value) -> Optional[float]:
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _is_st_stock(self, stock_row: pd.Series) -> bool:
        raw_is_st = stock_row.get("is_st")
        if raw_is_st is not None and not pd.isna(raw_is_st):
            text = str(raw_is_st).strip().lower()
            if text in {"1", "1.0", "true", "yes", "y", "st"}:
                return True
            if text in {"0", "0.0", "false", "no", "n", ""}:
                return False

        # 兜底：仅在数据源无 is_st 字段时用股票名判断。股票名是"当前名称"，
        # 回溯全历史会把非 ST 时段误判为 ST，因此必须显式告警。
        name = str(stock_row.get("stock_name", "") or "").upper()
        if "ST" in name or "退" in name:
            code = str(stock_row.get("stock_code", "") or "")
            if code not in self._st_name_fallback_warned:
                self._st_name_fallback_warned.add(code)
                logger.warning(
                    "is_st field missing for %s; falling back to current stock name '%s' "
                    "to infer ST status — this may mislabel historical non-ST periods.",
                    code,
                    name,
                )
            return True
        return False

    def _limit_move_threshold(self, stock_row: pd.Series) -> float:
        # 先判板块再判 ST：注册制下创业板/科创板（含 ST）±20%、北交所（含 ST）±30%，
        # 仅主板 ST 为 ±5%。
        code = str(stock_row.get("stock_code", "") or "")
        explicit = self._safe_float(stock_row.get("price_limit_pct"))
        if explicit is not None:
            return explicit - .005
        # SZSE's 2020-08-24 fund list explicitly includes the default 159915 pool member.
        if code == "159915" and str(stock_row.get("date") or "9999") >= "2020-08-24":
            return self.GEM_STAR_LIMIT_MOVE
        if code.startswith(("300", "301")) and stock_row.get("date") and str(stock_row["date"]) < "2020-08-24":
            return self.ST_MAIN_BOARD_LIMIT_MOVE if self._is_st_stock(stock_row) else self.limit_move_threshold
        if code.startswith(("300", "301", "688", "689")):
            return self.GEM_STAR_LIMIT_MOVE
        if code.startswith(("43", "83", "87", "88", "92")):
            return self.BSE_LIMIT_MOVE
        if self._is_st_stock(stock_row):
            return self.ST_MAIN_BOARD_LIMIT_MOVE
        return self.limit_move_threshold

    def _in_no_limit_window(self, stock_row: pd.Series) -> bool:
        """新股上市初期无涨跌幅限制：创业板/科创板前 5 个交易日；主板首日
        （+44%/-36% 有效申报范围近似为不拦截）；北交所首日无限制。

        上市天数用"数据面板中该代码首次出现日"起算的交易日序号近似；
        与面板同日起始的代码视为存量老股，不适用。"""
        if "raw_open" in stock_row.index and not stock_row.get("listing_date"):
            return False
        if not self._global_date_index or self._panel_first_date is None:
            return False
        code = str(stock_row.get("stock_code", "") or "")
        date = stock_row.get("date")
        first_date = self._code_first_date.get(code)
        if first_date is None or date is None:
            return False
        if first_date == self._panel_first_date:
            return False
        first_idx = self._global_date_index.get(first_date)
        cur_idx = self._global_date_index.get(date)
        if first_idx is None or cur_idx is None:
            return False
        listing_day_ordinal = cur_idx - first_idx  # 0 = 上市首日（近似）
        if code.startswith(("300", "301", "688", "689")):
            return listing_day_ordinal < self.GEM_STAR_NO_LIMIT_DAYS
        return listing_day_ordinal < self.OTHER_BOARD_NO_LIMIT_DAYS

    def _hits_limit(self, stock_row: pd.Series, price_field: str, direction: str) -> bool:
        prev_close = self._get_prev_close(stock_row)
        price = stock_row.get(price_field)
        if prev_close is None or pd.isna(price):
            return False

        if self._in_no_limit_window(stock_row):
            self.execution_stats["limit_check_skipped_new_stock_count"] += 1
            return False

        move_pct = (float(price) - prev_close) / prev_close
        threshold = self._limit_move_threshold(stock_row)
        if direction == "up":
            return move_pct >= threshold
        if direction == "down":
            return move_pct <= -threshold
        raise ValueError(f"Unsupported limit direction: {direction}")

    def _trade_block_reason(self, stock_row: pd.Series, price_field: str, side: str) -> Optional[str]:
        price = self._safe_float(stock_row.get(price_field))
        if price is None or price <= 0:
            return "invalid_price"

        if self.enforce_tradability:
            tradestatus = stock_row.get("tradestatus")
            if tradestatus is not None and not pd.isna(tradestatus):
                status = str(tradestatus).strip().lower()
                if status and status not in {"1", "1.0", "true", "trading", "trade", "active", "open", "交易", "正常"}:
                    return "halted"

            volume = self._safe_float(stock_row.get("volume"))
            if volume is not None and volume <= 0:
                return "no_volume"

        if side == "buy" and self._hits_limit(stock_row, price_field, "up"):
            return "limit_up"
        if side == "sell" and self._hits_limit(stock_row, price_field, "down"):
            return "limit_down"
        return None

    def _record_trade_block(self, reason: str, side: str):
        if reason == "limit_up" and side == "buy":
            self.execution_stats["blocked_limit_up_buy_count"] += 1
        elif reason == "limit_down" and side == "sell":
            self.execution_stats["blocked_limit_down_sell_count"] += 1
        elif reason == "halted":
            self.execution_stats["blocked_halt_trade_count"] += 1
        elif reason == "no_volume":
            self.execution_stats["blocked_no_volume_trade_count"] += 1
        elif reason == "invalid_price":
            self.execution_stats["blocked_invalid_price_count"] += 1

    def _is_t1_sell_blocked(self, pos: Position, date: str) -> bool:
        if not self.enforce_t1:
            return False
        return pos.available_quantity(date, enforce_t1=self.enforce_t1 and not getattr(self, "_t0_codes", set()).__contains__(pos.stock_code)) <= 0

    def _cap_order_quantity(self, stock_row: pd.Series, requested_qty: int) -> Tuple[int, bool]:
        requested_qty = int(requested_qty or 0)
        if requested_qty <= 0:
            return 0, False
        if not self.enforce_tradability:
            return requested_qty, False
        if self.max_volume_participation is None or self.max_volume_participation <= 0:
            return requested_qty, False

        volume = self._safe_float(stock_row.get("volume"))
        if volume is None:
            return requested_qty, False
        if volume <= 0:
            return 0, False

        max_qty = int((volume * self.max_volume_participation) // 100) * 100
        if max_qty <= 0:
            self.execution_stats["blocked_volume_limit_count"] += 1
            self.execution_stats["volume_limited_share_count"] += requested_qty
            return 0, False
        if requested_qty > max_qty:
            self.execution_stats["partial_fill_count"] += 1
            self.execution_stats["volume_limited_share_count"] += requested_qty - max_qty
            return max_qty, True
        return requested_qty, False

    def _open_position(
        self,
        date: str,
        code: str,
        stock_name: str,
        price: float,
        qty: int,
        requested_qty: Optional[int] = None,
        fill_status: str = "filled",
        at_close: bool = False,
    ) -> bool:
        if qty <= 0:
            self.execution_stats["zero_qty_buy_count"] += 1
            return False

        exec_amt = qty * price
        cost_breakdown = self.cost_model.calculate_cost_breakdown(
            exec_amt, False, trade_date=date, stock_code=code, at_close=at_close
        )
        total_cost = cost_breakdown["total"]
        if self.portfolio.cash < (exec_amt + total_cost):
            self.execution_stats["insufficient_cash_buy_count"] += 1
            return False

        self.portfolio.cash -= (exec_amt + total_cost)
        if code in self.portfolio.positions:
            pos = self.portfolio.positions[code]
            total_qty = pos.quantity + qty
            pos.avg_price = (pos.quantity * pos.avg_price + exec_amt) / total_qty
            pos.quantity = total_qty
            pos.market_value += exec_amt
            pos.lots.append(Lot(quantity=qty, price=float(price), entry_date=date, available_from=date))
        else:
            self.portfolio.positions[code] = Position(
                code,
                stock_name,
                qty,
                price,
                exec_amt,
                entry_date=date,
                lots=[Lot(quantity=qty, price=float(price), entry_date=date, available_from=date)],
            )
        self.turnover_amount += exec_amt
        self.execution_stats["buy_fills"] += 1
        self._record_cost_breakdown(cost_breakdown)
        self.trades.append({
            "date": date,
            "stock_code": code,
            "stock_name": stock_name,
            "side": "buy",
            "price": float(price),
            "qty": int(qty),
            "requested_qty": int(requested_qty or qty),
            "fill_status": fill_status,
            "notional": float(exec_amt),
            "cost": float(total_cost),
            "commission": cost_breakdown["commission"],
            "stamp_tax": cost_breakdown["stamp_tax"],
            "transfer_fee": cost_breakdown.get("transfer_fee", 0.0),
            "slippage": cost_breakdown["slippage"],
        })
        previous = self._open_round_trips.get(code)
        if previous:
            previous["qty"] += int(qty)
            previous["entry_notional"] += float(exec_amt)
            previous["entry_cost"] += float(total_cost)
            previous["entry_price"] = previous["entry_notional"] / previous["qty"]
        else:
            self._open_round_trips[code] = {
                "entry_date": date, "entry_price": float(price), "qty": int(qty),
                "entry_notional": float(exec_amt), "entry_cost": float(total_cost), "dividend_amount": 0.0,
            }
        return True

    def _close_position(
        self,
        date: str,
        code: str,
        price: float,
        side: str,
        stock_name: Optional[str] = None,
        qty: Optional[int] = None,
        requested_qty: Optional[int] = None,
        fill_status: str = "filled",
        at_close: bool = False,
    ) -> bool:
        pos = self.portfolio.positions.get(code)
        if pos is None:
            return False

        close_qty = min(int(qty or pos.quantity), pos.quantity)
        if close_qty <= 0:
            return False

        amount = close_qty * price
        cost_breakdown = self.cost_model.calculate_cost_breakdown(
            amount, True, trade_date=date, stock_code=code, at_close=at_close
        )
        total_cost = cost_breakdown["total"]
        self.portfolio.cash += (amount - total_cost)
        remaining_qty = pos.quantity - close_qty
        if remaining_qty > 0:
            pos.quantity = remaining_qty
            pos.market_value = remaining_qty * price
            remaining_to_deduct = close_qty
            for lot in pos.lots:
                if remaining_to_deduct <= 0:
                    break
                deduct = min(lot.quantity, remaining_to_deduct)
                lot.quantity -= deduct
                remaining_to_deduct -= deduct
            pos.lots = [lot for lot in pos.lots if lot.quantity > 0]
        else:
            del self.portfolio.positions[code]
        self.turnover_amount += amount
        self.execution_stats["sell_fills"] += 1
        self._record_cost_breakdown(cost_breakdown)
        self.trades.append({
            'date': date,
            'stock_code': code,
            'stock_name': stock_name or pos.stock_name,
            'side': side,
            'price': float(price),
            'qty': int(close_qty),
            'requested_qty': int(requested_qty or close_qty),
            'fill_status': fill_status,
            'notional': float(amount),
            'cost': float(total_cost),
            'commission': cost_breakdown["commission"],
            'stamp_tax': cost_breakdown["stamp_tax"],
            'transfer_fee': cost_breakdown.get("transfer_fee", 0.0),
            'slippage': cost_breakdown["slippage"],
        })
        entry_info = self._open_round_trips.get(code)
        if entry_info is not None:
            entry_date = datetime.strptime(entry_info["entry_date"], "%Y-%m-%d")
            exit_date = datetime.strptime(date, "%Y-%m-%d")
            entry_qty = int(entry_info.get("qty") or close_qty)
            close_fraction = min(1.0, close_qty / entry_qty) if entry_qty > 0 else 1.0
            closed_entry_notional = float(entry_info["entry_notional"]) * close_fraction
            closed_entry_cost = float(entry_info["entry_cost"]) * close_fraction
            dividend = float(entry_info.get("dividend_amount", 0.0)) * close_fraction
            gross_pnl = amount + dividend - closed_entry_notional
            net_pnl = amount + dividend - total_cost - closed_entry_notional - closed_entry_cost
            gross_return = gross_pnl / closed_entry_notional if closed_entry_notional > 0 else 0.0
            net_denominator = closed_entry_notional + closed_entry_cost
            net_return = net_pnl / net_denominator if net_denominator > 0 else 0.0
            self.round_trips.append({
                "stock_code": code,
                "stock_name": stock_name or pos.stock_name,
                "entry_date": entry_info["entry_date"],
                "exit_date": date,
                "holding_days": (exit_date - entry_date).days,
                "entry_price": entry_info["entry_price"],
                "exit_price": float(price),
                "qty": int(close_qty),
                "entry_notional": float(closed_entry_notional),
                "exit_notional": float(amount),
                "entry_cost": float(closed_entry_cost),
                "dividend_amount": dividend,
                "exit_cost": float(total_cost),
                "total_cost": float(closed_entry_cost + total_cost),
                "gross_return": float(gross_return),
                "net_return": float(net_return),
                "gross_pnl": float(gross_pnl),
                "net_pnl": float(net_pnl),
                "exit_side": side,
            })
            remaining_entry_qty = entry_qty - close_qty
            if remaining_entry_qty > 0 and remaining_qty > 0:
                entry_info["qty"] = int(remaining_entry_qty)
                entry_info["entry_notional"] = float(entry_info["entry_notional"] - closed_entry_notional)
                entry_info["entry_cost"] = float(entry_info["entry_cost"] - closed_entry_cost)
                entry_info["dividend_amount"] = float(entry_info.get("dividend_amount", 0.0) - dividend)
            else:
                self._open_round_trips.pop(code, None)
        return True

    def _intraday_limit_down_blocked(self, stock_row: pd.Series, fill_price: float) -> bool:
        """止损触价成交价若已达跌停价位则视为无法卖出（顺延到后续交易日）。"""
        if self._in_no_limit_window(stock_row):
            return False
        prev_close = self._get_prev_close(stock_row)
        if prev_close is None:
            return False
        threshold = self._limit_move_threshold(stock_row)
        return (fill_price - prev_close) / prev_close <= -threshold

    def _check_price_risk_exits(self, date: str, day_data: pd.DataFrame, phase: str) -> Set[str]:
        """个股风险退出：统一处理止损/止盈，并返回当日禁止回补的代码。

        成交价假设（日频近似止损单语义）：
        - 开盘已破位：按开盘价成交（跳空劣于触发价）；
        - 盘中触价（low <= 止损价）：按 min(open, 止损价) 成交；
          若成交价已达跌停价位则本日无法卖出，顺延；
        - 止盈对称：开盘已达标按开盘价，盘中 high >= 止盈价按 max(open, 止盈价)。

        执行时点假设（phase，防前视）：
        - RISK_EXIT_PHASE_OPEN：只处理"用当日开盘价即可判定"的跳空触发，在按开盘价
          调仓之前执行，其现金当日开盘可用；
        - RISK_EXIT_PHASE_INTRADAY：只处理"需要当日 low/high 才知道"的盘中触价，在
          调仓之后执行，其现金当日不再可用于开盘买单。
        同一次触发只会落在其中一个阶段，不会被重复评估或重复计入诊断计数。
        """
        if phase not in (self.RISK_EXIT_PHASE_OPEN, self.RISK_EXIT_PHASE_INTRADAY):
            raise ValueError(f"Unsupported risk exit phase: {phase}")

        blocked_reentry_codes: Set[str] = set()
        for code, pos in list(self.portfolio.positions.items()):
            stock_row = self._row_for_code(day_data, code)
            if stock_row is None:
                continue

            open_price = self._safe_float(stock_row.get('open'))
            if open_price is None or open_price <= 0 or pos.avg_price <= 0:
                continue

            # 1. 延迟止损意图（DEFERRED_INTENT）：前一日买入触发止损因 T+1 顺延到本日开盘执行
            if phase == self.RISK_EXIT_PHASE_OPEN and pos.deferred_intent is not None:
                if not self._is_t1_sell_blocked(pos, date):
                    intent_side = pos.deferred_intent
                    pos.deferred_intent = None
                    self.execution_stats["sell_attempts"] += 1
                    self.execution_stats["delayed_exit_count"] += 1
                    block_reason = self._trade_block_reason(stock_row, "open", "sell")
                    if block_reason is not None:
                        self._record_trade_block(block_reason, "sell")
                        continue
                    requested_qty = pos.available_quantity(date, enforce_t1=self.enforce_t1 and code not in getattr(self, "_t0_codes", set()))
                    qty, partial = self._cap_order_quantity(stock_row, requested_qty)
                    if qty > 0:
                        fill_status = "partial" if partial else "filled"
                        if self._close_position(
                            date, code, float(open_price), intent_side, pos.stock_name,
                            qty=qty, requested_qty=requested_qty, fill_status=fill_status
                        ):
                            blocked_reentry_codes.add(code)
                            continue

            low_price = self._safe_float(stock_row.get('low'))
            high_price = self._safe_float(stock_row.get('high'))
            stop_price = pos.avg_price * (1.0 + self.stock_stop_loss)
            take_price = (
                pos.avg_price * (1.0 + self.take_profit)
                if self.take_profit is not None
                else None
            )

            exit_side = None
            exec_price = None
            intraday_touch = False
            if open_price <= stop_price:
                exit_side, exec_price = 'stop_loss', open_price
            elif take_price is not None and open_price >= take_price:
                exit_side, exec_price = 'take_profit', open_price
            elif low_price is not None and low_price <= stop_price:
                exit_side, exec_price = 'stop_loss', min(open_price, stop_price)
                intraday_touch = True
            elif take_price is not None and high_price is not None and high_price >= take_price:
                exit_side, exec_price = 'take_profit', max(open_price, take_price)
                intraday_touch = True

            if exit_side is None:
                continue

            # 触发类型与执行时点必须匹配：开盘价触发只在开盘阶段成交，日内触价只在
            # 调仓之后成交。保证一次触发在一天内只被评估一次（诊断计数不重复）。
            if intraday_touch != (phase == self.RISK_EXIT_PHASE_INTRADAY):
                continue

            self.execution_stats["sell_attempts"] += 1
            if self._is_t1_sell_blocked(pos, date):
                self.execution_stats["t1_sell_block_count"] += 1
                pos.deferred_intent = exit_side
                continue

            block_reason = self._trade_block_reason(stock_row, "open", "sell")
            if block_reason is not None:
                self._record_trade_block(block_reason, "sell")
                continue

            if intraday_touch and exit_side == 'stop_loss' and self._intraday_limit_down_blocked(stock_row, exec_price):
                self._record_trade_block("limit_down", "sell")
                continue

            requested_qty = pos.available_quantity(date, enforce_t1=self.enforce_t1 and code not in getattr(self, "_t0_codes", set()))
            qty, partial = self._cap_order_quantity(stock_row, requested_qty)
            if qty <= 0:
                continue
            fill_status = "partial" if partial else "filled"
            if self._close_position(date, code, float(exec_price), exit_side, pos.stock_name, qty=qty, requested_qty=requested_qty, fill_status=fill_status):
                blocked_reentry_codes.add(code)

        return blocked_reentry_codes

    def _liquidate_positions(self, date: str, day_data: pd.DataFrame, side: str, price_field: str = "open"):
        for code in list(self.portfolio.positions.keys()):
            pos = self.portfolio.positions.get(code)
            if pos is None:
                continue
            stock_row = self._row_for_code(day_data, code)
            if stock_row is None:
                continue
            self.execution_stats["sell_attempts"] += 1
            if self._is_t1_sell_blocked(pos, date):
                self.execution_stats["t1_sell_block_count"] += 1
                if self.execution_mode == "signal_close_to_next_open":
                    self.execution_stats["delayed_exit_count"] += 1
                continue

            block_reason = self._trade_block_reason(stock_row, price_field, "sell")
            if block_reason is not None:
                self._record_trade_block(block_reason, "sell")
                if self.execution_mode == "signal_close_to_next_open":
                    self.execution_stats["delayed_exit_count"] += 1
                continue

            requested_qty = pos.available_quantity(date, enforce_t1=self.enforce_t1 and code not in getattr(self, "_t0_codes", set()))
            qty, partial = self._cap_order_quantity(stock_row, requested_qty)
            if qty <= 0:
                if self.execution_mode == "signal_close_to_next_open":
                    self.execution_stats["delayed_exit_count"] += 1
                continue
            fill_status = "partial" if partial else "filled"
            self._close_position(date, code, float(stock_row[price_field]), side, pos.stock_name, qty=qty, requested_qty=requested_qty, fill_status=fill_status)

    def _rebalance(self, date, day_data, signals, blocked_reentry_codes: Optional[Set[str]] = None):
        blocked_reentry_codes = blocked_reentry_codes or set()

        # Sell First
        to_sell = []
        for code, pos in self.portfolio.positions.items():
            if code not in signals:
                to_sell.append(code)
                
        for code in to_sell:
            pos = self.portfolio.positions[code]
            stock_row = self._row_for_code(day_data, code)
            if stock_row is None: continue
            
            self.execution_stats["sell_attempts"] += 1
            if self._is_t1_sell_blocked(pos, date):
                self.execution_stats["t1_sell_block_count"] += 1
                continue

            block_reason = self._trade_block_reason(stock_row, "open", "sell")
            if block_reason is not None:
                self._record_trade_block(block_reason, "sell")
                continue

            name = stock_row['stock_name']
            requested_qty = pos.available_quantity(date, enforce_t1=self.enforce_t1 and code not in getattr(self, "_t0_codes", set()))
            qty, partial = self._cap_order_quantity(stock_row, requested_qty)
            if qty <= 0:
                continue
            fill_status = "partial" if partial else "filled"
            self._close_position(date, code, float(stock_row['open']), 'sell', name, qty=qty, requested_qty=requested_qty, fill_status=fill_status)

        # Buy Second
        total_val = self.portfolio.total_value
        for code, weight in signals.items():
            if code in self.portfolio.positions or code in blocked_reentry_codes:
                if code in blocked_reentry_codes:
                    self.execution_stats["blocked_reentry_after_stop_count"] += 1
                continue
            
            stock_row = self._row_for_code(day_data, code)
            if stock_row is None:
                continue
            
            self.execution_stats["buy_attempts"] += 1
            block_reason = self._trade_block_reason(stock_row, "open", "buy")
            if block_reason is not None:
                self._record_trade_block(block_reason, "buy")
                continue
            
            name = stock_row['stock_name']
            price = float(stock_row['open'])
            buy_amt = min(total_val * weight, self.portfolio.cash * 0.98)
            
            qty = int(buy_amt / price / 100) * 100
            capped_qty, partial = self._cap_order_quantity(stock_row, qty)
            fill_status = "partial" if partial else "filled"
            self._open_position(date, code, name, price, capped_qty, requested_qty=qty, fill_status=fill_status)

    def _rebalance_close(self, date, day_data, signals, skip_exit_codes: Optional[Set[str]] = None):
        signals = signals or {}
        skip_exit_codes = skip_exit_codes or set()

        to_sell = []
        for code in self.portfolio.positions.keys():
            if code in skip_exit_codes:
                continue
            if code not in signals:
                to_sell.append(code)

        for code in to_sell:
            pos = self.portfolio.positions[code]
            stock_row = self._row_for_code(day_data, code)
            if stock_row is None:
                continue

            self.execution_stats["sell_attempts"] += 1
            if self._is_t1_sell_blocked(pos, date):
                self.execution_stats["t1_sell_block_count"] += 1
                self.execution_stats["delayed_exit_count"] += 1
                continue

            block_reason = self._trade_block_reason(stock_row, "close", "sell")
            if block_reason is not None:
                self._record_trade_block(block_reason, "sell")
                self.execution_stats["delayed_exit_count"] += 1
                continue

            requested_qty = pos.available_quantity(date, enforce_t1=self.enforce_t1 and code not in getattr(self, "_t0_codes", set()))
            qty, partial = self._cap_order_quantity(stock_row, requested_qty)
            if qty <= 0:
                self.execution_stats["delayed_exit_count"] += 1
                continue
            fill_status = "partial" if partial else "filled"
            # 收盘成交使用尾盘滑点参数（close_slippage_rate）。
            self._close_position(date, code, float(stock_row['close']), 'sell', pos.stock_name, qty=qty, requested_qty=requested_qty, fill_status=fill_status, at_close=True)

        total_val = self.portfolio.total_value
        for code, weight in signals.items():
            if code in self.portfolio.positions:
                continue

            stock_row = self._row_for_code(day_data, code)
            if stock_row is None:
                continue

            self.execution_stats["buy_attempts"] += 1
            block_reason = self._trade_block_reason(stock_row, "close", "buy")
            if block_reason is not None:
                self._record_trade_block(block_reason, "buy")
                continue

            name = stock_row['stock_name']
            price = float(stock_row['close'])
            buy_amt = min(total_val * weight, self.portfolio.cash * 0.98)

            qty = int(buy_amt / price / 100) * 100
            capped_qty, partial = self._cap_order_quantity(stock_row, qty)
            fill_status = "partial" if partial else "filled"
            # 收盘成交使用尾盘滑点参数（close_slippage_rate）。
            self._open_position(date, code, name, price, capped_qty, requested_qty=qty, fill_status=fill_status, at_close=True)

    def _generate_report(self):
        history = pd.DataFrame(self.portfolio.history)
        if history.empty: return {}
        
        history['returns'] = history['total_value'].pct_change().fillna(0)
        rolling_max = history['total_value'].cummax()
        history['drawdown'] = (history['total_value'] - rolling_max) / (rolling_max + 1e-9)
        total_return = (self.portfolio.total_value / self.initial_capital) - 1
        
        # New Metrics
        days = len(history)
        annual_return = ((1 + total_return) ** (self.annualization_factor / days)) - 1 if days > 0 else 0
        max_dd = self._calc_max_drawdown(history['total_value'])
        calmar = annual_return / abs(max_dd) if max_dd != 0 else 0

        closed_trade_breakdown = {side: 0 for side in self.CLOSED_TRADE_SIDES}
        for t in self.trades:
            if t['side'] in self.CLOSED_TRADE_SIDES:
                closed_trade_breakdown[t['side']] += 1

        total_trades = sum(closed_trade_breakdown.values())
        round_trips = pd.DataFrame(self.round_trips)
        if round_trips.empty:
            net_returns = pd.Series(dtype=float)
            gross_returns = pd.Series(dtype=float)
            holding_days = pd.Series(dtype=float)
        else:
            net_returns = round_trips["net_return"]
            gross_returns = round_trips["gross_return"]
            holding_days = round_trips["holding_days"]

        winning_trades = int((net_returns > 0).sum())
        losing_trades = int((net_returns <= 0).sum())
        win_rate = float(winning_trades / len(net_returns)) if len(net_returns) > 0 else 0.0
        avg_profit = float(net_returns[net_returns > 0].mean()) if winning_trades > 0 else 0.0
        avg_loss = float(abs(net_returns[net_returns <= 0].mean())) if losing_trades > 0 else 0.0
        profit_loss_ratio = float(avg_profit / avg_loss) if avg_loss > 0 else 0.0
        expectancy_net = float(net_returns.mean()) if len(net_returns) > 0 else 0.0
        profit_factor_net = (
            float(net_returns[net_returns > 0].sum() / abs(net_returns[net_returns <= 0].sum()))
            if losing_trades > 0 and abs(net_returns[net_returns <= 0].sum()) > 0
            else 0.0
        )
        avg_holding_days_actual = float(holding_days.mean()) if len(holding_days) > 0 else 0.0
        invested_days = int((history["num_positions"] > 0).sum())
        invested_ratio = float(invested_days / days) if days > 0 else 0.0
        avg_positions = float(history["num_positions"].mean()) if days > 0 else 0.0
        avg_cash_ratio = float((history["cash"] / history["total_value"].replace(0, np.nan)).fillna(0).mean()) if days > 0 else 0.0
        buy_fill_rate = (
            float(self.execution_stats["buy_fills"] / self.execution_stats["buy_attempts"])
            if self.execution_stats["buy_attempts"] > 0
            else 0.0
        )
        sell_fill_rate = (
            float(self.execution_stats["sell_fills"] / self.execution_stats["sell_attempts"])
            if self.execution_stats["sell_attempts"] > 0
            else 0.0
        )
        cost_bps_turnover = float(self.cost_stats["total_cost"] / self.turnover_amount * 10000) if self.turnover_amount > 0 else 0.0
        avg_cost_per_round_trip = float(self.cost_stats["total_cost"] / len(round_trips)) if len(round_trips) > 0 else 0.0
        
        # Baseline comparison
        benchmark_history = []
        benchmark_return = 0.0
        if getattr(self, 'benchmark_data', None) is not None and not getattr(self, 'benchmark_data').empty:
            bd = self.benchmark_data.sort_values('date')
            bd = bd[bd['date'].isin(history['date'])]
            if not bd.empty:
                initial_price = bd.iloc[0]['close']
                for _, row in bd.iterrows():
                    benchmark_history.append({
                        'date': row['date'],
                        'value': float(row['close'] / initial_price)
                    })
                benchmark_return = float(benchmark_history[-1]["value"] - 1) if benchmark_history else 0.0
        excess_return = float(total_return - benchmark_return)

        # 逐日执行时序（显式声明，供使用者判断结果是否含前视）。
        if self.execution_mode == "signal_close_to_next_open":
            daily_sequence = [
                "1_exit_overnight_positions_at_today_open",
                "2_generate_signals_from_today_close",
                "3_enter_new_positions_at_today_close",
                "4_mark_to_close_and_record_state",
            ]
        else:
            daily_sequence = [
                "1_mark_positions_to_today_open",
                "2_gap_open_risk_exits_at_today_open",
                "3_rebalance_yesterday_signals_at_today_open",
                "4_intraday_touch_risk_exits_after_open_rebalance",
                "5_mark_to_close_and_record_state",
                "6_generate_signals_from_today_close_for_next_open",
            ]

        return {
            'total_return': float(total_return),
            'history': history.drop(columns=['positions']).to_dict(orient='records'),
            'benchmark_history': benchmark_history,
            'trades': self.trades,
            'round_trips': self.round_trips,
            'final_positions': [
                {
                    'stock_code': p.stock_code,
                    'stock_name': p.stock_name,
                    'quantity': p.quantity,
                    'avg_price': p.avg_price,
                    'market_value': p.market_value,
                    'weight': float(p.market_value / self.portfolio.total_value) if self.portfolio.total_value > 0 else 0
                }
                for p in self.portfolio.positions.values()
            ],
            'summary': {
                'initial_capital': self.initial_capital,
                'final_value': self.portfolio.total_value,
                'annual_return': float(annual_return),
                'benchmark_return': benchmark_return,
                'excess_return': excess_return,
                'max_drawdown': float(max_dd),
                'sharpe_ratio': self._calc_sharpe(history['returns']),
                'calmar_ratio': float(calmar),
                'win_rate': float(win_rate),
                'profit_loss_ratio': float(profit_loss_ratio),
                'total_trades': total_trades,
                'closed_trade_breakdown': closed_trade_breakdown,
                'trade_stats': {
                    'round_trip_count': int(len(round_trips)),
                    'avg_trade_return_gross': float(gross_returns.mean()) if len(gross_returns) > 0 else 0.0,
                    'avg_trade_return_net': expectancy_net,
                    'median_trade_return_net': float(net_returns.median()) if len(net_returns) > 0 else 0.0,
                    'expectancy_net': expectancy_net,
                    'avg_win_net': float(avg_profit),
                    'avg_loss_net': float(-avg_loss) if avg_loss > 0 else 0.0,
                    'profit_factor_net': profit_factor_net,
                    'avg_holding_days_actual': avg_holding_days_actual,
                },
                'cost_stats': {
                    **{key: float(value) for key, value in self.cost_stats.items()},
                    'turnover_amount': float(self.turnover_amount),
                    'turnover_ratio': float(self.turnover_amount / self.initial_capital) if self.initial_capital > 0 else 0.0,
                    'cost_pct_initial': float(self.cost_stats['total_cost'] / self.initial_capital) if self.initial_capital > 0 else 0.0,
                    'cost_bps_turnover': cost_bps_turnover,
                    'avg_cost_per_round_trip': avg_cost_per_round_trip,
                },
                'execution_stats': {
                    **self.execution_stats,
                    'buy_fill_rate': buy_fill_rate,
                    'sell_fill_rate': sell_fill_rate,
                },
                'execution_model': {
                    'name': 'a_share_tradability_capacity_t1_v1',
                    'execution_mode': str(self.execution_mode),
                    'enforce_tradability': bool(self.enforce_tradability),
                    'enforce_t1': bool(self.enforce_t1),
                    'max_volume_participation': self.max_volume_participation,
                    # "触板即拒单"近似阈值（主板）；真实规则中仅封板不可成交。
                    'limit_move_threshold': float(self.limit_move_threshold),
                    # 止损/止盈成交价假设（日内触价近似）。
                    'risk_exit_fill_assumption': (
                        'stop=min(open,stop_price) on low touch, deferred at limit-down; '
                        'take=max(open,take_price) on high touch; gap fills at open'
                    ),
                    # 止损/止盈的执行时序假设（防前视）。
                    'risk_exit_timing_assumption': (
                        'gap-open exits (open<=stop / open>=take) settle at the open, before the '
                        'open-price rebalance; intraday touch exits (low<=stop / high>=take) settle '
                        'AFTER the open-price rebalance, so information only knowable intraday never '
                        'finances same-day open orders'
                    ),
                    # 盘中止损释放的现金能否用于同日开盘买单：否（最早次日开盘可用）。
                    'intraday_risk_exit_cash_available_same_day': False,
                    'daily_sequence': daily_sequence,
                    # 印花税豁免品种（A股仅股票卖出计征）。
                    'stamp_tax_exempt_instruments': (
                        'funds/ETF/LOF (5xxxxx, 15xxxx, 16xxxx) and bonds incl. convertibles '
                        '(1xxxxx) are exempt from A-share stamp tax'
                    ),
                    'close_fill_slippage_rate': float(self.cost_model.close_slippage_rate)
                        if hasattr(self.cost_model, 'close_slippage_rate') else None,
                    'risk_free_rate': float(self.risk_free_rate),
                    'annualization_factor': int(self.annualization_factor),
                },
                # 曾在持仓期间出现无行情行（停牌或数据缺行，按最后价估值）的标的数。
                'suspended_positions_count': int(len(self._suspended_position_codes)),
                'exposure_stats': {
                    'invested_days': invested_days,
                    'invested_ratio': invested_ratio,
                    'avg_positions': avg_positions,
                    'avg_cash_ratio': avg_cash_ratio,
                },
            }
        }

    def _calc_max_drawdown(self, values):
        rolling_max = values.cummax()
        drawdown = (values - rolling_max) / (rolling_max + 1e-9)
        return float(drawdown.min())

    def _calc_sharpe(self, returns):
        if returns.std() == 0: return 0.0
        ann = self.annualization_factor
        return float((returns.mean() - self.risk_free_rate / ann) / (returns.std() + 1e-9) * np.sqrt(ann))
