from typing import Optional

import pandas as pd


def _apply_by_stock(df: pd.DataFrame, func) -> pd.DataFrame:
    parts = []
    for _, group in df.groupby("stock_code", sort=False):
        parts.append(func(group.copy()))
    if not parts:
        return df.copy()
    return pd.concat(parts, ignore_index=False)


def _prepare_overnight_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["stock_code", "date"]).copy()

    def _calc_features(group: pd.DataFrame) -> pd.DataFrame:
        group["prev_close"] = group["close"].shift(1)
        group["ma5"] = group["close"].rolling(5).mean()
        group["ma10"] = group["close"].rolling(10).mean()
        group["vol_ma5"] = group["volume"].rolling(5).mean()
        group["close_strength"] = (group["close"] - group["low"]) / (group["high"] - group["low"] + 1e-9)
        group["pct_chg_real"] = group["close"] / group["prev_close"] - 1
        group["vol_ratio"] = group["volume"] / (group["vol_ma5"] + 1e-9)
        group["intraday_ret"] = group["close"] / group["open"] - 1
        group["body_ratio"] = abs(group["close"] - group["open"]) / (group["high"] - group["low"] + 1e-9)
        group["open_gap"] = group["open"] / group["prev_close"] - 1
        return group

    features = _apply_by_stock(df, _calc_features)
    features["above_ma10"] = (features["close"] > features["ma10"]).astype(float)
    features["market_breadth_ma10"] = features.groupby("date")["above_ma10"].transform("mean")
    features["signal"] = 0
    features["raw_signal"] = 0
    features["score"] = 0.0
    return features


def _apply_daily_top_n(frame: pd.DataFrame, top_n: int) -> pd.DataFrame:
    if top_n <= 0:
        frame["signal"] = 0
        return frame

    eligible = frame[frame["raw_signal"] == 1].copy()
    if eligible.empty:
        frame["signal"] = 0
        return frame

    eligible = eligible.sort_values(["date", "score", "stock_code"], ascending=[True, False, True])
    eligible["daily_rank"] = eligible.groupby("date").cumcount() + 1
    keep_index = set(eligible[eligible["daily_rank"] <= top_n].index.tolist())

    frame["signal"] = 0
    frame.loc[frame.index.isin(keep_index), "signal"] = 1
    return frame


def _build_overnight_variant(
    df: pd.DataFrame,
    *,
    close_strength_min: float,
    pct_chg_min: float,
    pct_chg_max: float,
    vol_ratio_min: float,
    vol_ratio_max: float,
    amplitude_max: Optional[float] = None,
    turnover_max: Optional[float] = None,
    market_breadth_min: Optional[float] = None,
    top_n: Optional[int] = None,
    score_style: str = "balanced",
) -> pd.DataFrame:
    features = _prepare_overnight_features(df)

    trend_cond = (features["close"] > features["ma5"]) & (features["ma5"] > features["ma10"])
    buy_cond = (
        trend_cond
        & (features["close_strength"] >= close_strength_min)
        & features["pct_chg_real"].between(pct_chg_min, pct_chg_max)
        & features["vol_ratio"].between(vol_ratio_min, vol_ratio_max)
    )

    if amplitude_max is not None:
        buy_cond &= features["amplitude"] <= amplitude_max
    if turnover_max is not None:
        buy_cond &= features["turnover_rate"] <= turnover_max
    if market_breadth_min is not None:
        buy_cond &= features["market_breadth_ma10"] >= market_breadth_min

    if score_style == "quality":
        score = (
            features["close_strength"] * 6.0
            - (features["pct_chg_real"] - 0.040).abs() * 14.0
            - (features["vol_ratio"] - 1.35).abs() * 0.8
            - (features["turnover_rate"] - 2.0).clip(lower=0) * 0.20
            - (features["amplitude"] - 5.5).clip(lower=0) * 0.20
        )
    elif score_style == "ranked":
        pct_bonus = 0.06 - (features["pct_chg_real"] - 0.045).abs() * 1.8
        vol_bonus = 0.9 - (features["vol_ratio"] - 1.45).abs() * 0.5
        score = (
            features["close_strength"] * 6.0
            + pct_bonus
            + vol_bonus
            + features["intraday_ret"] * 2.0
            - (features["turnover_rate"] - 2.5).clip(lower=0) * 0.18
            - (features["amplitude"] - 6.0).clip(lower=0) * 0.20
        )
    else:
        score = (
            features["close_strength"] * 5.0
            - (features["pct_chg_real"] - 0.045).abs() * 12.0
            - (features["vol_ratio"] - 1.50).abs() * 0.8
            - (features["amplitude"] - 5.0).clip(lower=0) * 0.15
        )

    features["raw_signal"] = buy_cond.fillna(False).astype(int)
    features["score"] = score.fillna(-999.0)
    features["signal"] = features["raw_signal"]

    if top_n is not None:
        features = _apply_daily_top_n(features, top_n=top_n)

    return features


def calculate_overnight_hold_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    隔夜持股 (Overnight Hold) - 旧版基线:
    核心逻辑：寻找尾盘强力扫货、量价协同、且避开涨停的强势标的。
    注意：保留旧版逻辑作为基线，不引入 score，避免改写原有容量截断语义。
    """
    features = _prepare_overnight_features(df)
    buy_cond = (
        (features["close_strength"] > 0.9)
        & (features["pct_chg_real"] > 0.03)
        & (features["pct_chg_real"] < 0.095)
        & (features["vol_ratio"] > 1.3)
        & (features["close"] > features["ma5"])
        & (features["ma5"] > features["ma10"])
    )
    features["raw_signal"] = buy_cond.fillna(False).astype(int)
    features["signal"] = features["raw_signal"]
    features = features.drop(columns=["score"])
    return features


def calculate_overnight_hold_signals_quality(df: pd.DataFrame) -> pd.DataFrame:
    """
    方案 A: 质量收缩版。
    重点保留极高 close_strength，同时对涨幅、量比和波动做更严格的联合约束。
    """
    return _build_overnight_variant(
        df,
        close_strength_min=0.95,
        pct_chg_min=0.03,
        pct_chg_max=0.095,
        vol_ratio_min=1.2,
        vol_ratio_max=1.8,
        amplitude_max=7.0,
        top_n=2,
        score_style="quality",
    )


def calculate_overnight_hold_signals_balanced(df: pd.DataFrame) -> pd.DataFrame:
    """
    方案 B: 平衡推荐版。
    高收盘强度 + 非过热 + 非拥挤，并用市场宽度与换手上限压掉差的 tape。
    """
    return _build_overnight_variant(
        df,
        close_strength_min=0.95,
        pct_chg_min=0.02,
        pct_chg_max=0.095,
        vol_ratio_min=1.3,
        vol_ratio_max=1.8,
        amplitude_max=7.0,
        turnover_max=3.5,
        market_breadth_min=0.45,
        top_n=2,
        score_style="quality",
    )


def calculate_overnight_hold_signals_ranked(df: pd.DataFrame) -> pd.DataFrame:
    """
    方案 C: 打分排序版。
    放宽预筛，再用“强收盘 + 不过热 + 不过拥挤”线性打分，只保留每日最优机会。
    """
    return _build_overnight_variant(
        df,
        close_strength_min=0.85,
        pct_chg_min=0.03,
        pct_chg_max=0.08,
        vol_ratio_min=1.3,
        vol_ratio_max=1.8,
        amplitude_max=8.0,
        top_n=1,
        score_style="ranked",
    )


def calculate_weak_to_strong_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    弱转强 (Weak to Strong) - 信号工厂:
    逻辑：识别开盘低开（弱），盘中迅速放量收复失地并收红（强）的结构。
    """
    df = df.sort_values(["stock_code", "date"]).copy()

    def _calc_signals(group: pd.DataFrame) -> pd.DataFrame:
        group["prev_close"] = group["close"].shift(1)
        group["vol_ma5"] = group["volume"].rolling(5).mean()
        group["ma10"] = group["close"].rolling(10).mean()
        group["open_gap"] = group["open"] / group["prev_close"] - 1
        group["close_gap"] = group["close"] / group["prev_close"] - 1
        group["vol_ratio"] = group["volume"] / (group["vol_ma5"] + 1e-9)
        group["signal"] = 0
        buy_cond = (
            (group["open_gap"] < -0.01)
            & (group["close_gap"] > 0.01)
            & (group["vol_ratio"] > 1.5)
            & (group["close"] > group["ma10"])
        )
        group.loc[buy_cond, "signal"] = 1
        return group

    return _apply_by_stock(df, _calc_signals)


def calculate_limit_up_doji_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    涨停十字星 (Limit Up Doji) - 信号工厂:
    逻辑：昨日涨停，今日收缩量十字星，预期第二波启动。
    """
    df = df.sort_values(["stock_code", "date"]).copy()

    def _calc_signals(group: pd.DataFrame) -> pd.DataFrame:
        group["prev_close"] = group["close"].shift(1)
        group["prev_pct_chg"] = group["close"] / group["prev_close"] - 1
        group["prev_volume"] = group["volume"].shift(1)
        group["body_ratio"] = abs(group["open"] - group["close"]) / (group["high"] - group["low"] + 1e-9)
        group["signal"] = 0
        buy_cond = (
            (group["prev_pct_chg"] > 0.095)
            & (group["body_ratio"] < 0.15)
            & (group["volume"] < group["prev_volume"] * 0.7)
            & (group["low"] > group["prev_close"] * 0.98)
        )
        group.loc[buy_cond, "signal"] = 1
        return group

    return _apply_by_stock(df, _calc_signals)
