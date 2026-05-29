import sys
import os
import json
from pathlib import Path
import pandas as pd

BACKEND_DIR = Path("/Users/gdxj/quant-viz-backtest/backend")
sys.path.insert(0, str(BACKEND_DIR))

import daily_update_quant_data_lake as dl

def get_core_symbols():
    pools_path = BACKEND_DIR / "pools.json"
    with open(pools_path, 'r', encoding='utf-8') as f:
        pools = json.load(f)
    symbols = set()
    for name, list_symbols in pools.items():
        for s in list_symbols:
            symbols.add(s)
    return symbols

def main():
    end_date = "2026-05-21"
    buffer_days = 7
    retry = 3
    task_timeout = 90
    
    core_symbols = get_core_symbols()
    print(f"Loaded {len(core_symbols)} core symbols from pools.json")
    
    dl.ensure_dirs()
    
    # 1. Build A-share tasks
    _, a_share_tasks, _ = dl.build_a_share_tasks(
        end_date=end_date,
        buffer_days=buffer_days,
        limit=0,
        dry_run=False
    )
    
    # Filter A-share tasks
    core_a_share_tasks = [t for t in a_share_tasks if t["code"] in core_symbols]
    print(f"Scheduled {len(core_a_share_tasks)} / {len(a_share_tasks)} A-share tasks for core symbols")
    
    # 2. Build ETF tasks
    _, etf_tasks = dl.build_etf_tasks(
        end_date=end_date,
        buffer_days=buffer_days,
        limit=0
    )
    
    # Filter ETF tasks
    core_etf_tasks = [t for t in etf_tasks if t["code"] in core_symbols]
    print(f"Scheduled {len(core_etf_tasks)} / {len(etf_tasks)} ETF tasks for core symbols")
    
    # 3. Run pools
    from functools import partial
    import time
    
    start_ts = time.time()
    
    a_share_results = []
    if core_a_share_tasks:
        print("\nStarting A-share sync for core symbols...")
        a_share_results = dl.run_pool(
            tasks=core_a_share_tasks,
            worker=partial(dl.fetch_a_share_task, end_date=end_date, retry=retry, task_timeout=task_timeout),
            max_workers=6,
            hard_timeout=max(60, (task_timeout + 12) * max(1, retry) * 2 + 30)
        )
        
    etf_results = []
    if core_etf_tasks:
        print("\nStarting ETF sync for core symbols...")
        etf_results = dl.run_pool(
            tasks=core_etf_tasks,
            worker=partial(dl.fetch_etf_task, end_date=end_date, retry=retry, task_timeout=task_timeout),
            max_workers=4,
            hard_timeout=max(60, (task_timeout + 12) * max(1, retry) * 2 + 30)
        )
        
    elapsed = time.time() - start_ts
    print(f"\nSync finished in {elapsed:.2f} seconds.")
    
    # Report results
    a_success = sum(1 for r in a_share_results if r["status"] == "success")
    a_fail = sum(1 for r in a_share_results if r["status"] == "failed")
    etf_success = sum(1 for r in etf_results if r["status"] == "success")
    etf_fail = sum(1 for r in etf_results if r["status"] == "failed")
    
    print(f"A-Share Sync: {a_success} succeeded, {a_fail} failed.")
    print(f"ETF Sync: {etf_success} succeeded, {etf_fail} failed.")
    
    if a_fail > 0:
        print("\nFailed A-shares:")
        for r in a_share_results:
            if r["status"] == "failed":
                print(f"  {r['code']} ({r['name']}): {r['error']}")
                
    if etf_fail > 0:
        print("\nFailed ETFs:")
        for r in etf_results:
            if r["status"] == "failed":
                print(f"  {r['code']} ({r['name']}): {r['error']}")

if __name__ == "__main__":
    main()
