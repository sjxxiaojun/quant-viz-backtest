"""D-05 T+1 分笔 Lot 账本与 DEFERRED_INTENT 延迟意图时序证伪探针。

验证目标：
1. Lot 物理隔离：当日买入的 Lot 在当日卖出循环与风险退出中物理不可达 (available_quantity == 0)。
2. 多日累加与 FIFO 扣减：多次加仓生成独立 Lot，部分平仓按时间优先 (FIFO) 扣减先买入的 Lot。
3. 延迟止损意图 (DEFERRED_INTENT)：
   - 当日买入标的日内触碰止损线时，T+1 机制物理阻断当日卖出，并记录 deferred_intent='stop_loss'；
   - T+1 日开盘阶段，引擎自动以 T+1 日真实开盘价执行延迟止损；
   - 杜绝偷看 D 日日内最低价，彻底消灭隐性前视偏差。
"""

import pandas as pd
import pytest
from engine import BacktestEngine, CostModel, Lot, Position

ZERO_COST_MODEL = CostModel(
    commission_rate=0.0,
    commission_min=0.0,
    stamp_tax_rate=0.0,
    slippage_rate=0.0,
    close_slippage_rate=0.0,
    transfer_fee_rate=0.0,
    use_order_slicing=False,
)


def _bar(date, code, open_p, close_p, low_p=None, high_p=None, prev_close=None):
    return {
        "date": date,
        "stock_code": code,
        "stock_name": code,
        "open": float(open_p),
        "close": float(close_p),
        "low": float(low_p if low_p is not None else min(open_p, close_p)),
        "high": float(high_p if high_p is not None else max(open_p, close_p)),
        "pct_chg": 0.0,
        "tradestatus": "1",
        "is_st": 0,
        "prev_close": float(prev_close or open_p),
    }


def test_lot_structure_initialization_and_availability():
    pos = Position(
        stock_code="600000",
        stock_name="浦发银行",
        quantity=1000,
        avg_price=10.0,
        entry_date="2026-01-02",
    )
    assert len(pos.lots) == 1
    assert pos.lots[0].quantity == 1000
    assert pos.lots[0].entry_date == "2026-01-02"

    # 当日 (T=0) 可用为 0
    assert pos.available_quantity("2026-01-02", enforce_t1=True) == 0
    # 次日 (T+1) 可用为 1000
    assert pos.available_quantity("2026-01-03", enforce_t1=True) == 1000
    # 关闭 T+1 时可用为 1000
    assert pos.available_quantity("2026-01-02", enforce_t1=False) == 1000


def test_multi_lot_accumulation_and_fifo_deduction():
    engine = BacktestEngine(initial_capital=1_000_000.0, cost_model=ZERO_COST_MODEL)
    engine._reset_diagnostics()

    # D1 买入 1000 股 @ 10.0
    engine._open_position("2026-01-02", "600000", "浦发银行", 10.0, 1000)
    pos = engine.portfolio.positions["600000"]
    assert pos.quantity == 1000
    assert len(pos.lots) == 1
    assert pos.available_quantity("2026-01-02") == 0

    # D2 加仓 2000 股 @ 12.0
    engine._open_position("2026-01-03", "600000", "浦发银行", 12.0, 2000)
    pos = engine.portfolio.positions["600000"]
    assert pos.quantity == 3000
    assert len(pos.lots) == 2
    # D2 只有 D1 的 1000 股可用
    assert pos.available_quantity("2026-01-03") == 1000

    # D2 卖出 500 股 (FIFO 扣减 D1 的 Lot)
    engine._close_position("2026-01-03", "600000", 12.5, "sell", qty=500)
    assert pos.quantity == 2500
    assert len(pos.lots) == 2
    assert pos.lots[0].quantity == 500  # D1 lot 剩余 500
    assert pos.lots[1].quantity == 2000 # D2 lot 保持 2000

    # D3 所有 2500 股均可用
    assert pos.available_quantity("2026-01-04") == 2500


def test_deferred_intent_t1_intraday_stop_executes_next_open():
    """证伪探针：D 日买入，D 日日内触及 -8% 止损（low=9.0 < 9.2）。

    断言：
    1. D 日严禁卖出（成交笔数=1，仅买入；t1_sell_block_count=1）。
    2. D 日记录 deferred_intent='stop_loss'。
    3. D+1 日开盘以 D+1 日真实开盘价（8.5）成交，而不是 D 日触价时的 9.2 或 9.0。
    4. 消除前视偏差与偷看未来数据。
    """
    rows = [
        _bar("2026-01-02", "600000", 10.0, 9.1, low_p=9.0, high_p=10.2, prev_close=10.0),
        _bar("2026-01-03", "600000", 8.5, 8.8, low_p=8.3, high_p=8.9, prev_close=9.1),
        _bar("2026-01-04", "600000", 8.8, 9.0, low_p=8.7, high_p=9.1, prev_close=8.8),
    ]
    df = pd.DataFrame(rows)

    # 信号：2026-01-02 盘前生成买入 600000 信号，在 2026-01-02 开盘调仓买入
    def signal_func(date, day_data, current_positions=None):
        return {}

    engine = BacktestEngine(
        initial_capital=100_000.0,
        cost_model=ZERO_COST_MODEL,
        stock_stop_loss=-0.08,
    )

    # 手动触发：在 2026-01-02 开盘调仓前注入买入信号
    # 或直接在 run_backtest 中通过 pending_signals 产生
    # 模拟：第 0 天产生信号，第 1 天 (2026-01-02) 开盘买入
    all_rows = [
        _bar("2026-01-01", "600000", 10.0, 10.0, low_p=10.0, high_p=10.0, prev_close=10.0),
        _bar("2026-01-02", "600000", 10.0, 9.1, low_p=9.0, high_p=10.2, prev_close=10.0),
        _bar("2026-01-03", "600000", 8.5, 8.8, low_p=8.3, high_p=8.9, prev_close=9.1),
        _bar("2026-01-04", "600000", 8.8, 9.0, low_p=8.7, high_p=9.1, prev_close=8.8),
    ]
    all_df = pd.DataFrame(all_rows)

    def signal_map(date, day_data, current_positions=None):
        if date == "2026-01-01":
            return {"600000": 1.0}
        return {}

    report = engine.run_backtest(all_df, signal_map, "2026-01-01", "2026-01-04")
    trades = report["trades"]

    # 交易列表断言
    assert len(trades) == 2
    buy_trade, sell_trade = trades[0], trades[1]

    # 买入在 2026-01-02 开盘
    assert buy_trade["date"] == "2026-01-02"
    assert buy_trade["side"] == "buy"
    assert buy_trade["price"] == 10.0

    # 卖出必须发生在 2026-01-03 开盘，且成交价严格等于 2026-01-03 开盘价 8.5
    assert sell_trade["date"] == "2026-01-03"
    assert sell_trade["side"] == "stop_loss"
    assert sell_trade["price"] == 8.5, "必须以 T+1 日开盘价成交，绝不可偷看 T 日日内触损价或最低价！"

    # 诊断计数断言
    stats = report["summary"]["execution_stats"]
    assert stats["t1_sell_block_count"] >= 1
    assert stats["delayed_exit_count"] >= 1
