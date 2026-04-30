"""
直接复现 main.py 中的 run_backtest 逻辑，捕获完整错误栈。
这个文件保留为手工调试入口，不参与默认 pytest 收集。
"""
import traceback
import pandas as pd
from datetime import datetime, timedelta
from data_manager import DataManager
from engine import BacktestEngine, CostModel
from strategy_registry import STRATEGY_REGISTRY
from position_manager import PositionManager
import json, os

# 加载 pools
pool_path = os.path.join(os.path.dirname(__file__), 'pools.json')
with open(pool_path, 'r') as f:
    POOLS = json.load(f)

def run_backtest_debug(factor="bottom_fishing", pool_name="etf"):
    dm = DataManager()
    current_pool = POOLS.get(pool_name, POOLS["core"])
    
    start_date = "2022-01-01"
    end_date   = "2025-01-01"
    
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    warmup_start = (start_dt - timedelta(days=150)).strftime("%Y-%m-%d")
    
    print(f"\n[1] 获取数据... pool={pool_name}, 品种数={len(current_pool)}")
    df, data_sources = dm.get_stock_pool_data(current_pool, warmup_start, end_date)
    print(f"    df.shape={df.shape}, columns={list(df.columns)}")
    
    if df.empty:
        print("    ERROR: df 为空，退出")
        return
    
    # 检查列名
    print(f"    df['date'] sample: {sorted(df['date'].unique())[:3]}")
    print(f"    stock_code sample: {df['stock_code'].unique()[:5] if 'stock_code' in df.columns else 'NO stock_code column'}")
    
    print(f"\n[2] 应用策略 {factor}...")
    strategy_func = STRATEGY_REGISTRY[factor]["func"]
    try:
        df = strategy_func(df)
        print(f"    成功, signal分布: {df['signal'].value_counts().to_dict() if 'signal' in df.columns else 'NO signal column'}")
    except Exception as e:
        print(f"    策略计算失败: {e}")
        traceback.print_exc()
        return
    
    print(f"\n[3] 获取基准数据...")
    benchmark_df, _ = dm.get_stock_data("510300", start_date, end_date)
    print(f"    benchmark shape={benchmark_df.shape}")
    
    print(f"\n[4] 初始化 PositionManager + Engine...")
    pos_manager = PositionManager(max_positions=5, weight_mode="equal")
    
    def signal_func(date, day_data):
        day_signals = df[df['date'] == date]
        if day_signals.empty:
            return {}
        return pos_manager.generate_target_weights(date, day_data, day_signals)
    
    cost_model = CostModel(slippage_rate=0.0003)
    engine = BacktestEngine(
        initial_capital=1_000_000,
        cost_model=cost_model,
        stock_stop_loss=-0.08,
    )
    
    print(f"\n[5] 运行回测...")
    try:
        result = engine.run_backtest(df, signal_func, start_date, end_date, benchmark_data=benchmark_df)
        print(f"    成功! total_return={result.get('total_return'):.4f}")
        print(f"    summary={result.get('summary')}")
    except Exception as e:
        print(f"    Engine 失败: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    run_backtest_debug("bottom_fishing", "etf")
