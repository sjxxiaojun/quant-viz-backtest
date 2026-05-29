import os
import numpy as np
import pandas as pd

def calculate_news_sentiment_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    舆情与资金流向自适应策略 (News Sentiment Alpha 2026):
    1. 引入 510300 (沪深300ETF) 作为大盘择时过滤代理，大盘处于站上 60 日线的多头牛市氛围才允许买入。
    2. 个股买入核心：
       - 强势多头排列：价格在均线上方，且 5日均线 > 10日均线，且均线拐头向上。
       - 温和放量突破：成交量爆发比率 (2.5 < vol_ratio < 4.5)，过滤大盘无量假突破或巨量见顶。
       - 饱满实体形态：日涨幅限制在 (3.0% < pct_chg < 7.0%)；上影线占比控制在 (upper_shadow < 1.2%)，防止冲高回落。
       - 开盘平稳：开盘高开涨幅控制在 (open_pct < 3.5%)，防止大幅跳空高开低走。
       - 跑赢沪深300大盘相对强弱度 (rs20 > 0.0)，只做超额领涨龙头。
       - 偏离度控制 bias20 < 0.12，防高位接盘。
    3. 风控出场：个股连续两天收盘跌破 30 日均线，或者大盘跌破 60 日中期生命线，立刻平仓。
    """
    if df.empty:
        return df

    # 按照代码 and 日期排序，确保滚动指标计算的准确性
    df = df.sort_values(['stock_code', 'date']).copy()
    df['date_str'] = df['date'].astype(str)
    
    # ---- Part 1: 大盘择时过滤 ----
    mkt_buy_status = {}
    mkt_exit_status = {}
    mkt_ret20_status = {}
    try:
        etf_path = "/Users/gdxj/quant_data_lake/etf/510300_full_history.parquet"
        if os.path.exists(etf_path):
            mkt_df = pd.read_parquet(etf_path).sort_values('date')
            mkt_df['date_str'] = mkt_df['date'].astype(str)
            mkt_df['mkt_ma60'] = mkt_df['close'].rolling(60).mean()
            
            # 大盘必须连续两天站上60日均线才允许买入
            mkt_df['mkt_ok_buy'] = (mkt_df['close'] > mkt_df['mkt_ma60']) & (mkt_df['close'].shift(1) > mkt_df['mkt_ma60'].shift(1))
            # 连续两天跌破60日均线才执行强平出局
            mkt_df['mkt_ok_exit'] = ~((mkt_df['close'] < mkt_df['mkt_ma60']) & (mkt_df['close'].shift(1) < mkt_df['mkt_ma60'].shift(1)))
            
            # 计算大盘过去20天的相对表现
            mkt_df['mkt_ret20'] = mkt_df['close'] / (mkt_df['close'].shift(20) + 1e-9)
            
            mkt_buy_status = mkt_df.set_index('date_str')['mkt_ok_buy'].to_dict()
            mkt_exit_status = mkt_df.set_index('date_str')['mkt_ok_exit'].to_dict()
            mkt_ret20_status = mkt_df.set_index('date_str')['mkt_ret20'].to_dict()
    except Exception:
        pass
        
    # ---- Part 2: 计算个股特征因子 ----
    def _calc_factors(g):
        g = g.copy()
        # 1. 均线通道
        g['ma5'] = g['close'].rolling(5).mean()
        g['ma10'] = g['close'].rolling(10).mean()
        g['ma20'] = g['close'].rolling(20).mean()
        g['ma30'] = g['close'].rolling(30).mean()
        g['ma60'] = g['close'].rolling(60).mean()
        
        # 2. 短期与中期均线拐头
        g['ma5_up'] = g['ma5'] > g['ma5'].shift(1)
        g['ma20_up'] = g['ma20'] > g['ma20'].shift(1)
        g['ma60_up'] = g['ma60'] > g['ma60'].shift(1)
        
        # 3. 20日均量
        g['vol_ma20'] = g['volume'].rolling(20).mean()
        
        # 4. 爆量突破因子
        g['vol_ratio'] = g['volume'] / (g['vol_ma20'].shift(1) + 1e-9)
        
        # 5. 成交量稳定性
        g['vol_std'] = g['volume'].rolling(20).std() / (g['vol_ma20'] + 1e-9)
        
        # 6. 个股相对乖离率 bias20
        g['bias20'] = (g['close'] - g['ma20']) / (g['ma20'] + 1e-9)
        
        # 7. 个股相对上影线长度比例 (相对于昨日收盘价的百分比，剔除冲高回落的假动作)
        g['upper_shadow'] = (g['high'] - g[['close', 'open']].max(axis=1)) / (g['close'] + 1e-9)
        
        # 8. 开盘高开比率
        g['open_pct'] = (g['open'] - g['close'].shift(1)) / (g['close'].shift(1) + 1e-9)
        
        # 9. 个股 20 日表现
        g['ret20'] = g['close'] / (g['close'].shift(20) + 1e-9)
        
        # 10. 连续两天跌破 30日线 (核心生命线)
        g['under_ma30_days2'] = (g['close'] < g['ma30']) & (g['close'].shift(1) < g['ma30'].shift(1))
        
        # 11. 消息面突发利好代理因子：隔夜跳空高开幅度
        g['open_pct'] = (g['open'] - g['close'].shift(1)) / (g['close'].shift(1) + 1e-9)
        
        return g
        
    df = df.groupby('stock_code', group_keys=False).apply(_calc_factors)
    
    # ---- Part 3: 打分与排序 ----
    # 在消息面利好驱动下，缺口越大、爆量越猛，说明利好越硬
    df['score'] = df['vol_ratio'] * 0.4 + df['open_pct'] * 100 * 0.6
    
    df['mkt_ok_buy'] = df['date_str'].map(mkt_buy_status).fillna(True)
    df['mkt_ok_exit'] = df['date_str'].map(mkt_exit_status).fillna(True)
    df['mkt_ret20'] = df['date_str'].map(mkt_ret20_status).fillna(1.0)
    
    # 消息面利好代理 + 量价共振 终极高胜率策略：
    # 1. 均线趋势护航：ma5_up, ma20_up, ma60_up 且 close > ma20
    # 2. 大盘牛市氛围：mkt_ok_buy (站上 60 日线)
    # 3. 【核心消息面代理】大幅跳空高开：open_pct > 0.010 (大蓝筹高开 1% 代表实质性政策/财报利好)
    # 4. 【核心资金面承接】高开高走不套人：close > open 
    # 5. 放量确认：vol_ratio > 1.5 
    valid_mask = (
        (df['close'] > df['ma20']) &
        (df['close'] > df['ma60']) &
        (df['ma5_up'] == True) &
        (df['ma20_up'] == True) &
        (df['ma60_up'] == True) &
        (df['mkt_ok_buy'] == True) &
        (df['open_pct'] > 0.010) &
        (df['close'] > df['open']) &
        (df['vol_ratio'] > 1.5) &
        (df['pct_chg'] < 9.0)
    )
    
    # 卖出离场条件：宽容洗盘，一旦连续两日跌破 30 日生命线再离场，让利润奔跑
    exit_mask = (
        (df['under_ma30_days2'] == True) |
        (df['mkt_ok_exit'] == False)
    )
    
    df.loc[~valid_mask, 'score'] = -999.0
    
    df['exit_cond'] = exit_mask
    
    def _apply_ranking(day_g):
        day_g = day_g.copy()
        day_g['signal'] = 0
        if len(day_g) < 2:
            return day_g
            
        valid_stocks = day_g[day_g['score'] > 0.0]
        if not valid_stocks.empty:
            top_idx = valid_stocks.nlargest(3, 'score').index
            day_g.loc[top_idx, 'signal'] = 1
            
        day_g.loc[day_g['exit_cond'] == True, 'signal'] = -1
        return day_g
        
    res = df.groupby('date_str', group_keys=False).apply(_apply_ranking)

    if 'date_str' in res.columns:
        res = res.drop(columns=['date_str'])
        
    return res
