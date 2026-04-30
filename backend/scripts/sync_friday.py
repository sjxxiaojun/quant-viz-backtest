import pandas as pd
import akshare as ak
from pathlib import Path
from datetime import datetime
import sys
import os

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_manager import DataManager

# 显式禁用代理，防止 AKShare 报错
os.environ['no_proxy'] = '*'
os.environ['http_proxy'] = ''
os.environ['https_proxy'] = ''
os.environ['all_proxy'] = ''

def sync_latest_data(target_date="2026-04-24"):
    print(f"🚀 开始通过 AKShare 同步最新行情数据 (目标日期: {target_date})...")
    
    # 1. 获取全市场快照
    try:
        df_spot = ak.stock_zh_a_spot_em()
        print(f"✅ 获取到 {len(df_spot)} 只股票的实时快照")
    except Exception as e:
        print(f"❌ 获取快照失败: {e}")
        return

    dm = DataManager()
    success_count = 0
    missing_count = 0
    
    # 2. 遍历快照并更新 Parquet
    # f12: 代码, f14: 名称, f2: 最新价, f3: 涨跌幅, f17: 开盘, f15: 最高, f16: 最低, f5: 成交量, f6: 成交额
    for _, row in df_spot.iterrows():
        code = row['代码']
        cache_path = dm.get_cache_path(code)
        
        if not cache_path.exists():
            missing_count += 1
            continue
            
        try:
            df_hist = pd.read_parquet(cache_path)
            if target_date in df_hist['date'].values:
                continue
                
            new_row = {
                'date': target_date,
                'open': float(row['开盘']) if row['开盘'] != '-' else 0,
                'high': float(row['最高']) if row['最高'] != '-' else 0,
                'low': float(row['最低']) if row['最低'] != '-' else 0,
                'close': float(row['最新价']) if row['最新价'] != '-' else 0,
                'volume': float(row['成交量']) if row['成交量'] != '-' else 0,
                'amount': float(row['成交额']) if row['成交额'] != '-' else 0,
                'pct_chg': float(row['涨跌幅']) if row['涨跌幅'] != '-' else 0,
                'stock_code': code,
                'stock_name': row['名称']
            }
            
            if new_row['close'] == 0:
                continue
                
            # 合并并保存
            new_df = pd.concat([df_hist, pd.DataFrame([new_row])]).sort_values('date').drop_duplicates('date')
            new_df.to_parquet(cache_path, index=False)
            success_count += 1
            
            if success_count % 500 == 0:
                print(f"  已更新 {success_count} 只...")
                
        except Exception as e:
            # print(f"  [{code}] 更新失败: {e}")
            pass

    print(f"\n📊 同步完成报告:")
    print(f" - 成功更新: {success_count} 只")
    print(f" - 本地文件缺失: {missing_count} 只")

if __name__ == "__main__":
    sync_latest_data("2026-04-24")
