import pandas as pd
import numpy as np
import inspect
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Set
from dataclasses import dataclass

@dataclass
class CostModel:
    commission_rate: float = 0.0003
    commission_min: float = 5.0
    stamp_tax_rate: float = 0.001
    slippage_rate: float = 0.0003 # Reduced to 0.03% (Institutional Grade)
    use_order_slicing: bool = True 

    def calculate_cost_breakdown(self, amount: float, is_sell: bool) -> Dict[str, float]:
        commission = max(amount * self.commission_rate, self.commission_min)
        stamp_tax = amount * self.stamp_tax_rate if is_sell else 0.0
        # Sliced execution further reduces impact
        effective_slippage = self.slippage_rate * 0.5 if self.use_order_slicing else self.slippage_rate
        slippage = amount * effective_slippage
        total = commission + stamp_tax + slippage
        return {
            "commission": float(commission),
            "stamp_tax": float(stamp_tax),
            "slippage": float(slippage),
            "total": float(total),
        }

    def calculate_total_cost(self, amount: float, is_sell: bool) -> float:
        return self.calculate_cost_breakdown(amount, is_sell)["total"]

@dataclass
class Position:
    stock_code: str
    stock_name: str
    quantity: int
    avg_price: float
    market_value: float = 0.0
    industry: Optional[str] = None
    entry_date: Optional[str] = None

class Portfolio:
    def __init__(self, initial_capital: float = 1000000.0):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.history: List[Dict] = []
        
    @property
    def total_value(self) -> float:
        market_value = sum(pos.market_value for pos in self.positions.values())
        return self.cash + market_value

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
    # Chinese A-shares have ±10% price limit (or ±20% for certain stocks).
    # Using 9.5% as a safety buffer to avoid hitting the hard limit boundary
    # while still allowing valid trades near the limit. Set via constructor for flexibility.
    LIMIT_MOVE_THRESHOLD: float = 0.095

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
        }
        self.cost_stats = {
            "commission_total": 0.0,
            "stamp_tax_total": 0.0,
            "slippage_total": 0.0,
            "total_cost": 0.0,
        }
        self.turnover_amount = 0.0
        self.round_trips: List[Dict] = []
        self._open_round_trips: Dict[str, Dict] = {}

    def _record_cost_breakdown(self, breakdown: Dict[str, float]):
        self.cost_stats["commission_total"] += breakdown["commission"]
        self.cost_stats["stamp_tax_total"] += breakdown["stamp_tax"]
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
        data_by_date = {
            date: group.set_index("stock_code", drop=False)
            for date, group in data.groupby("date", sort=False)
        }
        all_dates = sorted(data_by_date.keys())
        test_dates = [d for d in all_dates if d >= start_date and d <= end_date]
        
        if self.execution_mode == "signal_close_to_next_open":
            return self._run_signal_close_to_next_open(data_by_date, signal_func, test_dates)

        pending_signals: Optional[Dict[str, float]] = None
        
        for date in test_dates:
            day_data = data_by_date.get(date, pd.DataFrame())
            prev_trade_count = len(self.trades)
            blocked_reentry_codes: Set[str] = set()

            # 1. Open-time risk checks and pending execution. Do not use today's
            # close to decide trades that execute at today's open.
            self._mark_positions_to_price(day_data, "open")

            # 2. Individual stop-loss check before rebalance
            blocked_reentry_codes = self._check_price_risk_exits(date, day_data)
            
            # 3. Execute pending signals at today's open.
            if pending_signals is not None:
                self._rebalance(date, day_data, pending_signals, blocked_reentry_codes)
            today_trades = self.trades[prev_trade_count:]

            # 4. Mark to close and record the end-of-day portfolio state.
            self._mark_positions_to_price(day_data, "close")
            self.portfolio.record_state(date, today_trades)

            # 5. Generate NEW signals for tomorrow.
            pending_signals = self._invoke_signal_func(signal_func, date, day_data) or {}
            
        return self._generate_report()

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
        signal_day_data = self._signal_day_data(day_data)
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

        name = str(stock_row.get("stock_name", "") or "").upper()
        return "ST" in name or "退" in name

    def _limit_move_threshold(self, stock_row: pd.Series) -> float:
        if self._is_st_stock(stock_row):
            return 0.045

        code = str(stock_row.get("stock_code", "") or "")
        if code.startswith(("300", "301", "688", "689")):
            return 0.195
        if code.startswith(("43", "83", "87", "88", "92")):
            return 0.295
        return self.LIMIT_MOVE_THRESHOLD

    def _hits_limit(self, stock_row: pd.Series, price_field: str, direction: str) -> bool:
        prev_close = self._get_prev_close(stock_row)
        price = stock_row.get(price_field)
        if prev_close is None or pd.isna(price):
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
        return bool(self.enforce_t1 and pos.entry_date and pos.entry_date == date)

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
    ) -> bool:
        if qty <= 0:
            self.execution_stats["zero_qty_buy_count"] += 1
            return False

        exec_amt = qty * price
        cost_breakdown = self.cost_model.calculate_cost_breakdown(exec_amt, False)
        total_cost = cost_breakdown["total"]
        if self.portfolio.cash < (exec_amt + total_cost):
            self.execution_stats["insufficient_cash_buy_count"] += 1
            return False

        self.portfolio.cash -= (exec_amt + total_cost)
        self.portfolio.positions[code] = Position(code, stock_name, qty, price, exec_amt, entry_date=date)
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
            "slippage": cost_breakdown["slippage"],
        })
        self._open_round_trips[code] = {
            "entry_date": date,
            "entry_price": float(price),
            "qty": int(qty),
            "entry_notional": float(exec_amt),
            "entry_cost": float(total_cost),
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
    ) -> bool:
        pos = self.portfolio.positions.get(code)
        if pos is None:
            return False

        close_qty = min(int(qty or pos.quantity), pos.quantity)
        if close_qty <= 0:
            return False

        amount = close_qty * price
        cost_breakdown = self.cost_model.calculate_cost_breakdown(amount, True)
        total_cost = cost_breakdown["total"]
        self.portfolio.cash += (amount - total_cost)
        remaining_qty = pos.quantity - close_qty
        if remaining_qty > 0:
            pos.quantity = remaining_qty
            pos.market_value = remaining_qty * price
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
            gross_pnl = amount - closed_entry_notional
            net_pnl = amount - total_cost - closed_entry_notional - closed_entry_cost
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
            else:
                self._open_round_trips.pop(code, None)
        return True

    def _check_price_risk_exits(self, date: str, day_data: pd.DataFrame) -> Set[str]:
        """个股风险退出：统一处理止损/止盈，并返回当日禁止回补的代码。"""
        blocked_reentry_codes: Set[str] = set()
        for code, pos in list(self.portfolio.positions.items()):
            stock_row = self._row_for_code(day_data, code)
            if stock_row is None:
                continue

            current_price = stock_row['open']  # 用开盘价执行止损/止盈
            pnl_pct = (current_price - pos.avg_price) / pos.avg_price
            exit_side = None
            if pnl_pct <= self.stock_stop_loss:
                exit_side = 'stop_loss'
            elif self.take_profit is not None and pnl_pct >= self.take_profit:
                exit_side = 'take_profit'

            if exit_side is None:
                continue

            self.execution_stats["sell_attempts"] += 1
            if self._is_t1_sell_blocked(pos, date):
                self.execution_stats["t1_sell_block_count"] += 1
                continue

            block_reason = self._trade_block_reason(stock_row, "open", "sell")
            if block_reason is not None:
                self._record_trade_block(block_reason, "sell")
                continue

            requested_qty = pos.quantity
            qty, partial = self._cap_order_quantity(stock_row, requested_qty)
            if qty <= 0:
                continue
            fill_status = "partial" if partial else "filled"
            if self._close_position(date, code, float(current_price), exit_side, pos.stock_name, qty=qty, requested_qty=requested_qty, fill_status=fill_status):
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

            requested_qty = pos.quantity
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
            requested_qty = pos.quantity
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

            requested_qty = pos.quantity
            qty, partial = self._cap_order_quantity(stock_row, requested_qty)
            if qty <= 0:
                self.execution_stats["delayed_exit_count"] += 1
                continue
            fill_status = "partial" if partial else "filled"
            self._close_position(date, code, float(stock_row['close']), 'sell', pos.stock_name, qty=qty, requested_qty=requested_qty, fill_status=fill_status)

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
            self._open_position(date, code, name, price, capped_qty, requested_qty=qty, fill_status=fill_status)

    def _generate_report(self):
        history = pd.DataFrame(self.portfolio.history)
        if history.empty: return {}
        
        history['returns'] = history['total_value'].pct_change().fillna(0)
        rolling_max = history['total_value'].cummax()
        history['drawdown'] = (history['total_value'] - rolling_max) / (rolling_max + 1e-9)
        total_return = (self.portfolio.total_value / self.initial_capital) - 1
        
        # New Metrics
        days = len(history)
        annual_return = ((1 + total_return) ** (252 / days)) - 1 if days > 0 else 0
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
                    'enforce_tradability': bool(self.enforce_tradability),
                    'enforce_t1': bool(self.enforce_t1),
                    'max_volume_participation': self.max_volume_participation,
                },
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
        # Assuming 2.5% risk-free rate
        return float((returns.mean() - 0.025/252) / (returns.std() + 1e-9) * np.sqrt(252))
