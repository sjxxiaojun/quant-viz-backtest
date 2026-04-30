import pandas as pd
import numpy as np
from typing import List, Callable, Optional, Dict
from dataclasses import dataclass

@dataclass
class FactorConfig:
    name: str
    func: Callable[[pd.DataFrame], pd.Series]
    weight: float

# Standard Library of Factor Calculation Functions
def factor_low_volatility(g: pd.DataFrame, window: int = 20) -> pd.Series:
    """Negative volatility (lower is better)"""
    return -g['close'].pct_change().rolling(window).std()

def factor_value(g: pd.DataFrame) -> pd.Series:
    """1/PE + 1/PB. Returns 0 if PE/PB is 0 or NaN to handle ETFs correctly."""
    pe_inv = np.where(g['pe'] > 0.01, 1.0 / g['pe'], 0.0)
    pb_inv = np.where(g['pb'] > 0.01, 1.0 / g['pb'], 0.0)
    return pd.Series(pe_inv + pb_inv, index=g.index)

def factor_quality(g: pd.DataFrame, window: int = 60) -> pd.Series:
    """Price stability (mean / std)"""
    return g['close'].rolling(window).mean() / (g['close'].rolling(window).std() + 1e-9)

def factor_turnover(g: pd.DataFrame, window: int = 5) -> pd.Series:
    """Turnover or volume moving average"""
    return g['volume'].rolling(window).mean()

def factor_momentum(g: pd.DataFrame, window: int = 20) -> pd.Series:
    """Momentum factor (rate of return)"""
    return g['close'].pct_change(window)

def factor_reversal(g: pd.DataFrame, window: int = 5) -> pd.Series:
    """Reversal factor (negative rate of return)"""
    return -g['close'].pct_change(window).shift(1)

def factor_bollinger_position(g: pd.DataFrame, window: int = 20) -> pd.Series:
    """Bollinger band position: (close - ma) / (2 * std). We want negative for stretching downwards, so we return negative of it."""
    ma = g['close'].rolling(window).mean()
    std = g['close'].rolling(window).std()
    return -(g['close'] - ma) / (2 * std + 1e-9)

def factor_size(g: pd.DataFrame) -> pd.Series:
    """Size factor: Estimated market cap based on amount/turn. Smaller is usually better in A-shares."""
    # turn is in percentage, e.g., 2.5 means 2.5%
    # Estimated Market Cap = amount / (turn/100)
    est_cap = g['amount'] / (g['turn'] / 100.0 + 1e-9)
    return -np.log(est_cap + 1.0)

def factor_volatility_stability(g: pd.DataFrame, window: int = 20) -> pd.Series:
    """Volatility Stability: 1 / (std of returns). Captures low volatility anomaly."""
    vol = g['close'].pct_change().rolling(window).std()
    return 1.0 / (vol + 1e-9)

def factor_volatility_clustering(g: pd.DataFrame, window: int = 20) -> pd.Series:
    """Volatility Clustering: std of volume / mean of volume. Mined in Wave 0."""
    return g['volume'].rolling(window).std() / (g['volume'].rolling(window).mean() + 1e-9)

def factor_short_term_reversal(g: pd.DataFrame) -> pd.Series:
    """1-day reversal. Mined in Wave 0."""
    return -g['close'].pct_change(1)

class MultiFactorStrategy:
    def __init__(
        self,
        factors: List[FactorConfig],
        top_n: int = 2,
        score_threshold: Optional[float] = None,
        liquidity_filter_pct: Optional[float] = None,
    ):
        self.factors = factors
        self.top_n = top_n
        self.score_threshold = score_threshold
        self.liquidity_filter_pct = liquidity_filter_pct

    def calculate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.sort_values(['stock_code', 'date']).copy()
        
        # 1. Calculate factors per stock
        def _calc_raw_factors(g: pd.DataFrame) -> pd.DataFrame:
            g = g.copy()
            for factor in self.factors:
                g[f'f_{factor.name}'] = factor.func(g)
            return g
        
        # In pandas 2.x, include_groups=False removes the grouping column from the chunk.
        # We need it later, so we fallback or ensure it's there.
        try:
            # We don't use include_groups=False here because we need 'date' for the next step
            df = df.groupby('stock_code', group_keys=False).apply(_calc_raw_factors)
        except Exception:
            df = df.groupby('stock_code', group_keys=False).apply(_calc_raw_factors)
        
        # 2. Cross-sectional Z-Score standardization
        factor_names = [f"f_{factor.name}" for factor in self.factors]
        for f in factor_names:
            df[f'{f}_z'] = df.groupby('date')[f].transform(
                lambda x: (x - x.mean()) / (x.std() + 1e-9)
            )
            
        # 3. Weighted scoring
        df['score'] = 0.0
        for factor in self.factors:
            df['score'] += df[f'f_{factor.name}_z'] * factor.weight
            
        # 4. Generate ranking signals
        def _apply_ranking(day_g: pd.DataFrame) -> pd.DataFrame:
            day_g = day_g.copy()
            day_g['signal'] = 0
            
            if len(day_g) < self.top_n:
                return day_g
                
            # Optional liquidity filter
            if self.liquidity_filter_pct is not None:
                vol_threshold = day_g['volume'].quantile(self.liquidity_filter_pct)
                pool = day_g[day_g['volume'] >= vol_threshold]
            else:
                pool = day_g
                
            if len(pool) < self.top_n:
                return day_g

            # Buy signals
            top_stocks = pool.nlargest(self.top_n, 'score')
            if self.score_threshold is not None:
                top_stocks = top_stocks[top_stocks['score'] >= self.score_threshold]
            day_g.loc[top_stocks.index, 'signal'] = 1
            
            # Sell signals
            bottom_stocks = pool.nsmallest(self.top_n, 'score')
            day_g.loc[bottom_stocks.index, 'signal'] = -1
            
            return day_g
            
        try:
            return df.groupby('date', group_keys=False).apply(_apply_ranking)
        except Exception:
            return df.groupby('date', group_keys=False).apply(_apply_ranking)

class RegimeAdaptiveFactorStrategy(MultiFactorStrategy):
    """
    Dynamic weighting based on Market Regime.
    Regime 0: Bull/Trending -> Momentum, SmallCap, Value.
    Regime 1: Shaking/High Vol -> LowVol, Quality, Reversal.
    Regime 2: Bear/Down -> Cash (Low risk).
    """
    def __init__(self, top_n=5, liquidity_filter_pct=0.1):
        super().__init__(factors=[], top_n=top_n, liquidity_filter_pct=liquidity_filter_pct)
    
    def calculate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty: return df
        df = df.sort_values(['stock_code', 'date']).copy()
        
        # 1. Market Regime Detection
        mkt_ret = df.groupby('date')['pct_chg'].mean()
        mkt_trend = mkt_ret.rolling(20).sum()
        # Use transform to keep size same as df
        mkt_vol = df.groupby('date')['pct_chg'].transform(lambda x: x.abs().mean())
        mkt_vol_ma = mkt_vol.rolling(60).mean()
        
        # Map back to date index for mkt_trend
        regime_series = pd.Series(0, index=mkt_ret.index)
        regime_series[mkt_vol.groupby(df['date']).first() > mkt_vol_ma.groupby(df['date']).first()] = 1
        regime_series[mkt_trend < -0.05] = 2
        
        regime_df = pd.DataFrame({'date': mkt_ret.index, 'regime': regime_series.values})
        df = df.merge(regime_df, on='date', how='left')
        df['regime'] = df['regime'].fillna(0)

        # 2. Base Factors
        def _calc_base(g):
            g = g.copy()
            g['f_lowvol'] = -g['close'].pct_change().rolling(20).std()
            g['f_value'] = np.where(g['pb'] > 0, 1.0/(g['pb']+1e-9), 0) + np.where(g['pe'] > 0, 1.0/(g['pe']+1e-9), 0)
            g['f_momentum'] = g['close'].pct_change(20)
            g['f_quality'] = g['close'].rolling(60).mean() / (g['close'].rolling(60).std() + 1e-9)
            
            # --- Mined Factors ---
            g['f_rev1'] = -g['close'].pct_change(1)
            # Inverse Vol Stability (higher stability is better)
            g['f_vol_stab'] = - (g['volume'].rolling(20).std() / (g['volume'].rolling(20).mean() + 1e-9))
            return g
            
        df = df.groupby('stock_code', group_keys=False).apply(_calc_base)
        
        # 3. Z-Score
        factors = ['f_lowvol', 'f_value', 'f_momentum', 'f_quality', 'f_rev1', 'f_vol_stab']
        for f in factors:
            df[f'{f}_z'] = df.groupby('date')[f].transform(lambda x: (x - x.mean()) / (x.std() + 1e-9))
            
        # 4. Dynamic Weights
        df['score'] = 0.0
        # Bull (0): Add Vol Stability as filter
        mask0 = df['regime'] == 0
        df.loc[mask0, 'score'] = (
            df.loc[mask0, 'f_momentum_z'] * 0.4 + 
            df.loc[mask0, 'f_value_z'] * 0.2 + 
            df.loc[mask0, 'f_quality_z'] * 0.2 +
            df.loc[mask0, 'f_vol_stab_z'] * 0.2  # Marathon Mining influence
        )
        # Shaking (1): Strong Reversal + Vol Stability
        mask1 = df['regime'] == 1
        df.loc[mask1, 'score'] = (
            df.loc[mask1, 'f_rev1_z'] * 0.4 + 
            df.loc[mask1, 'f_vol_stab_z'] * 0.3 + 
            df.loc[mask1, 'f_lowvol_z'] * 0.3
        )
        # Bear (2)
        mask2 = df['regime'] == 2
        df.loc[mask2, 'score'] = df.loc[mask2, 'f_lowvol_z'] * 1.0 - 5.0
        
        # 5. Ranking
        return self._generate_signals(df)

    def _generate_signals(self, df):
        def _apply_ranking(day_g):
            day_g = day_g.copy()
            day_g['signal'] = 0
            if len(day_g) < self.top_n: return day_g
            top_idx = day_g.nlargest(self.top_n, 'score').index
            day_g.loc[top_idx, 'signal'] = 1
            day_g.loc[day_g.nsmallest(self.top_n, 'score').index, 'signal'] = -1
            return day_g
        return df.groupby('date', group_keys=False).apply(_apply_ranking)
