import pandas as pd
import numpy as np

def calculate_atm_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate "A-Share Trend & Momentum Filter" signals.
    
    Args:
        df: DataFrame with OHLCV data (date, open, high, low, close, volume)
        
    Returns:
        pd.DataFrame: Original DataFrame with technical indicators and 'signal' column.
        Signal values: 1 (Buy), -1 (Sell), 0 (Hold)
    """
    # 1. Ensure data is sorted by date and stock
    df = df.sort_values(['stock_code', 'date']).copy()
    
    # 2. Calculate indicators per stock
    def _calc_per_stock(g):
        g = g.copy()
        # Moving Averages
        g['ma20'] = g['close'].rolling(window=20).mean()
        g['ma60'] = g['close'].rolling(window=60).mean()
        
        # MACD (12, 26, 9)
        ema12 = g['close'].ewm(span=12, adjust=False).mean()
        ema26 = g['close'].ewm(span=26, adjust=False).mean()
        g['macd_line'] = ema12 - ema26
        g['signal_line'] = g['macd_line'].ewm(span=9, adjust=False).mean()
        
        # RSI (14)
        delta = g['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        # Avoid division by zero
        rs = gain / (loss + 1e-9)
        g['rsi'] = 100 - (100 / (1 + rs))
        
        # Volume Factor
        g['vol_ma5'] = g['volume'].rolling(window=5).mean()
        
        # Initialize signals
        g['signal'] = 0
        
        # Entry conditions
        buy_mask = (
            (g['close'] > g['ma60']) & 
            (g['ma20'] > g['ma60']) &
            (g['macd_line'] > g['signal_line']) &
            (g['rsi'] > 45) & (g['rsi'] < 80) &
            (g['volume'] > g['vol_ma5'] * 1.1)
        )
        
        # Exit conditions
        sell_mask = (
            (g['close'] < g['ma60']) | 
            (g['macd_line'] < g['signal_line']) | 
            (g['rsi'] > 85)
        )
        
        g.loc[buy_mask, 'signal'] = 1
        g.loc[sell_mask, 'signal'] = -1
        return g

    # For newer pandas versions, include_groups=False is recommended. 
    # To maintain compatibility, we check if the parameter exists or just use a standard selection.
    try:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_per_stock)
    except Exception:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_per_stock)
    return df
