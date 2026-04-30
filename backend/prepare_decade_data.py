import pandas as pd
import numpy as np
import os
import baostock as bs
from datetime import datetime

def prepare_decade_data():
    output_dir = "/Users/gdxj/quant-viz-backtest/backend/data_cache/decade_study"
    os.makedirs(output_dir, exist_ok=True)
    
    # 选定 15 只具备 10 年历史的行业代表性股票
    stock_pool = [
        "600519.SH", "000001.SZ", "600036.SH", "601318.SH", 
        "601012.SH", "002594.SZ", "600900.SH", "002371.SZ",
        "600406.SH", "000333.SZ", "601888.SH", "600030.SH",
        "000002.SZ", "601398.SH", "002415.SZ"
    ]
    
    parquet_dir = "/Users/gdxj/acodex/量化/data/parquet/research/daily_bars/akshare/raw"
    bs.login()
    
    for symbol in stock_pool:
        code, exch = symbol.split(".")
        bs_code = f"{exch.lower()}.{code}"
        
        # 1. 尝试合并本地行情
        parquet_path = os.path.join(parquet_dir, f"{symbol}.parquet")
        if os.path.exists(parquet_path):
            df_tech = pd.read_parquet(parquet_path)
            df_tech['date'] = pd.to_datetime(df_tech['trade_date']).dt.strftime('%Y-%m-%d')
            # 统一列名以适配 DataManager
            df_tech = df_tech.rename(columns={'pct_change': 'pct_chg'})
        else:
            print(f"No local data for {symbol}, skip.")
            continue
            
        # 2. 获取 10 年基本面数据 (2016-2026)
        print(f"Fetching 10-year indicators for {bs_code}...")
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,peTTM,pbMRQ,psTTM",
            start_date='2016-01-01', end_date='2026-04-21',
            frequency="d", adjustflag="3"
        )
        
        fund_list = []
        while rs.next():
            fund_list.append(rs.get_row_data())
            
        if fund_list:
            df_fund = pd.DataFrame(fund_list, columns=rs.fields)
            
            # 合并
            final_df = pd.merge(df_tech, df_fund, on='date', how='inner')
            final_df['stock_code'] = code
            # 加上名称映射 (DataManager 需要)
            name_map = {"600519": "贵州茅台", "000001": "平安银行", "600036": "招商银行", 
                        "601318": "中国平安", "601012": "隆基绿能", "002594": "比亚迪",
                        "600900": "长江电力", "002371": "北方华创", "600406": "国电南瑞",
                        "000333": "美的集团", "601888": "中国中免", "600030": "中信证券",
                        "000002": "万科A", "601398": "工商银行", "002415": "海康威视"}
            final_df['stock_name'] = name_map.get(code, "未知")
            
            # 转换为 numeric
            for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'peTTM', 'pbMRQ']:
                final_df[col] = pd.to_numeric(final_df[col], errors='coerce')
            
            # 重命名适配策略函数
            final_df = final_df.rename(columns={'peTTM': 'pe', 'pbMRQ': 'pb'})
            
            save_path = os.path.join(output_dir, f"{code}.parquet")
            final_df.to_parquet(save_path)
            print(f"Decade data for {symbol} saved. ({len(final_df)} rows)")
            
    bs.logout()

if __name__ == "__main__":
    prepare_decade_data()
