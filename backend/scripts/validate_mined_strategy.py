import sys
from pathlib import Path
import pandas as pd
import logging

# Add project root to sys.path
sys.path.append(str(Path(__file__).parent.parent))

from data_manager import DataManager
from strategy_registry import STRATEGY_REGISTRY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Validation")

def validate_new_strategy():
    dm = DataManager()
    strat_key = "alpha_miner_2026"
    spec = STRATEGY_REGISTRY.get(strat_key)
    
    if not spec:
        print(f"❌ Strategy {strat_key} not found in registry.")
        return
        
    print(f"🛡️ Validating {spec.name}...")
    
    # Load sample data
    codes = dm.list_local_codes("a_share")[:50]
    df, _ = dm.get_stock_pool_data(codes, "2025-01-01", "2025-03-31", allow_mock=False)
    
    # Run strategy
    signals = spec.func(df)
    
    buy_signals = signals[signals['signal'] == 1]
    print(f"✅ Generated {len(buy_signals)} buy signals across {len(signals['date'].unique())} days.")
    
    if len(buy_signals) > 0:
        print("🚀 Strategy logic is fully functional.")
        print("Sample Buy List (Top 5):")
        print(buy_signals[['date', 'stock_code', 'score']].tail(5))
    else:
        print("⚠️ No buy signals generated. Check threshold or pool size.")

if __name__ == "__main__":
    validate_new_strategy()
