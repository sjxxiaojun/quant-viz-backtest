import pandas as pd
import numpy as np
import os

def run_power_energy_strategy(lake_dir="/Users/gdxj/quant_data_lake"):
    """
    Executes the Power & Energy Sector Strategy backtest.
    Returns a dictionary with regime, metrics, and top_stocks.
    """
    stock_list = [
        "300750", "300274", "002594", "300014", "605117", "002335", # 储能
        "600900", "600011", "601985", "000539",                   # 电力运营商
        "600406", "600089", "600312", "000400", "002028"          # 电力设备
    ]
    
    all_data = []
    for symbol in stock_list:
        file_path = os.path.join(lake_dir, f"{symbol}_full_history.parquet")
        if os.path.exists(file_path):
            df = pd.read_parquet(file_path)
            df['symbol'] = symbol
            all_data.append(df)
            
    if not all_data:
        return {"error": "No data found in the lake for the selected symbols."}
        
    df = pd.concat(all_data)
    df['date'] = pd.to_datetime(df['date'])
    
    # Filter for 2025-2026 data
    df = df[df['date'] >= '2025-01-01'].sort_values(['symbol', 'date']).reset_index(drop=True)
    
    if df.empty:
        return {"error": "No data available for the specified period (2025+)."}
    
    # Compute factors (Vectorized)
    df['f_pb_inv'] = 1.0 / (pd.to_numeric(df['pb'], errors='coerce') + 1e-10)
    df['f_vol_20'] = df.groupby('symbol')['pct_chg'].rolling(20).std().reset_index(level=0, drop=True)
    df['f_rev_5'] = -df.groupby('symbol')['close'].pct_change(5).shift(1).reset_index(level=0, drop=True)
    
    ma20 = df.groupby('symbol')['close'].rolling(20).mean().reset_index(level=0, drop=True)
    std20 = df.groupby('symbol')['close'].rolling(20).std().reset_index(level=0, drop=True)
    df['f_boll_pos'] = (df['close'] - ma20) / (2 * std20 + 1e-10)
    
    df['target_ret_5'] = df.groupby('symbol')['close'].shift(-5).reset_index(level=0, drop=True) / df['close'] - 1
    
    # Drop rows with NaN in required columns except target_ret_5 for the latest dates
    factor_cols = ['f_pb_inv', 'f_vol_20', 'f_rev_5', 'f_boll_pos']
    df = df.dropna(subset=factor_cols).reset_index(drop=True)
    
    if df.empty:
         return {"error": "Insufficient valid data after computing factors."}

    # Factor Z-Score (Vectorized)
    for f in factor_cols:
        mean_f = df.groupby('date')[f].transform('mean')
        std_f = df.groupby('date')[f].transform('std')
        df[f'{f}_z'] = ((df[f] - mean_f) / std_f).fillna(0)
        
    # Composite Score
    df['composite_score'] = df['f_pb_inv_z'] + df['f_vol_20_z'] - df['f_boll_pos_z'] + df['f_rev_5_z']
    
    # Quantiles
    def safe_qcut(x):
        try:
            return pd.qcut(x, 3, labels=False, duplicates='drop')
        except:
            return np.nan
            
    df['quantile'] = df.groupby('date')['composite_score'].transform(safe_qcut)
    
    # Calculate Metrics
    df_metrics = df.dropna(subset=['target_ret_5', 'quantile'])
    
    if df_metrics.empty:
        return {"error": "No valid forward returns for backtesting metrics."}
        
    daily_rets = df_metrics.groupby(['date', 'quantile'])['target_ret_5'].mean().unstack()
    daily_rets = daily_rets.fillna(0)
    
    if 2 not in daily_rets.columns:
        return {"error": "Backtest failed to create top quantile."}
        
    top_ret = daily_rets[2]
    ann_ret = float(top_ret.mean() * 50)
    sharpe = float((top_ret.mean() / top_ret.std() * np.sqrt(50))) if top_ret.std() > 0 else 0.0
    cum_ret = (1 + top_ret).cumprod()
    mdd = float((cum_ret / cum_ret.cummax() - 1).min())
    
    # Get top stocks for the most recent date
    latest_date = df['date'].max()
    latest_df = df[df['date'] == latest_date]
    top_stocks = []
    if not latest_df.empty:
        top_stocks_df = latest_df.sort_values('composite_score', ascending=False).head(3)
        for _, row in top_stocks_df.iterrows():
            name = row.get('stock_name', row['symbol'])
            top_stocks.append({"code": row['symbol'], "name": name})
        
    return {
        "regime": "Trending",
        "metrics": {
            "annual_return": ann_ret,
            "sharpe": sharpe,
            "max_drawdown": mdd
        },
        "top_stocks": top_stocks
    }

def calculate_power_energy_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Standard signal generation function for the BacktestEngine.
    Expects df with standard columns (date, stock_code, close, pct_chg, pb)
    """
    df = df.copy()
    df = df.sort_values(['stock_code', 'date']).reset_index(drop=True)
    
    # 1. 价值因子: 1/PB
    df['f_pb_inv'] = 1.0 / (pd.to_numeric(df['pb'], errors='coerce') + 1e-10)
    
    # 2. 波性因子: 20日滚动波动率 (Vectorized)
    df['f_vol_20'] = df.groupby('stock_code')['pct_chg'].rolling(20).std().reset_index(level=0, drop=True)
    
    # 3. 反转因子: 5日涨跌幅取反 (Vectorized)
    df['f_rev_5'] = -df.groupby('stock_code')['close'].pct_change(5).shift(1).reset_index(level=0, drop=True)
    
    # 4. 回归因子: 距离布林带中轨的位置 (Vectorized)
    ma20 = df.groupby('stock_code')['close'].rolling(20).mean().reset_index(level=0, drop=True)
    std20 = df.groupby('stock_code')['close'].rolling(20).std().reset_index(level=0, drop=True)
    df['f_boll_pos'] = (df['close'] - ma20) / (2 * std20 + 1e-10)
    
    # 截面标准化 (Vectorized)
    for f in ['f_pb_inv', 'f_vol_20', 'f_rev_5', 'f_boll_pos']:
        mean_f = df.groupby('date')[f].transform('mean')
        std_f = df.groupby('date')[f].transform('std')
        df[f'{f}_z'] = ((df[f] - mean_f) / std_f).fillna(0)
        
    # 合成得分
    df['score'] = df['f_pb_inv_z'] + df['f_vol_20_z'] - df['f_boll_pos_z'] + df['f_rev_5_z']
    df['signal'] = 1
    return df


