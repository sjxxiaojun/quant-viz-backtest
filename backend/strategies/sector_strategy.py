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
    df = df[df['date'] >= '2025-01-01'].sort_values(['symbol', 'date'])
    
    if df.empty:
        return {"error": "No data available for the specified period (2025+)."}
    
    # Compute factors
    def compute_factors(group):
        group['f_pb_inv'] = 1.0 / (pd.to_numeric(group['pb'], errors='coerce') + 1e-10)
        group['f_vol_20'] = group['pct_chg'].rolling(20).std()
        group['f_rev_5'] = -group['close'].pct_change(5).shift(1)
        
        ma20 = group['close'].rolling(20).mean()
        std20 = group['close'].rolling(20).std()
        group['f_boll_pos'] = (group['close'] - ma20) / (2 * std20 + 1e-10)
        
        group['target_ret_5'] = group['close'].shift(-5) / group['close'] - 1
        return group
        
    df = df.groupby('symbol', group_keys=False).apply(compute_factors)
    # Drop rows with NaN in required columns except target_ret_5 for the latest dates
    # But for z-score we need the factors to be valid
    factor_cols = ['f_pb_inv', 'f_vol_20', 'f_rev_5', 'f_boll_pos']
    df = df.dropna(subset=factor_cols)
    
    if df.empty:
         return {"error": "Insufficient valid data after computing factors."}

    # Factor Z-Score
    for f in factor_cols:
        df[f'{f}_z'] = df.groupby('date')[f].transform(lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0)
        
    # Composite Score
    df['composite_score'] = df['f_pb_inv_z'] + df['f_vol_20_z'] - df['f_boll_pos_z'] + df['f_rev_5_z']
    
    # Quantiles
    def safe_qcut(x):
        try:
            return pd.qcut(x, 3, labels=False, duplicates='drop')
        except:
            return np.nan
            
    df['quantile'] = df.groupby('date')['composite_score'].transform(safe_qcut)
    
    # Calculate Metrics using target_ret_5 which might be NaN for the very last few days
    # so we dropna for target_ret_5 only when computing metrics
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
    # 1. 价值因子: 1/PB
    df['f_pb_inv'] = 1.0 / (pd.to_numeric(df['pb'], errors='coerce') + 1e-10)
    
    # 2. 波性因子: 20日滚动波动率
    df['f_vol_20'] = df.groupby('stock_code')['pct_chg'].transform(lambda x: x.rolling(20).std())
    
    # 3. 反转因子: 5日涨跌幅取反
    df['f_rev_5'] = -df.groupby('stock_code')['close'].transform(lambda x: x.pct_change(5).shift(1))
    
    # 4. 回归因子: 距离布林带中轨的位置
    def calc_boll(x):
        ma20 = x.rolling(20).mean()
        std20 = x.rolling(20).std()
        return (x - ma20) / (2 * std20 + 1e-10)
        
    df['f_boll_pos'] = df.groupby('stock_code')['close'].transform(calc_boll)
    
    # 填充NaN以防z-score失败
    df = df.copy()
    
    # 截面标准化
    for f in ['f_pb_inv', 'f_vol_20', 'f_rev_5', 'f_boll_pos']:
        df[f'{f}_z'] = df.groupby('date')[f].transform(lambda x: (x - x.mean()) / x.std() if x.std() > 0 else 0).fillna(0)
        
    # 合成得分 (同 run_power_energy_strategy)
    df['score'] = df['f_pb_inv_z'] + df['f_vol_20_z'] - df['f_boll_pos_z'] + df['f_rev_5_z']
    df['signal'] = 1
    return df

