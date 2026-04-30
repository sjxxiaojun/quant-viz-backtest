import baostock as bs
import pandas as pd


def run_baostock_smoke():
    lg = bs.login()
    print(f"Login code: {lg.error_code}, message: {lg.error_msg}")
    if lg.error_code != '0':
        return
    
    # Try fetching a well-known stock
    symbol = "sh.600519" # Moutai
    rs = bs.query_history_k_data_plus(
        symbol,
        "date,open,high,low,close,volume,amount,pctChg",
        start_date="2024-01-01", 
        end_date="2024-01-10", 
        frequency="d", 
        adjustflag="2"
    )
    print(f"Query code: {rs.error_code}, message: {rs.error_msg}")
    
    data = []
    while rs.next():
        data.append(rs.get_row_data())
    
    df = pd.DataFrame(data, columns=rs.fields)
    print(f"Data retrieved: {len(df)} rows")
    if not df.empty:
        print(df.head())
    
    bs.logout()

if __name__ == "__main__":
    run_baostock_smoke()
