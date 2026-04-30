from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd


BASE_COLUMNS = [
    "date",
    "stock_code",
    "stock_name",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "pct_chg",
    "turn",
    "turnover_rate",
    "pe",
    "pb",
    "ps",
    "pcf",
]

PRICE_FEATURES = [
    "ret_1d",
    "mom_3d",
    "mom_5d",
    "mom_10d",
    "mom_20d",
    "mom_60d",
    "reversal_3d",
    "reversal_5d",
    "ma_gap_5d",
    "ma_gap_20d",
    "high_20d_position",
    "drawdown_20d",
    "intraday_ret",
    "open_gap",
    "amplitude",
]

VOL_FEATURES = [
    "volatility_5d",
    "volatility_20d",
    "volume_ratio_5d",
    "volume_ratio_20d",
    "amount_ratio_20d",
    "turnover_rate",
    "turnover_z20",
]

VALUE_FEATURES = [
    "value_pe",
    "value_pb",
    "value_ps",
    "value_pcf",
]

CROSS_SECTION_FEATURES = [
    "mom_20d_rank",
    "reversal_5d_rank",
    "volatility_20d_rank",
    "volume_ratio_20d_rank",
    "value_pb_rank",
    "relative_strength_20d",
    "market_breadth_20d",
    "market_ret_1d",
]

FEATURE_COLUMNS = PRICE_FEATURES + VOL_FEATURES + VALUE_FEATURES + CROSS_SECTION_FEATURES

SUPPORTED_LABELS = {
    "next_open_ret": "next_open_ret",
    "next_close_ret": "next_close_ret",
    "next_5d_ret": "next_5d_ret",
}

LABEL_HORIZONS = {
    "next_open_ret": 1,
    "next_close_ret": 1,
    "next_5d_ret": 5,
}


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0, np.nan)


def _apply_by_stock(df: pd.DataFrame, func) -> pd.DataFrame:
    parts = []
    for stock_code, group in df.groupby("stock_code", sort=False):
        part = func(group.copy())
        part["stock_code"] = stock_code
        parts.append(part)
    if not parts:
        return df.copy()
    return pd.concat(parts, ignore_index=True)


def _coerce_numeric(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    for column in columns:
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def standardize_market_frame(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw OHLCV frames into the field contract used by Factor Lab."""
    if raw_df is None or raw_df.empty:
        return pd.DataFrame(columns=BASE_COLUMNS)

    df = raw_df.copy().rename(
        columns={
            "日期": "date",
            "股票代码": "stock_code",
            "代码": "stock_code",
            "名称": "stock_name",
            "股票名称": "stock_name",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "pct_chg",
            "换手率": "turn",
            "振幅": "amplitude",
            "pctChg": "pct_chg",
            "peTTM": "pe",
            "pbMRQ": "pb",
            "psTTM": "ps",
            "pcfNcfTTM": "pcf",
        }
    )

    if "date" not in df.columns:
        raise ValueError("market frame must include date")
    if "stock_code" not in df.columns:
        raise ValueError("market frame must include stock_code")

    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "stock_code"]).copy()
    df["date"] = df["date"].dt.strftime("%Y-%m-%d")
    df["stock_code"] = (
        df["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(df["stock_code"].astype(str))
    )
    if "stock_name" not in df.columns:
        df["stock_name"] = df["stock_code"]
    df["stock_name"] = df["stock_name"].fillna(df["stock_code"]).astype(str)

    numeric_defaults = {
        "open": np.nan,
        "high": np.nan,
        "low": np.nan,
        "close": np.nan,
        "volume": np.nan,
        "amount": np.nan,
        "pct_chg": np.nan,
        "turn": np.nan,
        "turnover_rate": np.nan,
        "pe": np.nan,
        "pb": np.nan,
        "ps": np.nan,
        "pcf": np.nan,
        "amplitude": np.nan,
    }
    for column, default in numeric_defaults.items():
        if column not in df.columns:
            df[column] = default
    df = _coerce_numeric(df, numeric_defaults.keys())

    if df["turnover_rate"].isna().all() and "turn" in df.columns:
        df["turnover_rate"] = df["turn"]
    if df["turn"].isna().all() and "turnover_rate" in df.columns:
        df["turn"] = df["turnover_rate"]

    df = df.sort_values(["stock_code", "date"]).drop_duplicates(["stock_code", "date"], keep="last")
    df = df.reset_index(drop=True)

    def _derive(group: pd.DataFrame) -> pd.DataFrame:
        group = group.copy()
        group["prev_close"] = group["close"].shift(1)
        inferred_prev_close = _safe_divide(group["close"], 1.0 + group["pct_chg"] / 100.0)
        group["prev_close"] = group["prev_close"].fillna(inferred_prev_close)
        group["intraday_ret"] = _safe_divide(group["close"], group["open"]) - 1.0
        group["open_gap"] = _safe_divide(group["open"], group["prev_close"]) - 1.0
        group["gap"] = group["open_gap"]
        derived_amplitude = _safe_divide(group["high"] - group["low"], group["prev_close"]) * 100.0
        fallback_amplitude = _safe_divide(group["high"] - group["low"], group["close"]) * 100.0
        group["amplitude"] = group["amplitude"].fillna(derived_amplitude).fillna(fallback_amplitude)

        volume_base = group["volume"].rolling(20, min_periods=5).median()
        derived_turnover = _safe_divide(group["volume"], volume_base) * 100.0
        group["turnover_rate"] = group["turnover_rate"].fillna(derived_turnover)
        group["turn"] = group["turn"].fillna(group["turnover_rate"])
        return group

    df = _apply_by_stock(df, _derive)
    return df


def generate_features(standardized_df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
    if standardized_df is None or standardized_df.empty:
        return pd.DataFrame(), {}

    df = standardize_market_frame(standardized_df)
    df = df.sort_values(["stock_code", "date"]).copy()

    def _features(group: pd.DataFrame) -> pd.DataFrame:
        group = group.copy()
        close = group["close"]
        ret = close.pct_change()
        group["ret_1d"] = ret
        for window in [3, 5, 10, 20, 60]:
            group["mom_%dd" % window] = close / close.shift(window) - 1.0
        group["reversal_3d"] = -group["mom_3d"]
        group["reversal_5d"] = -group["mom_5d"]
        group["volatility_5d"] = ret.rolling(5, min_periods=3).std() * np.sqrt(252)
        group["volatility_20d"] = ret.rolling(20, min_periods=8).std() * np.sqrt(252)
        group["volume_ratio_5d"] = _safe_divide(group["volume"], group["volume"].rolling(5, min_periods=3).mean())
        group["volume_ratio_20d"] = _safe_divide(group["volume"], group["volume"].rolling(20, min_periods=8).mean())
        group["amount_ratio_20d"] = _safe_divide(group["amount"], group["amount"].rolling(20, min_periods=8).mean())
        group["ma_gap_5d"] = _safe_divide(close, close.rolling(5, min_periods=3).mean()) - 1.0
        group["ma_gap_20d"] = _safe_divide(close, close.rolling(20, min_periods=8).mean()) - 1.0
        low_20d = group["low"].rolling(20, min_periods=8).min()
        high_20d = group["high"].rolling(20, min_periods=8).max()
        group["high_20d_position"] = _safe_divide(close - low_20d, high_20d - low_20d)
        group["drawdown_20d"] = _safe_divide(close, close.rolling(20, min_periods=8).max()) - 1.0
        turnover_mean = group["turnover_rate"].rolling(20, min_periods=8).mean()
        turnover_std = group["turnover_rate"].rolling(20, min_periods=8).std()
        group["turnover_z20"] = _safe_divide(group["turnover_rate"] - turnover_mean, turnover_std)
        return group

    df = _apply_by_stock(df, _features)

    for source_col, target_col in [
        ("pe", "value_pe"),
        ("pb", "value_pb"),
        ("ps", "value_ps"),
        ("pcf", "value_pcf"),
    ]:
        values = pd.to_numeric(df[source_col], errors="coerce")
        df[target_col] = np.where(values > 0, 1.0 / values, np.nan)

    rank_specs = [
        ("mom_20d", True, "mom_20d_rank"),
        ("reversal_5d", True, "reversal_5d_rank"),
        ("volatility_20d", False, "volatility_20d_rank"),
        ("volume_ratio_20d", True, "volume_ratio_20d_rank"),
        ("value_pb", True, "value_pb_rank"),
    ]
    for source_col, ascending, target_col in rank_specs:
        df[target_col] = df.groupby("date")[source_col].rank(pct=True, ascending=ascending)

    daily_mean_mom = df.groupby("date")["mom_20d"].transform("mean")
    df["relative_strength_20d"] = df["mom_20d"] - daily_mean_mom
    df["above_ma20"] = (df["ma_gap_20d"] > 0).astype(float)
    df["market_breadth_20d"] = df.groupby("date")["above_ma20"].transform("mean")
    df["market_ret_1d"] = df.groupby("date")["ret_1d"].transform("mean")

    groups = {
        "price_momentum": ["mom_3d", "mom_5d", "mom_10d", "mom_20d", "mom_60d", "ma_gap_20d"],
        "reversal": ["reversal_3d", "reversal_5d", "drawdown_20d"],
        "volatility": ["volatility_5d", "volatility_20d", "amplitude"],
        "volume_turnover": ["volume_ratio_5d", "volume_ratio_20d", "amount_ratio_20d", "turnover_rate", "turnover_z20"],
        "valuation": VALUE_FEATURES,
        "cross_section": CROSS_SECTION_FEATURES,
    }
    return df, groups


def add_labels(feature_df: pd.DataFrame, target_label: str = "next_5d_ret") -> pd.DataFrame:
    if target_label not in SUPPORTED_LABELS:
        raise ValueError("unsupported label: %s" % target_label)

    df = feature_df.sort_values(["stock_code", "date"]).copy()

    def _labels(group: pd.DataFrame) -> pd.DataFrame:
        group = group.copy()
        group["next_open_ret"] = group["open"].shift(-1) / group["close"] - 1.0
        group["next_close_ret"] = group["close"].shift(-1) / group["close"] - 1.0
        group["next_5d_ret"] = group["close"].shift(-5) / group["close"] - 1.0
        horizon = LABEL_HORIZONS[target_label]
        group["label_end_date"] = group["date"].shift(-horizon)
        group["label_horizon"] = horizon
        return group

    df = _apply_by_stock(df, _labels)
    df["label_reg"] = df[target_label]
    df["label_cls"] = (df["label_reg"] > 0).astype(int)
    return df


def build_model_sample(
    raw_df: pd.DataFrame,
    target_label: str = "next_5d_ret",
    winsorize: bool = True,
) -> Tuple[pd.DataFrame, List[str], Dict[str, List[str]]]:
    features, feature_groups = generate_features(raw_df)
    labeled = add_labels(features, target_label=target_label)
    sample = labeled.replace([np.inf, -np.inf], np.nan).dropna(subset=["label_reg"]).copy()
    available_features = [
        column
        for column in FEATURE_COLUMNS
        if column in sample.columns and sample[column].notna().sum() >= max(10, int(len(sample) * 0.05))
    ]
    if winsorize:
        sample = winsorize_features(sample, available_features)
    return sample, available_features, feature_groups


def winsorize_features(
    sample: pd.DataFrame,
    feature_columns: List[str],
    fit_split: str = "train",
) -> pd.DataFrame:
    out = sample.copy()
    fit_frame = out
    if "split" in out.columns:
        candidate = out[out["split"] == fit_split]
        if not candidate.empty:
            fit_frame = candidate

    for column in feature_columns:
        series = pd.to_numeric(sample[column], errors="coerce")
        valid = pd.to_numeric(fit_frame[column], errors="coerce").dropna()
        if valid.empty:
            continue
        lower = valid.quantile(0.01)
        upper = valid.quantile(0.99)
        if pd.notna(lower) and pd.notna(upper) and lower < upper:
            out[column] = series.clip(lower=lower, upper=upper)
    return out


def split_by_time(sample: pd.DataFrame) -> pd.DataFrame:
    if sample.empty:
        sample = sample.copy()
        sample["split"] = "train"
        return sample

    dates = sorted(sample["date"].dropna().unique().tolist())
    n_dates = len(dates)
    train_end = max(1, int(n_dates * 0.6))
    valid_end = max(train_end + 1, int(n_dates * 0.8))
    train_dates = set(dates[:train_end])
    valid_dates = set(dates[train_end:valid_end])
    first_valid_date = dates[train_end] if train_end < n_dates else None
    first_test_date = dates[valid_end] if valid_end < n_dates else None

    out = sample.copy()
    out["split"] = "test"
    out.loc[out["date"].isin(train_dates), "split"] = "train"
    out.loc[out["date"].isin(valid_dates), "split"] = "valid"
    if "label_end_date" in out.columns:
        if first_valid_date is not None:
            out.loc[
                (out["split"] == "train") & (out["label_end_date"] >= first_valid_date),
                "split",
            ] = "purged"
        if first_test_date is not None:
            out.loc[
                (out["split"] == "valid") & (out["label_end_date"] >= first_test_date),
                "split",
            ] = "purged"
    return out
