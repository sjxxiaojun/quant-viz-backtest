import pandas as pd
from engine import BacktestEngine
from data_manager import DataManager
from strategies.atm_filter import calculate_atm_signals
from strategies.extra_strategies import (
    calculate_reversal_vol_signals, 
    calculate_turtle_signals, 
    calculate_hfmr_signals,
    calculate_sector_alpha_signals,
    calculate_ai_ml_signals,
    calculate_ai_adaptive_signals
)
from datetime import datetime, timedelta
import baostock as bs

def verify():
    dm = DataManager()
    stocks = ["600519", "000001", "300750"] # Moutai, PingAn Bank, CATL
    start_date = "2024-01-01"
    end_date = "2024-03-01"
    
    # Warmup fetch
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    warmup_start = (start_dt - timedelta(days=120)).strftime("%Y-%m-%d")
    
    print(f"--- Fetching data ({warmup_start} to {end_date}) ---")
    df = dm.get_stock_pool_data(stocks, warmup_start, end_date)
    
    if df.empty:
        print("Error: No data fetched!")
        return

    print(f"Data columns: {df.columns.tolist()}")
    
    strategies = {
        "ATM": calculate_atm_signals,
        "Reversal": calculate_reversal_vol_signals,
        "Turtle": calculate_turtle_signals,
        "HFMR": calculate_hfmr_signals,
        "Sector_Alpha": calculate_sector_alpha_signals,
        "AI_ML": calculate_ai_ml_signals,
        "AI_Adaptive": calculate_ai_adaptive_signals
    }
    
    for name, func in strategies.items():
        print(f"\n--- Testing Strategy: {name} ---")
        try:
            # 1. Calculate signals
            strat_df = func(df.copy())
            
            # 2. Setup signal func for engine
            current_target_stocks = set()
            def signal_func(date, day_data):
                nonlocal current_target_stocks
                to_remove = set()
                for code in current_target_stocks:
                    stock_day = day_data[day_data['stock_code'] == code]
                    if not stock_day.empty and stock_day.iloc[0]['signal'] == -1:
                        to_remove.add(code)
                current_target_stocks -= to_remove
                buys = day_data[day_data['signal'] == 1]['stock_code'].tolist()
                for code in buys:
                    current_target_stocks.add(code)
                if not current_target_stocks: return {}
                active = list(current_target_stocks)[:10]
                return {code: 1.0/len(active) for code in active}

            # 3. Run engine
            engine = BacktestEngine(initial_capital=1000000)
            result = engine.run_backtest(strat_df, signal_func, start_date, end_date)
            
            print(f"Total Return: {result.get('total_return', 0)*100:.2f}%")
            print(f"Trades: {len(result.get('trades', []))}")
            if result.get('trades'):
                print(f"First Trade: {result['trades'][0]}")
            
        except Exception as e:
            print(f"FAILED: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    verify()
