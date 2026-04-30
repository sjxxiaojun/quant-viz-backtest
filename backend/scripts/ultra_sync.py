import os
import sys
import pandas as pd
import requests
import json
from pathlib import Path
from datetime import datetime
import concurrent.futures
import logging

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_manager import DataManager

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("UltraSync")

def get_market_snapshot():
    """
    Fetch all A-share stocks latest price from Eastmoney API directly.
    """
    logger.info("正在从东方财富获取全市场实时快照...")
    all_stocks = []
    # Broad filter for all A-shares across all boards
    fs_filter = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048,m:1+t:1,m:1+t:10"
    for page in range(1, 35):
        url = f"https://82.push2delay.eastmoney.com/api/qt/clist/get?pn={page}&pz=200&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f12&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048,m:1+t:1,m:1+t:10&fields=f12,f14,f2,f3,f17,f15,f16,f5,f6"
        try:
            r = requests.get(url, timeout=20, proxies={'http': None, 'https': None})
            data = r.json()
            if not data or 'data' not in data or not data['data'] or 'diff' not in data['data']:
                break
            stocks = data['data']['diff']
            if not stocks:
                break
            all_stocks.extend(stocks)
            if page % 5 == 0:
                logger.info(f"已获取 {len(all_stocks)} 只标的快照...")
        except Exception as e:
            logger.error(f"第 {page} 页获取失败: {e}")
            break
            
    logger.info(f"全市场快照获取完成，共 {len(all_stocks)} 只标的。")
    return all_stocks

def update_parquet_with_snapshot(stocks, target_date="2026-04-24"):
    dm = DataManager()
    success_count = 0
    already_updated = 0
    missing_file = 0
    
    logger.info(f"开始同步本地池至 {target_date}...")
    
    def process_one(s):
        code = s['f12']
        potential_paths = [
            dm.cache_dir / f"{code}_full_history.parquet",
            dm.cache_dir / f"sh.{code}_full_history.parquet",
            dm.cache_dir / f"sz.{code}_full_history.parquet"
        ]
        
        target_path = None
        for p in potential_paths:
            if p.exists():
                target_path = p
                break
        
        if not target_path:
            return "missing"
            
        try:
            df = pd.read_parquet(target_path)
            if target_date in df['date'].values:
                return "exists"
            
            # Create new row
            new_row = {
                'date': target_date,
                'stock_code': code,
                'stock_name': s['f14'],
                'open': float(s['f17']) if s['f17'] != '-' else 0,
                'high': float(s['f15']) if s['f15'] != '-' else 0,
                'low': float(s['f16']) if s['f16'] != '-' else 0,
                'close': float(s['f2']) if s['f2'] != '-' else 0,
                'volume': float(s['f5']) if s['f5'] != '-' else 0,
                'amount': float(s['f6']) if s['f6'] != '-' else 0,
                'pct_chg': float(s['f3']) if s['f3'] != '-' else 0
            }
            
            if new_row['close'] == 0:
                return "invalid"
                
            new_df = pd.concat([df, pd.DataFrame([new_row])]).sort_values('date').drop_duplicates('date')
            new_df.to_parquet(target_path)
            return "success"
        except:
            return "error"

    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
        results = list(executor.map(process_one, stocks))
        success_count = sum(1 for r in results if r == "success")
        already_updated = sum(1 for r in results if r == "exists")
        missing_file = sum(1 for r in results if r == "missing")

    logger.info(f"同步报告:")
    logger.info(f" - 成功更新: {success_count} 只")
    logger.info(f" - 本地已存在: {already_updated} 只")
    logger.info(f" - 本地文件缺失: {missing_file} 只")

if __name__ == "__main__":
    stocks = get_market_snapshot()
    if stocks:
        update_parquet_with_snapshot(stocks, "2026-04-24")
