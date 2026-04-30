import sys
import os
import sqlite3
import random
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import warnings

warnings.filterwarnings("ignore")
# Add the parent directory to sys.path to import local modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import BacktestEngine, CostModel
from data_manager import DataManager
from strategy_registry import STRATEGY_REGISTRY
from position_manager import PositionManager

DB_PATH = Path(__file__).resolve().parents[1] / "virtual_trading.db"

# Exactly 13 core strategies from frontend config
CORE_STRATEGY_KEYS = [
    "blackhorse", "ai_adaptive", "ai_ml", "bottom_fishing", "bottom_fishing_stable",
    "overnight", "weak_to_strong", "limit_up_doji", "sector_alpha", "turtle",
    "hfmr", "reversal", "atm"
]

def init_all_strategies(end_date="2026-04-23"):
    print(f"🐢🐇 「龟兔赛跑」模拟盘初始化开始 (基准日期: {end_date})")
    data_manager = DataManager()
    
    # 1. 获取所有策略需要的基础股票池
    all_symbols = data_manager.list_local_codes("a_share")
    etf_symbols = data_manager.list_local_codes("etf")
    
    # 2. 准备数据库
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 清理旧数据
    cursor.execute("DELETE FROM accounts")
    cursor.execute("DELETE FROM positions")
    cursor.execute("DELETE FROM trade_log")
    cursor.execute("DELETE FROM daily_stats")
    cursor.execute("DELETE FROM strategy_reports")
    cursor.execute("DELETE FROM execution_meta")
    
    # 3. 预加载所有数据 (优化点：只加载一次全市场数据)
    effective_start = "2026-03-23"
    warmup_start = (datetime.strptime(effective_start, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
    
    print(f"正在加载全市场 A 股数据 ({len(all_symbols)} 只标的)...")
    a_share_df, _ = data_manager.get_stock_pool_data(all_symbols, warmup_start, end_date, allow_mock=False)
    
    print(f"正在加载全市场 ETF 数据 ({len(etf_symbols)} 只标的)...")
    etf_df, _ = data_manager.get_stock_pool_data(etf_symbols, warmup_start, end_date, allow_mock=False)
    
    for key in CORE_STRATEGY_KEYS:
        spec = STRATEGY_REGISTRY.get(key)
        if not spec:
            print(f"  [Skip] {key} 不在注册中心")
            continue
            
        print(f"正在播种策略: {spec.name} ({key})...")
        
        # 选择池
        full_df = etf_df if spec.pool == "etf" else a_share_df
        
        if full_df.empty:
            print(f"  [Skip] {key} 数据为空")
            continue
            
        try:
            # 计算信号
            df_with_signals = spec.func(full_df.copy())
            
            # 兼容性修复：确保 stock_code 不在索引中
            if 'stock_code' not in df_with_signals.columns and 'stock_code' in df_with_signals.index.names:
                df_with_signals = df_with_signals.reset_index()
                 
            # 运行回测 (使用标准 10万本金)
            initial_capital = 100000.0
            engine = BacktestEngine(initial_capital=initial_capital)
            pos_manager = PositionManager(max_positions=5, strategy_spec=spec) # 统一最大 5 个持仓
            
            # 优化信号查询
            signal_groups = dict(list(df_with_signals.groupby('date')))
            
            def signal_func(date, day_data):
                day_sigs = signal_groups.get(date, pd.DataFrame())
                return pos_manager.generate_target_weights(date, day_data, day_sigs, current_positions=engine.portfolio.positions)
 
            engine.run_backtest(df_with_signals, signal_func, effective_start, end_date)
            
            # 提取 4.23 收盘状态
            final_portfolio = engine.portfolio
            cash = final_portfolio.cash
            total_value = final_portfolio.total_value
            
            # 写入账户
            cursor.execute("""
                INSERT OR REPLACE INTO accounts (strategy_id, strategy_name, cash, total_value, start_value, last_update)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (key, spec.name, cash, total_value, initial_capital, end_date))
            
            # 写入持仓
            for symbol, pos in final_portfolio.positions.items():
                if pos.shares > 0:
                    cursor.execute("""
                        INSERT INTO positions (
                            strategy_id, symbol, shares, cost_price, current_price, entry_date, entry_price
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (key, symbol, pos.shares, pos.cost_price, pos.current_price, end_date, pos.cost_price))
            
            # [NEW] 写入初始历史统计 (播种点)
            cursor.execute("""
                INSERT OR REPLACE INTO daily_stats (strategy_id, date, total_value, cash)
                VALUES (?, ?, ?, ?)
            """, (key, end_date, total_value, cash))

            print(f"  ✅ {spec.name} 初始化完成: 净值 {total_value:.2f}, 持仓数 {len([p for p in final_portfolio.positions.values() if p.shares > 0])}")
            
        except Exception as e:
            print(f"  ❌ {key} 初始化失败: {e}")
            import traceback
            traceback.print_exc()
            
    conn.commit()
    conn.close()
    print("🏁 所有 13 个策略初始化播种完成！")

if __name__ == "__main__":
    init_all_strategies()
