import sys
from pathlib import Path
import pandas as pd
import logging
import time

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from data_manager import DataManager
from alpha_factory import (
    AlphaFactory, alpha_momentum_120, alpha_reversal_short, 
    alpha_volume_std_20, alpha_price_volume_corr, alpha_range_pos,
    alpha_trend_macd_diff, alpha_trend_breakout_60, alpha_volatility_adj_mom_20
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TechTrendEvaluation")

def run_tech_evaluation():
    dm = DataManager()
    factory = AlphaFactory(dm)
    
    # Register trend factors
    factory.register_factor("trend_macd", alpha_trend_macd_diff)
    factory.register_factor("trend_breakout60", alpha_trend_breakout_60)
    factory.register_factor("trend_vol_adj_mom20", alpha_volatility_adj_mom_20)
    
    # Register reversal factors as benchmark
    factory.register_factor("rev_1", alpha_reversal_short)
    factory.register_factor("vol_std_20", alpha_volume_std_20)
    
    logger.info("Loading 2024-2026 data for Tech evaluation...")
    consolidated_dir = Path("/Users/gdxj/quant_data_lake/consolidated")
    
    dfs = []
    for year in [2024, 2025, 2026]:
        file_path = consolidated_dir / f"market_{year}.parquet"
        if file_path.exists():
            dfs.append(pd.read_parquet(file_path))
            
    full_df = pd.concat(dfs, ignore_index=True)
    
    # Filter for tech stocks: ChiNext (300xxx) and STAR Market (688xxx)
    tech_df = full_df[full_df['stock_code'].str.startswith(('300', '688'))].copy()
    tech_df = tech_df.sort_values(['stock_code', 'date'])
    logger.info(f"Tech Universe: {len(tech_df)} rows for {len(tech_df['stock_code'].unique())} stocks.")
    
    tech_df = factory.compute_factors(tech_df)
    
    print("\n" + "="*50)
    print("      TECH SECTOR: 5-DAY HORIZON")
    print("="*50)
    report_5d = factory.evaluate_factors(tech_df, horizon=5)
    print(report_5d.to_string(index=False))
    
    print("\n" + "="*50)
    print("      TECH SECTOR: 20-DAY HORIZON")
    print("="*50)
    report_20d = factory.evaluate_factors(tech_df, horizon=20)
    print(report_20d.to_string(index=False))

if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    run_tech_evaluation()
