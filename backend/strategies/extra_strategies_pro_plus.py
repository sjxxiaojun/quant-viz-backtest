import pandas as pd
import numpy as np


def calculate_ai_adaptive_signals_pro_plus(df: pd.DataFrame) -> pd.DataFrame:
    """
    市场环境切换原味版 (Adaptive Dual Mode):
    趋势市用动量，震荡市用反转。
    修复：regime 的 mkt_std 阈值改用滚动均值，消除前视偏差。
    """
    df = df.sort_values(['stock_code', 'date']).copy()
    
    mkt_stats = df.groupby('date').agg({'pct_chg': 'mean', 'volume': 'sum'})
    mkt_stats['mkt_trend'] = mkt_stats['pct_chg'].rolling(20).sum()
    mkt_stats['mkt_std'] = mkt_stats['pct_chg'].rolling(20).std()
    # [FIX] 用 expanding().mean() 取代全局 mkt_std.mean()，消除前视偏差
    mkt_stats['mkt_std_ma'] = mkt_stats['mkt_std'].expanding(min_periods=20).mean()
    
    # 0 为趋势，1 为震荡
    mkt_stats['regime'] = 0
    mkt_stats.loc[mkt_stats['mkt_trend'].abs() > 0.05, 'regime'] = 1
    mkt_stats.loc[mkt_stats['mkt_std'] > mkt_stats['mkt_std_ma'], 'regime'] = 1
    
    df = df.merge(mkt_stats[['regime']], on='date', how='left')
    df['regime'] = df['regime'].fillna(0)
    
    def _calc_factors(g):
        g = g.copy()
        g['f_trend'] = g['close'].pct_change(20).shift(1)
        g['f_swing'] = -g['close'].pct_change(5).shift(1)
        return g
    try:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_factors)
    except Exception:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_factors)
    
    for f in ['f_trend', 'f_swing']:
        df[f'{f}_z'] = df.groupby('date')[f].transform(lambda x: (x - x.mean()) / (x.std() + 1e-9))
        
    df['score'] = np.where(df['regime'] == 0, df['f_swing_z'], df['f_trend_z'])
    
    def _apply_ranking(day_g):
        day_g = day_g.copy()
        day_g['signal'] = 0
        if len(day_g) < 2: return day_g
        top_idx = day_g.nlargest(1, 'score').index
        day_g.loc[top_idx, 'signal'] = 1
        # 只对最差的1只发出卖出信号，不要对所有其他股票做空
        bot_idx = day_g.nsmallest(1, 'score').index
        day_g.loc[bot_idx, 'signal'] = -1
        return day_g
        
    return df.groupby('date', group_keys=False).apply(_apply_ranking)


def calculate_blackhorse_signals_pro_plus(df: pd.DataFrame) -> pd.DataFrame:
    """
    动量加速原味版 (Momentum Acceleration Original):
    加速度因子 + 量能突破因子的纯动量策略。
    """
    df = df.sort_values(['stock_code', 'date']).copy()
    def _calc_smart_money(g):
        g = g.copy()
        mom_20 = g['close'].pct_change(20)
        mom_prev = g['close'].shift(20).pct_change(20)
        g['f_accel'] = (mom_20 - mom_prev) / (abs(mom_prev) + 1e-9)
        
        vol_ma = g['volume'].rolling(20).mean()
        g['f_vol_break'] = g['volume'] / (vol_ma.shift(1) + 1e-9)  # shift(1) 消除当日量比自引用
        return g
    try:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_smart_money)
    except Exception:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_smart_money)
    
    for f in ['f_accel', 'f_vol_break']:
        df[f'{f}_z'] = df.groupby('date')[f].transform(lambda x: (x - x.mean()) / (x.std() + 1e-9))
    
    df['score'] = df['f_accel_z'] * 0.4 + df['f_vol_break_z'] * 0.6
    
    def _apply_ranking(day_g):
        day_g = day_g.copy()
        day_g['signal'] = 0
        if len(day_g) < 2: return day_g
        top_idx = day_g.nlargest(1, 'score').index
        day_g.loc[top_idx, 'signal'] = 1
        bot_idx = day_g.nsmallest(1, 'score').index
        day_g.loc[bot_idx, 'signal'] = -1
        return day_g
        
    return df.groupby('date', group_keys=False).apply(_apply_ranking)
