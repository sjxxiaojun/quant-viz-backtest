import os
from data_manager import DataManager
import time

def test():
    print("Testing local cache...")
    os.environ.pop("DATA_LAKE_API_URL", None)
    dm_local = DataManager()
    t0 = time.time()
    df_local, src_local = dm_local.get_stock_data("000001", "2023-01-01", "2023-01-10", allow_mock=True, auto_login=False)
    print(f"Local: fetched {len(df_local)} rows from {src_local} in {time.time() - t0:.2f}s")
    
    print("Testing remote API mode...")
    os.environ["DATA_LAKE_API_URL"] = "http://localhost:8081"
    dm_remote = DataManager()
    t0 = time.time()
    df_remote, src_remote = dm_remote.get_stock_data("000001", "2023-01-01", "2023-01-10", allow_mock=True, auto_login=False)
    print(f"Remote: fetched {len(df_remote)} rows from {src_remote} in {time.time() - t0:.2f}s")
    
    print("Testing bulk pool remote mode...")
    t0 = time.time()
    df_pool, sources = dm_remote.get_stock_pool_data(["000001", "600519"], "2023-01-01", "2023-01-10", allow_mock=True)
    print(f"Remote Pool: fetched {len(df_pool)} rows from {list(sources.keys())} in {time.time() - t0:.2f}s")

if __name__ == "__main__":
    test()
