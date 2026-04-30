import sys
import os
import pandas as pd
import akshare as ak
from pathlib import Path
from datetime import datetime, timedelta
import concurrent.futures
import logging

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_manager import DataManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DataSync")

def sync_stock(dm, symbol, target_date):
    try:
        # get_stock_data will automatically fetch from AKShare if cache is missing target_date
        df, source = dm.get_stock_data(symbol, target_date, target_date, allow_mock=False)
        if not df.empty and df['date'].max() == target_date:
            return True, source
        return False, "Data missing"
    except Exception as e:
        return False, str(e)

def fast_bulk_sync(target_date="2026-04-23"):
    dm = DataManager()
    all_symbols = dm.list_local_codes("a_share")
    etf_symbols = dm.list_local_codes("etf")
    
    symbols_to_check = all_symbols + etf_symbols
    missing = []
    
    logger.info(f"检查 {len(symbols_to_check)} 只标的是否包含 {target_date} 数据...")
    
    # Check cache in parallel (much faster)
    def check_one(sym):
        cache_path = dm.get_cache_path(sym)
        if cache_path.exists():
            try:
                # Use metadata or fast check
                df = pd.read_parquet(cache_path, columns=['date'])
                if target_date not in df['date'].values:
                    return sym
            except:
                return sym
        else:
            return sym
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as check_executor:
        results = list(check_executor.map(check_one, symbols_to_check))
        missing = [r for r in results if r is not None]
            
    if not missing:
        logger.info("🎉 所有数据均已同步至最新！")
        return

    logger.info(f"发现 {len(missing)} 只标的数据落后，开始增量同步...")
    
    # Use more workers but be careful with AKShare limits
    success_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_sym = {executor.submit(sync_stock, dm, sym, target_date): sym for sym in missing}
        for i, future in enumerate(concurrent.futures.as_completed(future_to_sym)):
            sym = future_to_sym[future]
            success, msg = future.result()
            if success:
                success_count += 1
            
            if (i + 1) % 100 == 0:
                logger.info(f"进度: {i+1}/{len(missing)} (成功: {success_count})")

    logger.info(f"同步完成！成功更新 {success_count} 只标的。")

if __name__ == "__main__":
    # We sync for 4.22 and 4.23
    for dt in ["2026-04-22", "2026-04-23"]:
        logger.info(f"=== 开始同步 {dt} 数据 ===")
        fast_bulk_sync(dt)
