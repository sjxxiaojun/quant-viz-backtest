import os
import pandas as pd
from pathlib import Path
import logging
import time
import concurrent.futures

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Consolidator")

def read_file(f):
    try:
        df = pd.read_parquet(f)
        # Only keep essential columns for alpha mining to save memory
        cols = ['date', 'stock_code', 'open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg', 'turnover_rate']
        available = [c for c in cols if c in df.columns]
        return df[available]
    except Exception as e:
        logger.error(f"Error reading {f.name}: {e}")
        return None

def consolidate_lake(lake_dir="/Users/gdxj/quant_data_lake", output_dir="/Users/gdxj/quant_data_lake/consolidated"):
    lake_path = Path(lake_dir)
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    files = list(lake_path.glob("*_full_history.parquet"))
    logger.info(f"Found {len(files)} files to consolidate.")
    
    start_time = time.time()
    
    # Concurrent reading using ProcessPoolExecutor for CPU-bound decompression
    all_data = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=os.cpu_count()) as executor:
        results = list(executor.map(read_file, files))
        all_data = [r for r in results if r is not None]
    
    logger.info(f"Read {len(all_data)} files in {time.time() - start_time:.2f}s")
    
    if not all_data:
        logger.error("No data found.")
        return

    # Merge
    logger.info("Merging all data...")
    final_df = pd.concat(all_data, ignore_index=True)
    
    # Convert date to datetime for better partitioning
    final_df['date'] = pd.to_datetime(final_df['date'])
    
    # Save as partitioned parquet by year
    logger.info("Saving consolidated data by year...")
    final_df['year'] = final_df['date'].dt.year
    
    for year, group in final_df.groupby('year'):
        year_file = out_path / f"market_{year}.parquet"
        group.drop(columns=['year']).to_parquet(year_file, index=False)
        logger.info(f"Saved {year_file}")

    logger.info(f"Consolidation complete in {time.time() - start_time:.2f}s")

if __name__ == "__main__":
    consolidate_lake()
