import pandas as pd
import numpy as np

def calculate_blackhorse_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    前锋·动量捕手 (Blackhorse):
    专抓高弹性中小盘。逻辑：价格突破 + 动量加速度 + 成交量异常放大。
    """
    df = df.sort_values(['stock_code', 'date']).copy()
    
    def _calc(g):
        g = g.copy()
        # 1. 价格动量加速度 (前视安全：用shift确保信号基于昨日数据)
        g['roc'] = g['close'].pct_change(5)
        g['accel'] = g['roc'].diff()
        
        # 2. 20日均线
        g['ma20'] = g['close'].rolling(20).mean()
        
        # 3. 成交量异动（用shift(1)确保量比是基于昨日均量）
        g['vol_ratio'] = g['volume'] / (g['volume'].rolling(10).mean().shift(1) + 1e-9)
        
        g['signal'] = 0
        buy_mask = (g['accel'] > 0) & (g['close'] > g['ma20']) & (g['vol_ratio'] > 2.0)
        ma5 = g['close'].rolling(5).mean()
        sell_mask = (g['accel'] < -0.05) | (g['close'] < ma5)
        
        g.loc[buy_mask, 'signal'] = 1
        g.loc[sell_mask, 'signal'] = -1
        return g

    return df.groupby('stock_code', group_keys=False).apply(_calc)


def calculate_ai_adaptive_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    自适应双模策略 (Adaptive):
    基于滚动波动率自动切换趋势/反转模式。
    修复：avg_vol 改用 expanding().mean() 消除前视偏差。
    """
    df = df.sort_values(['stock_code', 'date']).copy()
    
    def _calc(g):
        g = g.copy()
        # 计算短期波动率
        vol = g['close'].pct_change().rolling(10).std()
        # [FIX] 改用 expanding().mean() 代替 vol.mean()，消除前视偏差
        avg_vol = vol.expanding(min_periods=10).mean()
        
        ma20 = g['close'].rolling(20).mean()
        
        # RSI6
        delta = g['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(6).mean()
        loss = delta.abs().where(delta < 0, 0).rolling(6).mean()
        rsi = gain / (gain + loss + 1e-9) * 100
        
        g['signal'] = 0
        # 低波市：跟趋势（vol < 当前点的历史均值）
        trend_buy = (g['close'] > ma20) & (vol < avg_vol)
        # 高波市：抢超卖反弹
        revert_buy = (rsi < 25) & (vol >= avg_vol)
        
        g.loc[trend_buy | revert_buy, 'signal'] = 1
        g.loc[(rsi > 80) | (g['close'] < ma20 * 0.95), 'signal'] = -1
        return g

    return df.groupby('stock_code', group_keys=False).apply(_calc)


def calculate_reversal_vol_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    超跌反转 Pro:
    1. 5日跌幅反转 + 成交量放大
    2. 增加【成交量稳定性】过滤：避开成交量极度不稳的标的 (Marathon Mined: vol_std_20 < 0)
    """
    df = df.sort_values(['stock_code', 'date']).copy()
    def _calc_per_stock(g):
        g = g.copy()
        g['ret5'] = g['close'].pct_change(5)
        g['reversal'] = -g['ret5'].shift(1)
        
        # 成交量爆发
        g['vol_ma20'] = g['volume'].rolling(20).mean()
        g['vol_spike'] = g['volume'] / (g['vol_ma20'].shift(1) + 1e-9)
        
        # 成交量稳定性 (Marathon Mining 发现的重要反向指标)
        # 高 vol_std 代表不稳，我们要低 vol_std 的
        g['vol_std'] = g['volume'].rolling(20).std() / (g['volume'].rolling(20).mean() + 1e-9)
        
        g['signal'] = 0
        # 买入条件：反转信号 + 爆量 + 成交量相对平稳 (vol_std 低于均值 1.0)
        buy_mask = (g['reversal'] > 0.02) & (g['vol_spike'] > 1.5) & (g['vol_std'] < 1.0)
        sell_mask = (g['ret5'] > 0.05)
        g.loc[buy_mask, 'signal'] = 1
        g.loc[sell_mask, 'signal'] = -1
        return g
    return df.groupby('stock_code', group_keys=False).apply(_calc_per_stock)


def calculate_turtle_signals(df: pd.DataFrame) -> pd.DataFrame:
    """海龟法则：唐奇安通道突破。"""
    df = df.sort_values(['stock_code', 'date']).copy()
    def _calc_per_stock(g):
        g = g.copy()
        # shift(1) 确保用昨日高点，避免当日收盘 vs 当日高点的偏差
        g['h5'] = g['high'].rolling(5).max().shift(1)
        g['l2'] = g['low'].rolling(2).min().shift(1)
        g['signal'] = 0
        g.loc[g['close'] > g['h5'], 'signal'] = 1
        g.loc[g['close'] < g['l2'], 'signal'] = -1
        return g
    return df.groupby('stock_code', group_keys=False).apply(_calc_per_stock)


def calculate_hfmr_signals(df: pd.DataFrame) -> pd.DataFrame:
    """高频均值回归：RSI6 超卖 + 布林带下轨。"""
    df = df.sort_values(['stock_code', 'date']).copy()
    def _calc_per_stock(g):
        g = g.copy()
        delta = g['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(6).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(6).mean()
        g['rsi6'] = 100 - (100 / (1 + gain / (loss + 1e-9)))
        g['lower_bb'] = g['close'].rolling(10).mean() - 1.5 * g['close'].rolling(10).std()
        g['signal'] = 0
        g.loc[(g['rsi6'] < 30) & (g['close'] < g['lower_bb']), 'signal'] = 1
        g.loc[(g['rsi6'] > 70), 'signal'] = -1
        return g
    return df.groupby('stock_code', group_keys=False).apply(_calc_per_stock)


def calculate_sector_alpha_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    行业截面多因子 (Alpha):
    Z-Score 截面评分，不依赖 PE/PB（防止 ETF 失效）。
    """
    df = df.sort_values(['stock_code', 'date']).copy()
    def _calc_raw_factors(g):
        g = g.copy()
        # 价值因子：只在 pb>0 时有效，否则置0
        g['f_val'] = np.where(g['pb'] > 0.01, 1.0 / g['pb'], 0.0)
        g['f_vol'] = g['close'].pct_change().rolling(20).std()
        ma20 = g['close'].rolling(20).mean()
        std20 = g['close'].rolling(20).std()
        g['f_boll'] = (g['close'] - ma20) / (2 * std20 + 1e-9)
        g['f_rev'] = -g['close'].pct_change(5).shift(1)
        return g
    try:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_raw_factors)
    except Exception:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_raw_factors)
    for f in ['f_val', 'f_vol', 'f_boll', 'f_rev']:
        df[f'{f}_z'] = df.groupby('date')[f].transform(lambda x: (x - x.mean()) / (x.std() + 1e-9))
    df['score'] = df['f_val_z'] + df['f_vol_z'] - df['f_boll_z'] + df['f_rev_z']
    def _apply_ranking(day_g):
        day_g = day_g.copy()
        day_g['signal'] = 0
        if len(day_g) < 3: return day_g
        day_g.loc[day_g.nlargest(3, 'score').index, 'signal'] = 1
        day_g.loc[day_g.nsmallest(3, 'score').index, 'signal'] = -1
        return day_g
    return df.groupby('date', group_keys=False).apply(_apply_ranking)


def calculate_ai_ml_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    低波价值因子模型 (Multi-Factor):
    多因子加权评分，权重来自因子有效性分析：低波(42%) + 价值(22%) + 活跃度(8%)。
    注：不依赖 PE/PB 为0 的标的（ETF 自动降权该因子）。
    """
    df = df.sort_values(['stock_code', 'date']).copy()
    def _calc_ml_proxies(g):
        g = g.copy()
        g['f_vol'] = -g['close'].pct_change().rolling(20).std()
        # 价值因子：PE/PB 均为0（如ETF）时该项贡献为0
        g['f_val'] = np.where(g['pe'] > 0.01, 1.0 / g['pe'], 0.0) + \
                     np.where(g['pb'] > 0.01, 1.0 / g['pb'], 0.0)
        g['f_turn'] = g['volume'].rolling(5).mean()
        return g
    try:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_ml_proxies)
    except Exception:
        df = df.groupby('stock_code', group_keys=False).apply(_calc_ml_proxies)
    for f in ['f_vol', 'f_val', 'f_turn']:
        df[f'{f}_z'] = df.groupby('date')[f].transform(lambda x: (x - x.mean()) / (x.std() + 1e-9))
    df['score'] = df['f_vol_z'] * 0.42 + df['f_val_z'] * 0.22 + df['f_turn_z'] * 0.08
    def _apply_ranking(day_g):
        day_g = day_g.copy()
        day_g['signal'] = 0
        if len(day_g) < 2: return day_g
        day_g.loc[day_g.nlargest(2, 'score').index, 'signal'] = 1
        day_g.loc[day_g.nsmallest(2, 'score').index, 'signal'] = -1
        return day_g
    return df.groupby('date', group_keys=False).apply(_apply_ranking)


def calculate_etf_bottom_signals(df: pd.DataFrame, mode="aggressive") -> pd.DataFrame:
    """
    ETF 抄底模型:
    专为 ETF 设计，剔除 PE/PB 因子，改用纯技术因子（波动率 + 布林偏离 + RSI）。
    """
    df = df.sort_values(['stock_code', 'date']).copy()

    grouped_close = df.groupby('stock_code', sort=False)['close']
    pct_change = grouped_close.pct_change()
    df['f_vol'] = -pct_change.groupby(df['stock_code'], sort=False).transform(lambda x: x.rolling(20).std())

    ma20 = grouped_close.transform(lambda x: x.rolling(20).mean())
    std20 = grouped_close.transform(lambda x: x.rolling(20).std())
    df['bb_lower'] = ma20 - 2 * std20
    df['f_stretch'] = (df['bb_lower'] - df['close']) / (df['close'] + 1e-9)

    delta = grouped_close.diff()
    gain = delta.where(delta > 0, 0).groupby(df['stock_code'], sort=False).transform(lambda x: x.rolling(6).mean())
    loss = (-delta.where(delta < 0, 0)).groupby(df['stock_code'], sort=False).transform(lambda x: x.rolling(6).mean())
    df['rsi'] = 100 - (100 / (1 + gain / (loss + 1e-9)))
    df['f_momentum'] = -grouped_close.pct_change(20)

    for f in ['f_vol', 'f_stretch', 'f_momentum']:
        by_date = df.groupby('date', sort=False)[f]
        df[f'{f}_z'] = (df[f] - by_date.transform('mean')) / (by_date.transform('std') + 1e-9)

    # 纯技术因子权重：波动率(42%) + 偏离度(36%) + 反动量(22%)
    df['prob_score'] = df['f_vol_z'] * 0.42 + df['f_stretch_z'] * 0.36 + df['f_momentum_z'] * 0.22
    threshold = 0.8 if mode == "aggressive" else 1.3
    df['signal'] = 0
    buy_mask = (df['prob_score'] > threshold) & (df['rsi'] < 35)
    sell_mask = (df['rsi'] > 75) | (df['prob_score'] < -0.5)
    df.loc[buy_mask, 'signal'] = 1
    df.loc[sell_mask, 'signal'] = -1
    return df
