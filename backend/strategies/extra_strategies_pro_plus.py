import pandas as pd
import numpy as np


# 市场三态编码：REGIME_CALM 平静市 / REGIME_TREND 趋势市 / REGIME_CHOPPY 高波震荡市
REGIME_CALM = 0
REGIME_TREND = 1
REGIME_CHOPPY = 2


def calculate_ai_adaptive_signals_pro_plus(df: pd.DataFrame) -> pd.DataFrame:
    """
    市场环境切换原味版 (Adaptive Dual Mode):
    三态市场划分：趋势市（|20日累计涨幅|>5%，可与高波共存，趋势优先）用动量因子；
    高波无趋势的震荡市用反转因子；平静市（低波无趋势）沿用反转因子。
    regime 的 mkt_std 阈值用 expanding 均值，不使用全局统计量（避免前视）。
    """
    df = df.sort_values(['stock_code', 'date']).copy()

    mkt_stats = df.groupby('date').agg({'pct_chg': 'mean', 'volume': 'sum'})
    mkt_stats['mkt_trend'] = mkt_stats['pct_chg'].rolling(20).sum()
    mkt_stats['mkt_std'] = mkt_stats['pct_chg'].rolling(20).std()
    mkt_stats['mkt_std_ma'] = mkt_stats['mkt_std'].expanding(min_periods=20).mean()

    # 三态划分：先标高波震荡，再标趋势（有方向的行情即使高波也按趋势市处理）
    mkt_stats['regime'] = REGIME_CALM
    mkt_stats.loc[mkt_stats['mkt_std'] > mkt_stats['mkt_std_ma'], 'regime'] = REGIME_CHOPPY
    mkt_stats.loc[mkt_stats['mkt_trend'].abs() > 0.05, 'regime'] = REGIME_TREND

    df = df.merge(mkt_stats[['regime']], on='date', how='left')
    df['regime'] = df['regime'].fillna(REGIME_CALM)

    def _calc_factors(g):
        g = g.copy()
        g['f_trend'] = g['close'].pct_change(20).shift(1)
        g['f_swing'] = -g['close'].pct_change(5).shift(1)
        return g
    df = df.groupby('stock_code', group_keys=False).apply(_calc_factors)

    for f in ['f_trend', 'f_swing']:
        df[f'{f}_z'] = df.groupby('date')[f].transform(lambda x: (x - x.mean()) / (x.std() + 1e-9))

    # 趋势市 -> 动量因子；震荡市/平静市 -> 反转因子
    df['score'] = np.where(df['regime'] == REGIME_TREND, df['f_trend_z'], df['f_swing_z'])
    
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
