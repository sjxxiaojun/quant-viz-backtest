import baostock as bs
import pandas as pd
from pathlib import Path
import sys
import os

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_manager import DataManager

def sync_baostock(target_date="2026-04-24"):
    print(f"🚀 开始通过 Baostock 同步 {target_date} 数据...")
    
    lg = bs.login()
    if lg.error_code != '0':
        print(f"❌ Baostock 登录失败: {lg.error_msg}")
        return

    dm = DataManager()
    all_codes = dm.list_local_codes()
    print(f"🔍 发现本地缓存标的 {len(all_codes)} 只")
    
    success_count = 0
    fields = "date,open,high,low,close,volume,amount,pctChg"
    
    # Baostock 批量查询较慢，我们只更新本地已有的
    for code in all_codes:
        bs_code = dm._get_bs_symbol(code)
        rs = bs.query_history_k_data_plus(
            bs_code, fields,
            start_date=target_date, end_date=target_date,
            frequency="d", adjustflag="2"
        )
        
        if rs.error_code == '0' and rs.next():
            row = rs.get_row_data()
            cache_path = dm.get_cache_path(code)
            try:
                df = pd.read_parquet(cache_path)
                if target_date in df['date'].values:
                    continue
                
                new_row = {
                    'date': target_date,
                    'open': float(row[1]) if row[1] else 0,
                    'high': float(row[2]) if row[2] else 0,
                    'low': float(row[3]) if row[3] else 0,
                    'close': float(row[4]) if row[4] else 0,
                    'volume': float(row[5]) if row[5] else 0,
                    'amount': float(row[6]) if row[6] else 0,
                    'pct_chg': float(row[7]) if row[7] else 0,
                    'stock_code': code,
                    'stock_name': df['stock_name'].iloc[0] if not df.empty else code
                }
                
                if new_row['close'] > 0:
                    new_df = pd.concat([df, pd.DataFrame([new_row])]).sort_values('date').drop_duplicates('date')
                    new_df.to_parquet(cache_path, index=False)
                    success_count += 1
                    if success_count % 100 == 0:
                        print(f"  已更新 {success_count} 只...")
            except:
                pass
                
    bs.logout()
    print(f"✅ 同步完成，共更新 {success_count} 只标的。")

if __name__ == "__main__":
    sync_baostock("2026-04-24")
