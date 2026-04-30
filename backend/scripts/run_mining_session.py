import sys
from pathlib import Path
import pandas as pd
import logging

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from data_manager import DataManager
from alpha_factory import AlphaFactory, alpha_momentum_120, alpha_reversal_short, alpha_volume_std_20, alpha_price_volume_corr, alpha_range_pos

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MiningSession")

def run_mining_session():
    # 1. Initialize
    dm = DataManager()
    factory = AlphaFactory(dm)
    
    # Register factors to test
    factory.register_factor("mom_120", alpha_momentum_120)
    factory.register_factor("rev_1", alpha_reversal_short)
    factory.register_factor("vol_std_20", alpha_volume_std_20)
    factory.register_factor("pv_corr_10", alpha_price_volume_corr)
    factory.register_factor("range_pos", alpha_range_pos)
    
    # 2. Load Consolidated Data (Sample: 2025)
    logger.info("Loading 2025 market data...")
    data_path = Path("/Users/gdxj/quant_data_lake/consolidated/market_2025.parquet")
    if not data_path.exists():
        logger.error("Consolidated data not found. Run consolidate_lake.py first.")
        return
        
    df = pd.read_parquet(data_path)
    
    # 3. Compute Alphas
    df = factory.compute_factors(df)
    
    # 4. Evaluate (IC Analysis)
    logger.info("Evaluating factors...")
    report = factory.evaluate_factors(df, horizon=5) # 5-day horizon
    
    print("\n" + "="*50)
    print("        ALPHA FACTORY MINING REPORT (2025)")
    print("="*50)
    print(report.to_string(index=False))
    print("="*50 + "\n")
    
    # 5. Save Results
    results_path = Path("results/alpha_mining_2025.csv")
    results_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(results_path, index=False)
    logger.info(f"Report saved to {results_path}")

if __name__ == "__main__":
    run_mining_session()
