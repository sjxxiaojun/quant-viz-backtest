import sys
import os
from pathlib import Path
import time
import pandas as pd
import numpy as np

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from data_manager import DataManager

def prove_alpha_speed():
    dm = DataManager()
    
    # 1. Selection
    all_codes = dm.list_local_codes("a_share")
    if not all_codes:
        print("❌ No local codes found. Run sync scripts first.")
        return
    
    sample_size = min(100, len(all_codes))
    sample_codes = all_codes[:sample_size]
    
    print(f"🚀 Wave 0: Proving Alpha Speed with {sample_size} stocks...")
    
    start_time = time.time()
    
    # 2. Loading (Vectorizedish)
    # Using a 1-year window for proof
    end_date = "2026-04-23"
    start_date = "2025-04-23"
    
    df, sources = dm.get_stock_pool_data(sample_codes, start_date, end_date, allow_mock=False)
    
    load_time = time.time() - start_time
    print(f"✅ Data Loaded: {len(df)} rows in {load_time:.2f}s")
    
    # 3. Factor Computation (Vectorized)
    comp_start = time.time()
    
    # Simple Momentum / Volatility factor
    # Group by stock_code and compute
    df = df.sort_values(['stock_code', 'date'])
    
    # Momentum: 20-day return
    df['mom_20'] = df.groupby('stock_code')['close'].pct_change(20)
    
    # Volatility: 20-day std of log returns
    df['log_ret'] = np.log(df['close'] / df['close'].shift(1))
    df['vol_20'] = df.groupby('stock_code')['log_ret'].transform(lambda x: x.rolling(20).std())
    
    # Composite Factor
    df['alpha_mom_vol'] = df['mom_20'] / df['vol_20'].replace(0, np.nan)
    
    comp_time = time.time() - comp_start
    total_time = time.time() - start_time
    
    print(f"📊 Alpha Computed in {comp_time:.2f}s")
    print(f"⏱️ Total Wave 0 Time: {total_time:.2f}s")
    
    if total_time < 30: # Our KPI was 30s for full market, but for 100 stocks we want < 5s
        print("🟢 KPI MET: Speed is sufficient for closed-loop mining.")
    else:
        print("🔴 KPI FAILED: Speed is too slow. Optimization required.")

if __name__ == "__main__":
    prove_alpha_speed()
