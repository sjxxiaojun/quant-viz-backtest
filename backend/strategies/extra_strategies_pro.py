import pandas as pd
import numpy as np


def calculate_ai_ml_signals_pro(df: pd.DataFrame) -> pd.DataFrame:
    """
    防御多因子 Pro (Defense Factor Pro):
    低波动 + 价值 + 质量 + 流动性过滤。
    修复：PE/PB 为0时（ETF）自动降权该因子。
    """
    df = df.sort_values(['stock_code', 'date']).copy()
    def _calc_pro_plus_features(g):
        g = g.copy()
        g['f_low_vol'] = -g['close'].pct_change().rolling(20).std()
        # [FIX] PE/PB 为0时不贡献价值因子
        g['f_value'] = np.where(g['pb'] > 0.01, 1.0 / g['pb'], 0.0) + \
                       np.where(g['pe'] > 0.01, 1.0 / g['pe'], 0.0)
        # 质量因子：价格稳定性（Sharpe 代理）
        g['f_quality'] = g['close'].rolling(60).mean() / (g['close'].rolling(60).std() + 1e-9)
        # 流动性
        g['f_liquidity'] = g['amount'].rolling(5).mean() if 'amount' in g.columns else g['volume'].rolling(5).mean()
        return g
    try:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_pro_plus_features)
    except Exception:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_pro_plus_features)
    for f in ['f_low_vol', 'f_value', 'f_quality']:
        df[f'{f}_z'] = df.groupby('date')[f].transform(lambda x: (x - x.mean()) / (x.std() + 1e-9))
    df['score'] = df['f_low_vol_z'] * 0.4 + df['f_value_z'] * 0.3 + df['f_quality_z'] * 0.3
    # 流动性剔除：剔除成交额后 20% 的个股
    df.loc[
        df['f_liquidity'] < df.groupby('date')['f_liquidity'].transform(lambda x: x.quantile(0.2)),
        'score'
    ] = -999
    def _apply_pro_ranking(day_g):
        day_g = day_g.copy()
        day_g['signal'] = 0
        if len(day_g) < 2: return day_g
        top_idx = day_g[day_g['score'] > 0.5].nlargest(2, 'score').index
        day_g.loc[top_idx, 'signal'] = 1
        day_g.loc[day_g.nsmallest(2, 'score').index, 'signal'] = -1
        return day_g
    try:
        return df.groupby('date', group_keys=False).apply(_apply_pro_ranking)
    except Exception:
        return df.groupby('date', group_keys=False).apply(_apply_pro_ranking)


def calculate_ai_adaptive_signals_pro(df: pd.DataFrame) -> pd.DataFrame:
    """
    市场环境切换策略 Pro (Regime Switching Pro):
    引入大盘趋势作为全局切换开关，消除前视偏差。
    修复：regime 计算改为滚动方式，不使用全局统计量。
    """
    df = df.sort_values(['stock_code', 'date']).copy()

    # [FIX] 全部使用滚动计算，不再有全局平均
    mkt_ret = df.groupby('date')['pct_chg'].mean()
    mkt_trend = mkt_ret.rolling(20).sum()
    mkt_vol = df.groupby('date')['pct_chg'].apply(lambda x: x.abs().mean())
    mkt_vol_ma = mkt_vol.rolling(60).mean()  # 60日滚动均值（不是全局均值）

    # Regime: 0 (低波趋势), 1 (高波震荡), 2 (单边下行)
    regime = pd.Series(0, index=mkt_ret.index)
    # [FIX] 用滚动均值比较，而非全局均值
    regime[mkt_vol > mkt_vol_ma] = 1
    regime[mkt_trend < -0.05] = 2

    regime_df = pd.DataFrame({'date': mkt_ret.index, 'regime': regime.values})
    df = df.merge(regime_df, on='date', how='left')
    df['regime'] = df['regime'].fillna(0)

    def _calc_dual_factors(g):
        g = g.copy()
        g['f_trend'] = g['close'].pct_change(60)
        # shift(1) 确保反转因子不包含当日数据
        g['f_swing'] = -g['close'].pct_change(5).shift(1)
        return g
    try:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_dual_factors)
    except Exception:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_dual_factors)

    # 下行周期强制空仓 (score = -999)
    df['score'] = np.where(df['regime'] == 0, df['f_trend'],
                           np.where(df['regime'] == 1, df['f_swing'], -999))

    def _apply_ranking(day_g):
        day_g = day_g.copy()
        day_g['signal'] = 0
        if len(day_g) < 2: return day_g
        day_g.loc[day_g.nlargest(2, 'score').index, 'signal'] = 1
        day_g.loc[day_g.nsmallest(2, 'score').index, 'signal'] = -1
        return day_g
    try:
        return df.groupby('date', group_keys=False).apply(_apply_ranking)
    except Exception:
        return df.groupby('date', group_keys=False).apply(_apply_ranking)


def calculate_blackhorse_signals_pro(df: pd.DataFrame) -> pd.DataFrame:
    """
    动量猎手 Pro (Blackhorse Hunter Pro):
    量价背离识别，专抓"黄金坑"缩量回调后的启动。
    """
    df = df.sort_values(['stock_code', 'date']).copy()
    def _calc_smart_features(g):
        g = g.copy()
        g['f_accel'] = g['close'].pct_change(5) - g['close'].shift(5).pct_change(5)
        # 黄金坑：价格在均线上方但量能萎缩（机构控盘洗筹特征）
        g['f_pit'] = (g['close'] > g['close'].rolling(20).mean()) & \
                     (g['volume'] < g['volume'].rolling(20).mean() * 0.8)
        # 聪明钱：涨幅方向 × 成交量相对强度
        g['f_smart'] = np.sign(g['pct_chg']) * (g['volume'] / (g['volume'].rolling(20).mean() + 1e-9))
        return g
    try:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_smart_features)
    except Exception:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_smart_features)
    for f in ['f_accel', 'f_smart']:
        df[f'{f}_z'] = df.groupby('date')[f].transform(lambda x: (x - x.mean()) / (x.std() + 1e-9))
    df['score'] = df['f_accel_z'] * 0.4 + df['f_smart_z'] * 0.4 + df['f_pit'].fillna(False).astype(int) * 0.2
    def _apply_ranking(day_g):
        day_g = day_g.copy()
        day_g['signal'] = 0
        if len(day_g) < 2: return day_g
        top_idx = day_g[day_g['score'] > 1.2].nlargest(1, 'score').index
        day_g.loc[top_idx, 'signal'] = 1
        day_g.loc[day_g['score'] < 0, 'signal'] = -1
        return day_g
    try:
        return df.groupby('date', group_keys=False).apply(_apply_ranking)
    except Exception:
        return df.groupby('date', group_keys=False).apply(_apply_ranking)


def calculate_aph_pro_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    尾盘突破猎手 (APH Pro):
    基于"尾盘放量突破昨日高点"的极端信号，T+1 策略。
    """
    df = df.sort_values(['stock_code', 'date']).copy()
    def _calc_hf_plus(g):
        g = g.copy()
        # 1. 收盘突破昨日高点且放量 1.5 倍
        g['f_break'] = (g['close'] > g['high'].shift(1)) & \
                       (g['volume'] > g['volume'].shift(1) * 1.5)
        # 2. 近 10 日平均隔夜溢价（历史经验）
        g['f_gap_hist'] = (g['open'] / g['close'].shift(1) - 1).rolling(10).mean()
        # 3. 日内振幅过滤（振幅过大说明分歧剧烈，风险高）
        g['f_stable'] = (g['high'] - g['low']) / (g['close'] + 1e-9) < 0.05
        return g
    try:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_hf_plus)
    except Exception:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_hf_plus)
    df['signal'] = 0
    buy_mask = (df['f_break'] == True) & (df['f_stable'] == True) & (df['f_gap_hist'] > 0)
    df.loc[buy_mask, 'signal'] = 1
    return df
