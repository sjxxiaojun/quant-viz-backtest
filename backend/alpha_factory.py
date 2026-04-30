import pandas as pd
import numpy as np
from typing import List, Dict, Callable
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("AlphaFactory")

class AlphaFactory:
    """
    Professional Alpha Mining Engine.
    Closed-loop: Data -> Factor -> Eval -> Deploy.
    """
    def __init__(self, data_manager):
        self.dm = data_manager
        self.factors = {}
        
    def register_factor(self, name: str, func: Callable):
        self.factors[name] = func
        
    def compute_factors(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute all registered factors on the provided multi-stock dataframe.
        """
        logger.info(f"Computing {len(self.factors)} factors on {len(df)} rows...")
        df = df.sort_values(['stock_code', 'date'])
        
        for name, func in self.factors.items():
            try:
                df[name] = func(df)
                logger.info(f"Factor {name} computed.")
            except Exception as e:
                logger.error(f"Failed to compute factor {name}: {e}")
                
        return df

    def evaluate_factors(self, df: pd.DataFrame, horizon: int = 5) -> pd.DataFrame:
        """
        Calculate Information Coefficient (IC) for each factor.
        Returns a summary DataFrame.
        """
        # Calculate future returns
        df = df.sort_values(['stock_code', 'date'])
        df['fwd_ret'] = df.groupby('stock_code')['close'].shift(-horizon) / df['close'] - 1
        
        # Drop rows without future returns (end of sample)
        df = df.dropna(subset=['fwd_ret'])
        
        metrics = []
        for name in self.factors.keys():
            if name not in df.columns: continue
            
            # Rank IC per day
            def calc_daily_ic(group):
                if len(group) < 10: return np.nan
                return group[name].corr(group['fwd_ret'], method='spearman')
            
            ic_series = df.groupby('date', group_keys=False).apply(calc_daily_ic)
            ic_series = ic_series.dropna()
            
            if ic_series.empty: continue
            
            mean_ic = ic_series.mean()
            std_ic = ic_series.std()
            ir = mean_ic / std_ic if std_ic > 0 else 0
            
            metrics.append({
                "factor": name,
                "mean_ic": mean_ic,
                "ic_std": std_ic,
                "ir": ir,
                "ic_win_rate": (ic_series > 0).mean() if mean_ic > 0 else (ic_series < 0).mean(),
                "t_stat": (mean_ic / std_ic) * np.sqrt(len(ic_series)) if std_ic > 0 else 0
            })
            
        return pd.DataFrame(metrics).sort_values('ir', ascending=False)

# --- Alpha Library (Alpha 101 Inspired) ---

def alpha_momentum_120(df):
    """Long-term momentum"""
    return df.groupby('stock_code')['close'].pct_change(120)

def alpha_reversal_short(df):
    """Short-term reversal (1-day)"""
    return -df.groupby('stock_code')['close'].pct_change(1)

def alpha_volume_std_20(df):
    """Volume stability"""
    return df.groupby('stock_code')['volume'].transform(lambda x: x.rolling(20).std() / x.rolling(20).mean())

def alpha_price_volume_corr(df):
    """Correlation between return and volume"""
    def rolling_corr(x):
        return x['pct_chg'].rolling(10).corr(x['volume'])
    return df.groupby('stock_code', group_keys=False).apply(rolling_corr)

def alpha_range_pos(df):
    """Where close sits in the High-Low range of the day"""
    return (df['close'] - df['low']) / (df['high'] - df['low']).replace(0, 1e-6)
