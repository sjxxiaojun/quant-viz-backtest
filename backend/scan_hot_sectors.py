import pandas as pd
import numpy as np
import os
import baostock as bs
from datetime import datetime, timedelta
from strategies.extra_strategies_pro_plus import calculate_blackhorse_signals_pro_plus

def scan_hot_sectors():
    # 今日热点标的
    hot_pool = {
        "688017.SH": "绿的谐波", "002472.SZ": "双环传动", "002050.SZ": "三花智控", "002747.SZ": "埃斯顿", # 机器人
        "300073.SZ": "当升科技", "688567.SH": "孚能科技", "300750.SZ": "宁德时代"  # 固态电池
    }
    
    end_date_str = datetime.now().strftime('%Y-%m-%d')
    start_date_str = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
    
    bs.login()
    all_data = []
    for symbol, name in hot_pool.items():
        code, exch = symbol.split(".")
        # 获取最近 60 日数据用于计算 Pro++ 因子
        rs = bs.query_history_k_data_plus(f"{exch.lower()}.{code}",
            "date,open,high,low,close,volume,amount,pctChg,peTTM,pbMRQ",
            start_date=start_date_str, end_date=end_date_str,
            frequency="d", adjustflag="3")
        data = []
        while rs.next(): data.append(rs.get_row_data())
        if data:
            df = pd.DataFrame(data, columns=rs.fields)
            df = df.rename(columns={'pctChg': 'pct_chg', 'peTTM': 'pe', 'pbMRQ': 'pb'})
            df['stock_code'] = code
            df['stock_name'] = name
            for col in ['open', 'high', 'low', 'close', 'volume', 'amount', 'pct_chg', 'pe', 'pb']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            all_data.append(df)
    bs.logout()
    
    if all_data:
        full_df = pd.concat(all_data)
        # 运行小G前锋扫描
        results = calculate_blackhorse_signals_pro_plus(full_df)
        latest = results[results['date'] == results['date'].max()].sort_values('score', ascending=False)
        
        report = f"# 🏹 小G前锋：{end_date_str} 今日热点黑马猎杀名单\n"
        report += latest[['stock_code', 'stock_name', 'score']].to_markdown(index=False)
        
        with open("../results/quant-factor-mining/reports/daily_hot_scan.md", "w") as f:
            f.write(report)
        print("Hot scan complete.")

if __name__ == "__main__":
    os.chdir("/Users/gdxj/quant-viz-backtest/backend")
    scan_hot_sectors()
