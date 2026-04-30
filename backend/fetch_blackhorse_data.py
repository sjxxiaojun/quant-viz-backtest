import pandas as pd
import numpy as np
import os
import baostock as bs
from datetime import datetime

def fetch_blackhorse_data():
    output_dir = "/Users/gdxj/quant-viz-backtest/backend/data_cache/blackhorse_study"
    os.makedirs(output_dir, exist_ok=True)
    
    # 低空经济 & AI 算力 核心标的
    blackhorse_pool = [
        # AI 算力 / CPO / 芯片
        "000977.SZ", "300308.SZ", "688256.SH", "688041.SH", "002230.SZ", "300502.SZ",
        # 低空经济 / 飞行汽车
        "000099.SZ", "002085.SZ", "001696.SZ", "301091.SZ", "603611.SH"
    ]
    
    name_map = {
        "000977": "浪潮信息", "300308": "中际旭创", "688256": "寒武纪", 
        "688041": "海光信息", "002230": "科大讯飞", "300502": "新易盛",
        "000099": "中信海直", "002085": "万丰奥威", "001696": "宗申动力",
        "301091": "深城交", "603611": "建新股份"
    }
    
    parquet_dir = "/Users/gdxj/acodex/量化/data/parquet/research/daily_bars/akshare/raw"
    bs.login()
    
    for symbol in blackhorse_pool:
        code, exch = symbol.split(".")
        bs_code = f"{exch.lower()}.{code}"
        
        # 加载行情
        parquet_path = os.path.join(parquet_dir, f"{symbol}.parquet")
        if os.path.exists(parquet_path):
            df_tech = pd.read_parquet(parquet_path)
            df_tech['date'] = pd.to_datetime(df_tech['trade_date']).dt.strftime('%Y-%m-%d')
            df_tech = df_tech.rename(columns={'pct_change': 'pct_chg'})
            df_tech = df_tech[df_tech['date'] >= '2023-01-01']
        else:
            continue
            
        # 获取基本面
        rs = bs.query_history_k_data_plus(
            bs_code, "date,peTTM,pbMRQ,psTTM",
            start_date='2023-01-01', end_date='2026-04-21',
            frequency="d", adjustflag="3"
        )
        fund_list = []
        while rs.next(): fund_list.append(rs.get_row_data())
        
        if fund_list:
            df_fund = pd.DataFrame(fund_list, columns=rs.fields)
            final_df = pd.merge(df_tech, df_fund, on='date', how='inner')
            final_df['stock_code'] = code
            final_df['stock_name'] = name_map.get(code, "未知")
            for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'peTTM', 'pbMRQ']:
                final_df[col] = pd.to_numeric(final_df[col], errors='coerce')
            final_df = final_df.rename(columns={'peTTM': 'pe', 'pbMRQ': 'pb'})
            final_df.to_parquet(os.path.join(output_dir, f"{code}.parquet"))
            print(f"Blackhorse data for {symbol} saved.")
            
    bs.logout()

if __name__ == "__main__":
    fetch_blackhorse_data()
