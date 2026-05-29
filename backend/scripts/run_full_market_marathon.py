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
logger = logging.getLogger("MarathonMining")

def run_full_market_marathon():
    # 1. Initialize
    dm = DataManager()
    factory = AlphaFactory(dm)
    
    # Register candidate factors
    factory.register_factor("mom_120", alpha_momentum_120)
    factory.register_factor("rev_1", alpha_reversal_short)
    factory.register_factor("vol_std_20", alpha_volume_std_20)
    factory.register_factor("pv_corr_10", alpha_price_volume_corr)
    factory.register_factor("range_pos", alpha_range_pos)
    
    # Trend-Following Extensions
    factory.register_factor("trend_macd", alpha_trend_macd_diff)
    factory.register_factor("trend_breakout60", alpha_trend_breakout_60)
    factory.register_factor("trend_vol_adj_mom20", alpha_volatility_adj_mom_20)
    
    # 2. Load Consolidated Data (2022 to 2026)
    logger.info("🚀 Starting Full Market Marathon (2022-2026)...")
    consolidated_dir = Path("/Users/gdxj/quant_data_lake/consolidated")
    
    years = [2022, 2023, 2024, 2025, 2026]
    dfs = []
    
    for year in years:
        file_path = consolidated_dir / f"market_{year}.parquet"
        if file_path.exists():
            logger.info(f"Loading {file_path.name}...")
            dfs.append(pd.read_parquet(file_path))
        else:
            logger.warning(f"File for {year} missing, skipping.")
            
    if not dfs:
        logger.error("No data found to mine.")
        return
        
    full_df = pd.concat(dfs, ignore_index=True)
    full_df = full_df.sort_values(['stock_code', 'date'])
    logger.info(f"✅ Total Data Loaded: {len(full_df)} rows for {len(full_df['stock_code'].unique())} stocks.")
    
    # 3. Compute Alphas (Vectorized)
    start_time = time.time()
    logger.info("Computing all candidate factors...")
    full_df = factory.compute_factors(full_df)
    logger.info(f"Factors computed in {time.time() - start_time:.2f}s")
    
    # 4. Global Evaluation (IC Analysis)
    logger.info("Evaluating global factor performance...")
    report = factory.evaluate_factors(full_df, horizon=5)
    
    print("\n" + "🌟"*25)
    print("      MASTER ALPHA MARATHON REPORT (2022-2026)")
    print("🌟"*25)
    print(report.to_string(index=False))
    print("🌟"*25 + "\n")
    
    # 5. Save Master Results
    results_path = Path("results/master_alpha_marathon.csv")
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(results_path, index=False)
    logger.info(f"Master report saved to {results_path}")
    
    # 6. Recommendation
    best_factor = report.iloc[0]['factor']
    logger.info(f"🏆 Recommendation: The best performing global factor is '{best_factor}' with an IR of {report.iloc[0]['ir']:.4f}")

if __name__ == "__main__":
    run_full_market_marathon()
