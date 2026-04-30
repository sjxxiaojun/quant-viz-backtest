import sys
import os
import sqlite3
import pandas as pd
import logging
from datetime import datetime, timedelta

# Add parent dir to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_manager import DataManager
from strategy_registry import STRATEGY_REGISTRY

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("EmergencySeed")

CORE_STRATEGY_KEYS = [
    "blackhorse", "ai_adaptive", "ai_ml", "bottom_fishing", "bottom_fishing_stable",
    "overnight", "weak_to_strong", "limit_up_doji", "sector_alpha", "turtle",
    "hfmr", "reversal", "atm"
]

def seed_now():
    dm = DataManager()
    conn = sqlite3.connect("virtual_trading.db")
    cursor = conn.cursor()
    
    # Ensure tables exist (just in case)
    # They should exist because VTM ensures them
    
    logger.info("开始紧急初始化 13 个策略账户...")
    
    target_date = "2026-04-23"
    
    for key in CORE_STRATEGY_KEYS:
        spec = STRATEGY_REGISTRY.get(key)
        if not spec: continue
        
        # Check if already exists
        cursor.execute("SELECT count(*) FROM accounts WHERE strategy_id = ?", (key,))
        if cursor.fetchone()[0] > 0:
            logger.info(f"策略 {key} 已存在，跳过。")
            continue
            
        logger.info(f"正在初始化策略: {spec.name} ({key})...")
        
        # Initial state: 100,000 Cash, 0 positions
        cursor.execute("""
            INSERT INTO accounts (strategy_id, strategy_name, cash, total_value, start_value, last_update)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (key, spec.name, 100000.0, 100000.0, 100000.0, "2026-04-22"))
    
    conn.commit()
    conn.close()
    logger.info("紧急初始化完成！现在可以点击『一键执行今日模拟』来进行调仓了。")

if __name__ == "__main__":
    seed_now()
