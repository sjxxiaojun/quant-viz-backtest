import os
import time
import pandas as pd
import akshare as ak
import baostock as bs
from concurrent.futures import ProcessPoolExecutor, as_completed

# Make sure this runs independently to build the full market data lake
CACHE_DIR = "/Users/gdxj/quant_data_lake"
if not os.path.exists(CACHE_DIR):
    os.makedirs(CACHE_DIR)

def _get_bs_symbol(symbol):
    if not symbol: return ""
    if symbol.startswith(('92', '4', '8', '43', '83', '87', '88', '89')): return f"bj.{symbol}"
    if symbol.startswith(('6', '5', '11')): return f"sh.{symbol}"
    elif symbol.startswith(('0', '3', '2')): return f"sz.{symbol}"
    return f"sz.{symbol}"

def fetch_single_stock(symbol, start_date="2022-01-01", end_date=None):
    if not end_date:
        end_date = pd.Timestamp.today().strftime('%Y-%m-%d')
        
    cache_path = os.path.join(CACHE_DIR, f"{symbol}_full_history.parquet")
    
    # Skip if recently updated (very basic check)
    if os.path.exists(cache_path):
        try:
            df = pd.read_parquet(cache_path)
            if not df.empty and df['date'].max() >= pd.Timestamp.today().strftime('%Y-%m-%d'):
                return symbol, "Cached"
        except:
            pass

    # Process-safe Baostock login
    bs.login()
    try:
        bs_symbol = _get_bs_symbol(symbol)
        # Expanded comprehensive fields: turn(turnover), pe(PE), pb(PB), ps(PS), pcf(PCF), isST, tradestatus
        fields = "date,open,high,low,close,volume,amount,pctChg,turn,tradestatus,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
        rs = bs.query_history_k_data_plus(bs_symbol, fields, start_date=start_date, end_date=end_date, frequency="d", adjustflag="2")
        data_list = []
        while rs.next(): data_list.append(rs.get_row_data())
        if data_list:
            new_df = pd.DataFrame(data_list, columns=rs.fields)
            new_df = new_df.rename(columns={
                "pctChg": "pct_chg", "peTTM": "pe", "pbMRQ": "pb",
                "psTTM": "ps", "pcfNcfTTM": "pcf", "isST": "is_st"
            })
            for col in ["open", "high", "low", "close", "volume", "amount", "pct_chg", "turn", "pe", "pb", "ps", "pcf"]: 
                new_df[col] = pd.to_numeric(new_df[col], errors='coerce')
            new_df['stock_code'] = symbol
            rs_name = bs.query_stock_basic(code=bs_symbol)
            new_df['stock_name'] = rs_name.get_row_data()[1] if rs_name.next() else symbol
            new_df.to_parquet(cache_path)
            return symbol, f"Success ({len(new_df)} rows)"
        return symbol, "No Data"
    except Exception as e:
        return symbol, f"Error: {str(e)}"
    finally:
        bs.logout()

def download_full_market():
    print("Fetching A-share & ETF market symbols...")
    stock_symbols = []
    etf_symbols = []
    
    # 1. Get A-share Stocks with retries
    for attempt in range(3):
        try:
            spot_df = ak.stock_zh_a_spot_em()
            stock_symbols = spot_df['代码'].tolist()
            print(f"Loaded {len(stock_symbols)} Stock symbols from network.")
            break
        except Exception as e:
            print(f"Attempt {attempt+1} failed to get stock spot data: {e}")
            time.sleep(2)
            
    # 2. Get ETFs with retries
    for attempt in range(3):
        try:
            etf_df = ak.fund_etf_spot_em()
            etf_symbols = etf_df['代码'].tolist()
            print(f"Loaded {len(etf_symbols)} ETF symbols from network.")
            break
        except Exception as e:
            print(f"Attempt {attempt+1} failed to get ETF spot data: {e}")
            time.sleep(2)

    # 3. Independent Fallbacks
    if not stock_symbols or not etf_symbols:
        print("Some network fetches failed. Checking local cache for missing symbols...")
        if os.path.exists(CACHE_DIR):
            local_files = [f.split('_')[0] for f in os.listdir(CACHE_DIR) if f.endswith('_full_history.parquet')]
            local_stocks = [s for s in local_files if not s.startswith(('5', '1'))]
            local_etfs = [s for s in local_files if s.startswith(('5', '1'))]
            
            if not stock_symbols:
                stock_symbols = local_stocks
                print(f"Recovered {len(stock_symbols)} Stocks from local cache.")
            if not etf_symbols:
                etf_symbols = local_etfs
                print(f"Recovered {len(etf_symbols)} ETFs from local cache.")

    symbols = list(set(stock_symbols + etf_symbols))
    if not symbols:
        print("Critical failure: No symbols found anywhere. Falling back to test pool.")
        symbols = ["600519", "510300"]
        
    # Remove duplicates if any
    symbols = list(set(symbols))
    print(f"Total unique symbols to fetch: {len(symbols)}")
    print("Starting multiprocessing download (this will take a while)...")
    
    start_time = time.time()
    success_count = 0
    
    # Use ProcessPoolExecutor to bypass Baostock threading issues
    with ProcessPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(fetch_single_stock, sym): sym for sym in symbols}
        
        for i, future in enumerate(as_completed(futures)):
            sym, status = future.result()
            if "Success" in status or "Cached" in status:
                success_count += 1
            if (i + 1) % 100 == 0:
                print(f"[{i+1}/{len(symbols)}] Processed. Last: {sym} -> {status}")
                
    elapsed = time.time() - start_time
    print(f"\nDownload Complete! Time taken: {elapsed/60:.2f} mins")
    print(f"Successfully downloaded/cached: {success_count}/{len(symbols)}")

if __name__ == "__main__":
    # Disable proxy for multiprocessing
    os.environ['no_proxy'] = '*'
    os.environ['http_proxy'] = ''
    os.environ['https_proxy'] = ''
    os.environ['all_proxy'] = ''
    download_full_market()
