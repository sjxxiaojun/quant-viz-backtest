import json
import os
import tempfile
import threading
import warnings
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .data_prep import FEATURE_COLUMNS, build_model_sample, split_by_time, winsorize_features


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = PROJECT_ROOT / "results" / "quant-factor-mining" / "reports" / "factor_lab"
LATEST_RESULT_PATH = REPORT_ROOT / "latest_summary.json"
LATEST_MODEL_PATH = REPORT_ROOT / "latest_model.joblib"
LATEST_SCORES_PATH = REPORT_ROOT / "latest_scores.csv"
LATEST_MANIFEST_PATH = REPORT_ROOT / "latest_manifest.json"

DEFAULT_BASELINE_WEIGHT = 0.35
DEFAULT_NONLINEAR_WEIGHT = 0.65
FACTOR_LAB_WRITE_LOCK = threading.RLock()


FACTOR_NAME_CN = {
    "ret_1d": "1日涨跌",
    "mom_3d": "3日动量",
    "mom_5d": "5日动量",
    "mom_10d": "10日动量",
    "mom_20d": "20日动量",
    "mom_60d": "60日动量",
    "reversal_3d": "3日反转",
    "reversal_5d": "5日反转",
    "ma_gap_5d": "5日均线偏离",
    "ma_gap_20d": "20日均线偏离",
    "high_20d_position": "20日区间位置",
    "drawdown_20d": "20日回撤",
    "intraday_ret": "日内涨跌",
    "open_gap": "开盘跳空",
    "amplitude": "日内振幅",
    "volatility_5d": "5日波动",
    "volatility_20d": "20日波动",
    "volume_ratio_5d": "5日量比",
    "volume_ratio_20d": "20日量比",
    "amount_ratio_20d": "20日成交额变化",
    "turnover_rate": "换手率",
    "turnover_z20": "换手异常度",
    "value_pe": "市盈率估值",
    "value_pb": "市净率估值",
    "value_ps": "市销率估值",
    "value_pcf": "现金流估值",
    "mom_20d_rank": "20日动量横截面排名",
    "reversal_5d_rank": "5日反转横截面排名",
    "volatility_20d_rank": "20日波动横截面排名",
    "volume_ratio_20d_rank": "20日量比横截面排名",
    "value_pb_rank": "市净率估值横截面排名",
    "relative_strength_20d": "20日相对强弱",
    "market_breadth_20d": "市场广度",
    "market_ret_1d": "市场日收益",
    "risk_adjusted_mom_20d": "波动调整动量",
    "liquidity_momentum_20d": "量价共振动量",
    "reversal_liquidity_5d": "放量反转",
    "low_vol_momentum_20d": "低波动动量",
    "panic_rebound_20d": "回撤修复弹性",
    "value_momentum_pb_20d": "估值动量共振",
    "gap_reversal_pressure": "跳空反转压力",
}


def _factor_name_cn(feature: str) -> str:
    if feature in FACTOR_NAME_CN:
        return FACTOR_NAME_CN[feature]
    return feature.replace("_", " ")


def _factor_plain_explanation(feature: str) -> str:
    name = feature.lower()
    if "risk_adjusted_mom" in name:
        return "看上涨是否不是靠过高波动堆出来的，偏向更干净的趋势。"
    if "liquidity_momentum" in name:
        return "把价格强度和成交活跃度放在一起看，避免只有价格没有成交支撑。"
    if "reversal_liquidity" in name:
        return "看短期回落后是否伴随成交改善，寻找反弹质量更好的样本。"
    if "low_vol_momentum" in name:
        return "偏好走势相对强、但波动没有失控的股票。"
    if "panic_rebound" in name:
        return "看深回撤之后的修复弹性，避免单纯追涨。"
    if "value_momentum" in name:
        return "把估值相对便宜和中期强势结合起来看。"
    if "gap_reversal" in name:
        return "观察开盘跳空和短线反转之间是否有情绪修复机会。"
    if "mom" in name or "relative_strength" in name:
        return "看股票最近是不是比其他股票更强。"
    if "reversal" in name or "drawdown" in name:
        return "看短期下跌后是否有反弹或修复特征。"
    if "volatility" in name or "amplitude" in name:
        return "看价格波动是否过大或更稳定。"
    if "turnover" in name or "volume" in name or "amount" in name:
        return "看成交是否活跃，避免信号只停留在纸面上。"
    if "value" in name or "pe" in name or "pb" in name:
        return "看价格相对基本面是否便宜或昂贵。"
    if "gap" in name or "intraday" in name:
        return "看当天开盘和盘中价格行为是否透露短期情绪。"
    if "market" in name:
        return "看整体市场环境是否支持这个信号。"
    return "模型认为这个指标对股票排序有解释力。"


def _direction_text(direction: str) -> str:
    return "数值偏高更有利" if direction != "short" else "数值偏低更有利"


@dataclass
class FactorLabConfig:
    start_date: str
    end_date: str
    pool: str = "core"
    label: str = "next_5d_ret"
    top_n: int = 5
    max_symbols: Optional[int] = None
    random_state: int = 42
    rf_n_estimators: int = 40
    rf_max_samples: float = 0.65
    rf_n_jobs: int = -1
    walk_forward_rf_n_estimators: int = 24
    walk_forward_max_windows: int = 4
    walk_forward_max_train_rows: int = 36000


def _config_hash(config: FactorLabConfig) -> str:
    import hashlib

    payload = json.dumps(asdict(config), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _atomic_write_json(path: Path, payload: Dict[str, object]) -> None:
    _atomic_write_text(path, json.dumps(_json_safe(payload), ensure_ascii=False, indent=2))


def _atomic_to_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    try:
        df.to_csv(tmp_name, index=False)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _atomic_joblib_dump(payload: Dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    try:
        joblib.dump(payload, tmp_name)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _json_safe(value):
    if isinstance(value, (np.floating, np.integer)):
        return _json_safe(value.item())
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    if isinstance(value, dict):
        return {key: _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _daily_corr(frame: pd.DataFrame, factor: str, label: str, method: str) -> pd.Series:
    values = []
    for date, group in frame.groupby("date"):
        valid = group[[factor, label]].dropna()
        if len(valid) < 5 or valid[factor].nunique() < 2 or valid[label].nunique() < 2:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            corr = valid[factor].corr(valid[label], method=method)
        if pd.notna(corr):
            values.append((date, corr))
    if not values:
        return pd.Series(dtype=float)
    return pd.Series({date: corr for date, corr in values})


def _daily_corr_frame(
    frame: pd.DataFrame,
    feature_columns: List[str],
    label: str,
    method: str,
) -> pd.DataFrame:
    rows = []
    index = []
    for date, group in frame.groupby("date", sort=False):
        if len(group) < 5:
            continue
        y = group[label]
        if y.notna().sum() < 5 or y.nunique(dropna=True) < 2:
            continue
        x = group[feature_columns]
        if method == "spearman":
            x = x.rank(method="average")
            y = y.rank(method="average")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            corr = x.corrwith(y, method="pearson")
        counts = x.notna().mul(y.notna(), axis=0).sum()
        corr = corr.where((counts >= 5) & (x.nunique(dropna=True) > 1))
        corr = corr.replace([np.inf, -np.inf], np.nan).dropna()
        if corr.empty:
            continue
        rows.append(corr)
        index.append(date)
    if not rows:
        return pd.DataFrame(columns=feature_columns)
    return pd.DataFrame(rows, index=index).reindex(columns=feature_columns)


def _bucket_returns(frame: pd.DataFrame, factor: str, label: str, buckets: int = 5) -> Dict[str, float]:
    valid = frame[["date", factor, label]].dropna().copy()
    if valid.empty:
        return {}

    counts = valid.groupby("date")[factor].transform("count")
    uniques = valid.groupby("date")[factor].transform("nunique")
    valid = valid[(counts >= buckets) & (uniques >= buckets)].copy()
    if valid.empty:
        return {}

    ranked_pct = valid.groupby("date")[factor].rank(method="first", pct=True)
    valid["bucket"] = np.ceil(ranked_pct * buckets).clip(1, buckets).astype(int)
    result = valid.groupby("bucket")[label].mean().to_dict()
    return {"bucket_%d" % int(bucket): float(value) for bucket, value in result.items()}


def evaluate_factors(sample: pd.DataFrame, feature_columns: List[str]) -> pd.DataFrame:
    rows = []
    label = "label_reg"
    columns = ["date", label] + feature_columns
    numeric = sample[columns].copy()
    numeric["date"] = numeric["date"].astype(str)
    numeric[label] = pd.to_numeric(numeric[label], errors="coerce")
    numeric[feature_columns] = numeric[feature_columns].apply(pd.to_numeric, errors="coerce")

    latest_cutoff = None
    if not numeric.empty:
        latest_date = pd.to_datetime(numeric["date"]).max()
        latest_cutoff = (latest_date - pd.Timedelta(days=365)).strftime("%Y-%m-%d")

    label_mask = numeric[label].notna()
    sample_counts = numeric.loc[label_mask, feature_columns].notna().sum()
    feature_uniques = numeric.loc[label_mask, feature_columns].nunique(dropna=True)
    ic_by_date = _daily_corr_frame(numeric, feature_columns, label, "pearson")
    rank_ic_by_date = _daily_corr_frame(numeric, feature_columns, label, "spearman")
    recent_rank_ic_by_date = (
        _daily_corr_frame(numeric[numeric["date"] >= latest_cutoff], feature_columns, label, "spearman")
        if latest_cutoff is not None
        else pd.DataFrame(columns=feature_columns)
    )

    for feature in feature_columns:
        sample_count = int(sample_counts.get(feature, 0))
        if sample_count < 20 or int(feature_uniques.get(feature, 0)) < 3:
            continue
        ic = ic_by_date[feature].dropna() if feature in ic_by_date.columns else pd.Series(dtype=float)
        rank_ic = rank_ic_by_date[feature].dropna() if feature in rank_ic_by_date.columns else pd.Series(dtype=float)
        buckets = _bucket_returns(numeric, feature, label)
        bucket_values = [buckets.get("bucket_%d" % idx) for idx in range(1, 6)]
        monotonicity = 0.0
        if all(value is not None for value in bucket_values):
            monotonicity = float(pd.Series(range(1, 6)).corr(pd.Series(bucket_values), method="spearman") or 0.0)

        recent_rank_ic = (
            recent_rank_ic_by_date[feature].dropna()
            if feature in recent_rank_ic_by_date.columns
            else pd.Series(dtype=float)
        )
        rows.append(
            {
                "factor": feature,
                "sample_count": sample_count,
                "ic_mean": float(ic.mean()) if len(ic) else 0.0,
                "ic_std": float(ic.std(ddof=0)) if len(ic) else 0.0,
                "rank_ic_mean": float(rank_ic.mean()) if len(rank_ic) else 0.0,
                "rank_ic_std": float(rank_ic.std(ddof=0)) if len(rank_ic) else 0.0,
                "ic_positive_ratio": float((ic > 0).mean()) if len(ic) else 0.0,
                "recent_rank_ic_mean": float(recent_rank_ic.mean()) if len(recent_rank_ic) else 0.0,
                "monotonicity": monotonicity,
                "abs_rank_ic": float(abs(rank_ic.mean())) if len(rank_ic) else 0.0,
            }
        )

    ranking = pd.DataFrame(rows)
    if ranking.empty:
        return ranking
    ranking["factor_score"] = (
        ranking["abs_rank_ic"] * 0.55
        + ranking["ic_positive_ratio"] * 0.20
        + ranking["monotonicity"].abs() * 0.15
        + ranking["recent_rank_ic_mean"].abs() * 0.10
    )
    return ranking.sort_values(["factor_score", "abs_rank_ic", "sample_count"], ascending=[False, False, False])


def _rank_ic_by_date(frame: pd.DataFrame, score_col: str) -> float:
    values = []
    for _, group in frame.groupby("date"):
        valid = group[[score_col, "label_reg"]].dropna()
        if len(valid) >= 5 and valid[score_col].nunique() > 1 and valid["label_reg"].nunique() > 1:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                corr = valid[score_col].corr(valid["label_reg"], method="spearman")
            if pd.notna(corr):
                values.append(corr)
    return float(np.mean(values)) if values else 0.0


def _top_quantile_return(frame: pd.DataFrame, score_col: str, q: float = 0.2) -> float:
    rets = []
    for _, group in frame.groupby("date"):
        valid = group[[score_col, "label_reg"]].dropna()
        if len(valid) < 5:
            continue
        cutoff = valid[score_col].quantile(1.0 - q)
        selected = valid[valid[score_col] >= cutoff]
        if not selected.empty:
            rets.append(selected["label_reg"].mean())
    return float(np.mean(rets)) if rets else 0.0


def _rank_by_date(frame: pd.DataFrame, column: str, ascending: bool = True) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index)
    values = pd.to_numeric(frame[column], errors="coerce")
    return values.groupby(frame["date"]).rank(pct=True, ascending=ascending)


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0, np.nan)


CandidateRecipe = Tuple[str, str, List[str], Callable[[pd.DataFrame], pd.Series]]


def _candidate_factor_recipes() -> List[CandidateRecipe]:
    return [
        (
            "risk_adjusted_mom_20d",
            "20日动量 / 20日波动",
            ["mom_20d", "volatility_20d"],
            lambda frame: _safe_ratio(
                pd.to_numeric(frame["mom_20d"], errors="coerce"),
                pd.to_numeric(frame["volatility_20d"], errors="coerce").abs() + 1e-6,
            ),
        ),
        (
            "liquidity_momentum_20d",
            "20日动量排名 * 20日量比排名",
            ["mom_20d_rank", "volume_ratio_20d_rank"],
            lambda frame: _rank_by_date(frame, "mom_20d_rank") * _rank_by_date(frame, "volume_ratio_20d_rank"),
        ),
        (
            "reversal_liquidity_5d",
            "5日反转排名 * 20日量比排名",
            ["reversal_5d_rank", "volume_ratio_20d_rank"],
            lambda frame: _rank_by_date(frame, "reversal_5d_rank") * _rank_by_date(frame, "volume_ratio_20d_rank"),
        ),
        (
            "low_vol_momentum_20d",
            "20日动量排名 * 低波动排名",
            ["mom_20d_rank", "volatility_20d_rank"],
            lambda frame: _rank_by_date(frame, "mom_20d_rank") * (1.0 - _rank_by_date(frame, "volatility_20d_rank")),
        ),
        (
            "panic_rebound_20d",
            "20日回撤幅度 * 5日反转",
            ["drawdown_20d", "reversal_5d"],
            lambda frame: pd.to_numeric(frame["drawdown_20d"], errors="coerce").abs()
            * pd.to_numeric(frame["reversal_5d"], errors="coerce"),
        ),
        (
            "value_momentum_pb_20d",
            "市净率估值排名 * 20日动量排名",
            ["value_pb_rank", "mom_20d_rank"],
            lambda frame: _rank_by_date(frame, "value_pb_rank") * _rank_by_date(frame, "mom_20d_rank"),
        ),
        (
            "gap_reversal_pressure",
            "开盘跳空反向 * 3日反转",
            ["open_gap", "reversal_3d"],
            lambda frame: -pd.to_numeric(frame["open_gap"], errors="coerce")
            * pd.to_numeric(frame["reversal_3d"], errors="coerce"),
        ),
    ]


def mine_candidate_factors(
    sample: pd.DataFrame,
    feature_columns: List[str],
    max_promoted: int = 6,
) -> Tuple[pd.DataFrame, List[str], Dict[str, List[str]], Dict[str, object]]:
    """Generate non-leaky candidate factors and promote the ones that pass train/valid evidence."""
    out = sample.copy()
    base_features = set(feature_columns)
    candidate_columns = []
    tested = []
    recipe_lookup: Dict[str, Dict[str, object]] = {}

    for name, formula, dependencies, builder in _candidate_factor_recipes():
        if name in out.columns or not set(dependencies).issubset(out.columns):
            continue
        values = builder(out).replace([np.inf, -np.inf], np.nan)
        if values.notna().sum() < max(30, int(len(out) * 0.05)) or values.nunique(dropna=True) < 5:
            tested.append(
                {
                    "factor": name,
                    "name_cn": _factor_name_cn(name),
                    "status": "skipped",
                    "formula": formula,
                    "dependencies": dependencies,
                    "reason": "有效样本或取值层次不足，未进入本轮验证。",
                }
            )
            continue
        out[name] = values
        candidate_columns.append(name)
        recipe_lookup[name] = {
            "factor": name,
            "name_cn": _factor_name_cn(name),
            "formula": formula,
            "dependencies": dependencies,
        }

    if not candidate_columns:
        return out, feature_columns, {"discovered": []}, {
            "mode": "candidate_factor_mining",
            "tested": len(tested),
            "promoted": 0,
            "candidates": tested,
            "actions": ["本轮没有足够有效的候选组合因子进入验证。"],
        }

    discovery_frame = out[out.get("split", "train").isin(["train", "valid"])].copy() if "split" in out.columns else out.copy()
    holdout_frame = out[out["split"] == "test"].copy() if "split" in out.columns else pd.DataFrame()
    candidate_ranking = evaluate_factors(discovery_frame, candidate_columns)
    base_ranking = evaluate_factors(discovery_frame, list(feature_columns))

    if base_ranking.empty:
        promotion_cutoff = 0.01
    else:
        top_base = base_ranking.head(min(10, len(base_ranking)))["factor_score"]
        promotion_cutoff = max(0.01, float(top_base.median() * 0.70))

    holdout_ranking = evaluate_factors(holdout_frame, candidate_columns) if not holdout_frame.empty else pd.DataFrame()
    holdout_lookup = {
        row["factor"]: row.to_dict()
        for _, row in holdout_ranking.iterrows()
    } if not holdout_ranking.empty else {}

    promoted = []
    rows = []
    if not candidate_ranking.empty:
        for _, row in candidate_ranking.iterrows():
            factor = str(row["factor"])
            test_row = holdout_lookup.get(factor, {})
            status = "promoted" if len(promoted) < max_promoted and float(row.get("factor_score", 0.0)) >= promotion_cutoff else "watch"
            if status == "promoted":
                promoted.append(factor)
            rows.append(
                {
                    **recipe_lookup.get(factor, {}),
                    "status": status,
                    "score": float(row.get("factor_score", 0.0) or 0.0),
                    "rank_ic": float(row.get("rank_ic_mean", 0.0) or 0.0),
                    "recent_rank_ic": float(row.get("recent_rank_ic_mean", 0.0) or 0.0),
                    "test_rank_ic": float(test_row.get("rank_ic_mean", 0.0) or 0.0),
                    "reason": (
                        "训练/验证证据达到本轮晋级线，已加入模型训练。"
                        if status == "promoted"
                        else "有一定研究价值，但证据未达到本轮晋级线，先保留观察。"
                    ),
                }
            )

    skipped_names = {item["factor"] for item in rows}
    rows.extend([item for item in tested if item["factor"] not in skipped_names])
    actions = [
        f"本轮自动生成 {len(candidate_columns)} 个候选组合因子。",
        f"用训练集和验证集筛选候选，晋级线为 {promotion_cutoff:.4f}。",
        f"{len(promoted)} 个候选因子进入本轮模型训练；测试集只用于事后观察，不参与晋级。"
    ]
    return out, list(feature_columns) + promoted, {"discovered": promoted}, {
        "mode": "candidate_factor_mining",
        "tested": len(candidate_columns),
        "promoted": len(promoted),
        "promotion_cutoff": promotion_cutoff,
        "promoted_factors": promoted,
        "candidates": rows,
        "actions": actions,
    }


def _model_metrics(frame: pd.DataFrame, score_col: str, pred_col: str, model_name: str) -> Dict[str, object]:
    metrics = {"model": model_name}
    for split in ["train", "valid", "test"]:
        part = frame[frame["split"] == split].dropna(subset=[pred_col, "label_reg"])
        if part.empty:
            metrics["%s_r2" % split] = 0.0
            metrics["%s_mae" % split] = 0.0
            metrics["%s_rank_ic" % split] = 0.0
            metrics["%s_top20_ret" % split] = 0.0
            continue
        metrics["%s_r2" % split] = float(r2_score(part["label_reg"], part[pred_col]))
        metrics["%s_mae" % split] = float(mean_absolute_error(part["label_reg"], part[pred_col]))
        metrics["%s_rank_ic" % split] = _rank_ic_by_date(part, score_col)
        metrics["%s_top20_ret" % split] = _top_quantile_return(part, score_col)
    return metrics


def _build_model_pipelines(
    random_state: int,
    rf_n_estimators: int = 40,
    rf_max_samples: Optional[float] = 0.65,
    rf_n_jobs: int = -1,
) -> Dict[str, Pipeline]:
    rf_kwargs = {
        "n_estimators": max(8, int(rf_n_estimators)),
        "max_depth": 5,
        "min_samples_leaf": 5,
        "random_state": random_state,
        "n_jobs": rf_n_jobs,
    }
    if rf_max_samples is not None and 0 < float(rf_max_samples) <= 1:
        rf_kwargs["max_samples"] = float(rf_max_samples)
    return {
        "baseline": Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                ("scaler", StandardScaler()),
                ("model", Ridge(alpha=3.0, solver="svd")),
            ]
        ),
        "nonlinear": Pipeline(
            steps=[
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    RandomForestRegressor(**rf_kwargs),
                ),
            ]
        ),
    }


def _safe_predict(model: Pipeline, features: pd.DataFrame) -> np.ndarray:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return model.predict(features)


def _blend_score(frame: pd.DataFrame, baseline_weight: float, nonlinear_weight: float) -> pd.Series:
    baseline = pd.to_numeric(frame.get("baseline_score"), errors="coerce").fillna(0.5)
    nonlinear = pd.to_numeric(frame.get("ml_score"), errors="coerce").fillna(0.5)
    total = max(float(baseline_weight) + float(nonlinear_weight), 1e-9)
    return (baseline * float(baseline_weight) + nonlinear * float(nonlinear_weight)) / total


def _optimize_model_blend(scored: pd.DataFrame) -> Dict[str, object]:
    validation = scored[scored["split"] == "valid"].copy() if "split" in scored.columns else scored.iloc[0:0].copy()
    if validation.empty or validation["label_reg"].notna().sum() < 100:
        return {
            "baseline_weight": DEFAULT_BASELINE_WEIGHT,
            "nonlinear_weight": DEFAULT_NONLINEAR_WEIGHT,
            "selection_metric": "fallback_default",
            "selection_split": "valid",
            "reason": "验证集样本不足，沿用默认 35% 线性 + 65% 非线性。",
            "candidates": [],
        }

    candidate_weights = [0.35, 0.45, 0.55, 0.65, 0.75, 0.85]
    rows = []
    best_row = None
    for nonlinear_weight in candidate_weights:
        baseline_weight = 1.0 - nonlinear_weight
        candidate = validation.copy()
        candidate["candidate_score"] = _blend_score(candidate, baseline_weight, nonlinear_weight)
        rank_ic = _rank_ic_by_date(candidate, "candidate_score")
        top20_ret = _top_quantile_return(candidate, "candidate_score")
        objective = rank_ic * 0.75 + top20_ret * 0.25
        row = {
            "baseline_weight": baseline_weight,
            "nonlinear_weight": nonlinear_weight,
            "valid_rank_ic": rank_ic,
            "valid_top20_ret": top20_ret,
            "objective": objective,
        }
        rows.append(row)
        if best_row is None or row["objective"] > best_row["objective"]:
            best_row = row

    if best_row is None:
        best_row = {
            "baseline_weight": DEFAULT_BASELINE_WEIGHT,
            "nonlinear_weight": DEFAULT_NONLINEAR_WEIGHT,
            "valid_rank_ic": 0.0,
            "valid_top20_ret": 0.0,
            "objective": 0.0,
        }

    return {
        "baseline_weight": float(best_row["baseline_weight"]),
        "nonlinear_weight": float(best_row["nonlinear_weight"]),
        "selection_metric": "0.75*valid_rank_ic + 0.25*valid_top20_ret",
        "selection_split": "valid",
        "valid_rank_ic": float(best_row["valid_rank_ic"]),
        "valid_top20_ret": float(best_row["valid_top20_ret"]),
        "objective": float(best_row["objective"]),
        "reason": "每次运行都会在验证集重选线性模型和非线性模型的融合比例。",
        "candidates": rows,
    }


def train_models(
    sample: pd.DataFrame,
    feature_columns: List[str],
    random_state: int,
    rf_n_estimators: int = 40,
    rf_max_samples: Optional[float] = 0.65,
    rf_n_jobs: int = -1,
) -> Dict[str, object]:
    train = sample[sample["split"] == "train"].copy()
    if train.empty:
        raise ValueError("not enough training samples")

    fit_feature_columns = [
        column for column in feature_columns
        if column in train.columns and train[column].replace([np.inf, -np.inf], np.nan).notna().any()
    ]
    if len(fit_feature_columns) < 5:
        raise ValueError("not enough non-empty training features")

    x_train = train[fit_feature_columns].replace([np.inf, -np.inf], np.nan)
    y_train = train["label_reg"]

    pipelines = _build_model_pipelines(
        random_state,
        rf_n_estimators=rf_n_estimators,
        rf_max_samples=rf_max_samples,
        rf_n_jobs=rf_n_jobs,
    )
    baseline = pipelines["baseline"]
    nonlinear = pipelines["nonlinear"]

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        baseline.fit(x_train, y_train)
    nonlinear.fit(x_train, y_train)

    scored = sample.copy()
    x_all = scored[fit_feature_columns].replace([np.inf, -np.inf], np.nan)
    scored["baseline_pred"] = _safe_predict(baseline, x_all)
    scored["nonlinear_pred"] = _safe_predict(nonlinear, x_all)
    scored["baseline_pred"] = pd.Series(scored["baseline_pred"], index=scored.index).replace([np.inf, -np.inf], np.nan)
    scored["baseline_score"] = scored.groupby("date")["baseline_pred"].rank(pct=True)
    scored["ml_score"] = scored.groupby("date")["nonlinear_pred"].rank(pct=True)
    model_recipe = _optimize_model_blend(scored)
    scored["composite_score"] = _blend_score(
        scored,
        float(model_recipe["baseline_weight"]),
        float(model_recipe["nonlinear_weight"]),
    )

    metrics = [
        _model_metrics(scored, "baseline_score", "baseline_pred", "ridge_baseline"),
        _model_metrics(scored, "ml_score", "nonlinear_pred", "random_forest"),
        _model_metrics(scored, "composite_score", "nonlinear_pred", "composite_score"),
    ]

    rf_model = nonlinear.named_steps["model"]
    rf_importance = pd.DataFrame(
        {
            "feature": fit_feature_columns,
            "importance": rf_model.feature_importances_,
            "model": "random_forest",
        }
    )
    ridge = baseline.named_steps["model"]
    ridge_importance = pd.DataFrame(
        {
            "feature": fit_feature_columns,
            "importance": np.abs(ridge.coef_),
            "model": "ridge_abs_coef",
        }
    )
    feature_importance = pd.concat([rf_importance, ridge_importance], ignore_index=True)
    feature_importance["importance"] = feature_importance.groupby("model")["importance"].transform(
        lambda s: s / (s.sum() + 1e-12)
    )
    feature_importance = feature_importance.sort_values(["model", "importance"], ascending=[True, False])

    return {
        "baseline_model": baseline,
        "nonlinear_model": nonlinear,
        "scored": scored,
        "metrics": pd.DataFrame(metrics),
        "feature_importance": feature_importance,
        "feature_columns": fit_feature_columns,
        "model_recipe": model_recipe,
    }


def generate_walk_forward_predictions(
    scored_base: pd.DataFrame,
    feature_columns: List[str],
    random_state: int,
    max_windows: int = 4,
    max_train_rows: int = 36000,
    rf_n_estimators: int = 24,
    rf_max_samples: Optional[float] = 0.65,
    rf_n_jobs: int = -1,
    baseline_weight: float = DEFAULT_BASELINE_WEIGHT,
    nonlinear_weight: float = DEFAULT_NONLINEAR_WEIGHT,
) -> Dict[str, object]:
    scored = scored_base.copy()
    scored["walk_forward_baseline_pred"] = np.nan
    scored["walk_forward_pred"] = np.nan
    unique_dates = sorted(scored["date"].dropna().unique().tolist())
    if len(unique_dates) < 90:
        return {
            "scored": scored,
            "metrics": pd.DataFrame(),
            "summary": {
                "enabled": False,
                "message": "not enough dates for walk-forward evaluation",
                "score_source": "composite_score",
                "baseline_weight": float(baseline_weight),
                "nonlinear_weight": float(nonlinear_weight),
            },
        }

    min_train_dates = min(max(60, len(unique_dates) // 3), len(unique_dates) - 10)
    base_step_size = max(10, min(20, len(unique_dates) // 8))
    remaining_dates = max(len(unique_dates) - min_train_dates, 0)
    if max_windows and max_windows > 0:
        step_size = max(base_step_size, int(np.ceil(remaining_dates / max_windows)))
    else:
        step_size = base_step_size
    retrain_windows = 0
    predicted_dates = []

    for start_idx in range(min_train_dates, len(unique_dates), step_size):
        if max_windows and retrain_windows >= max_windows:
            break
        train_dates = set(unique_dates[:start_idx])
        infer_dates = unique_dates[start_idx:start_idx + step_size]
        if not infer_dates:
            continue
        train_chunk = scored[scored["date"].isin(train_dates)].dropna(subset=["label_reg"]).copy()
        if "label_end_date" in train_chunk.columns:
            train_chunk = train_chunk[train_chunk["label_end_date"] < infer_dates[0]].copy()
        infer_chunk = scored[scored["date"].isin(infer_dates)].copy()
        if len(train_chunk) < 100 or infer_chunk.empty:
            continue
        if max_train_rows and len(train_chunk) > max_train_rows:
            train_chunk = train_chunk.sort_values(["date", "stock_code"]).tail(max_train_rows).copy()

        chunk_feature_columns = [
            column for column in feature_columns
            if column in train_chunk.columns and train_chunk[column].replace([np.inf, -np.inf], np.nan).notna().any()
        ]
        if len(chunk_feature_columns) < 5:
            continue

        pipelines = _build_model_pipelines(
            random_state + retrain_windows,
            rf_n_estimators=rf_n_estimators,
            rf_max_samples=rf_max_samples,
            rf_n_jobs=rf_n_jobs,
        )
        x_train = train_chunk[chunk_feature_columns].replace([np.inf, -np.inf], np.nan)
        y_train = train_chunk["label_reg"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            pipelines["baseline"].fit(x_train, y_train)
        pipelines["nonlinear"].fit(x_train, y_train)

        x_infer = infer_chunk[chunk_feature_columns].replace([np.inf, -np.inf], np.nan)
        baseline_pred = _safe_predict(pipelines["baseline"], x_infer)
        nonlinear_pred = _safe_predict(pipelines["nonlinear"], x_infer)
        scored.loc[infer_chunk.index, "walk_forward_baseline_pred"] = baseline_pred
        scored.loc[infer_chunk.index, "walk_forward_pred"] = nonlinear_pred
        retrain_windows += 1
        predicted_dates.extend(infer_dates)

    scored["walk_forward_baseline_pred"] = scored["walk_forward_baseline_pred"].replace([np.inf, -np.inf], np.nan)
    scored["walk_forward_pred"] = scored["walk_forward_pred"].replace([np.inf, -np.inf], np.nan)
    scored["walk_forward_baseline_score"] = scored.groupby("date")["walk_forward_baseline_pred"].rank(pct=True)
    scored["walk_forward_score"] = scored.groupby("date")["walk_forward_pred"].rank(pct=True)
    oos_mask = scored["walk_forward_pred"].notna() | scored["walk_forward_baseline_pred"].notna()
    scored["walk_forward_composite_score"] = np.nan
    total_weight = max(float(baseline_weight) + float(nonlinear_weight), 1e-9)
    scored.loc[oos_mask, "walk_forward_composite_score"] = (
        scored.loc[oos_mask, "walk_forward_baseline_score"].fillna(0.5) * float(baseline_weight)
        + scored.loc[oos_mask, "walk_forward_score"].fillna(0.5) * float(nonlinear_weight)
    ) / total_weight

    metrics_rows = []
    if scored["walk_forward_baseline_pred"].notna().sum() > 0:
        metrics_rows.append(
            _model_metrics(scored, "walk_forward_baseline_score", "walk_forward_baseline_pred", "walk_forward_baseline")
        )
    if scored["walk_forward_pred"].notna().sum() > 0:
        metrics_rows.append(
            _model_metrics(scored, "walk_forward_score", "walk_forward_pred", "walk_forward_random_forest")
        )
        metrics_rows.append(
            _model_metrics(scored, "walk_forward_composite_score", "walk_forward_pred", "walk_forward_composite")
        )

    predicted_dates = sorted(set(predicted_dates))
    coverage = float(scored["walk_forward_pred"].notna().mean()) if len(scored) > 0 else 0.0
    summary = {
        "enabled": bool(predicted_dates),
        "score_source": "walk_forward_composite_score" if predicted_dates else "composite_score",
        "first_prediction_date": predicted_dates[0] if predicted_dates else None,
        "last_prediction_date": predicted_dates[-1] if predicted_dates else None,
        "retrain_windows": retrain_windows,
        "retrain_interval_dates": step_size,
        "base_retrain_interval_dates": base_step_size,
        "max_retrain_windows": int(max_windows) if max_windows else None,
        "max_train_rows": int(max_train_rows) if max_train_rows else None,
        "rf_n_estimators": int(rf_n_estimators),
        "baseline_weight": float(baseline_weight),
        "nonlinear_weight": float(nonlinear_weight),
        "sampled_walk_forward": bool(step_size > base_step_size or (max_windows and retrain_windows >= max_windows)),
        "coverage_ratio": coverage,
        "oos_enforced": bool(predicted_dates),
    }
    return {
        "scored": scored,
        "metrics": pd.DataFrame(metrics_rows),
        "summary": summary,
    }


def _signals_from_scores(scored: pd.DataFrame, top_n: int, score_col: str = "composite_score") -> pd.DataFrame:
    cols = [
        "date",
        "stock_code",
        "stock_name",
        "close",
        "label_reg",
        "split",
        "baseline_pred",
        "nonlinear_pred",
        "baseline_score",
        "ml_score",
        "composite_score",
        "walk_forward_baseline_pred",
        "walk_forward_pred",
        "walk_forward_baseline_score",
        "walk_forward_score",
        "walk_forward_composite_score",
        "label_end_date",
        "label_horizon",
    ]
    out = scored[[column for column in cols if column in scored.columns]].copy()
    out["score_source"] = score_col
    preferred_score = pd.to_numeric(out.get(score_col), errors="coerce")
    if score_col.startswith("walk_forward"):
        out["score"] = preferred_score
    else:
        fallback_score = pd.to_numeric(out.get("composite_score"), errors="coerce")
        out["score"] = preferred_score.fillna(fallback_score)
    out["is_oos_score"] = out["score"].notna() if score_col.startswith("walk_forward") else False
    out["daily_rank"] = out.groupby("date")["score"].rank(method="first", ascending=False)
    out["signal"] = (out["daily_rank"] <= top_n).astype(int)
    return out.sort_values(["date", "daily_rank", "stock_code"])


def _summary_dict(
    config: FactorLabConfig,
    raw_df: pd.DataFrame,
    sample: pd.DataFrame,
    feature_columns: List[str],
    factor_ranking: pd.DataFrame,
    model_metrics: pd.DataFrame,
) -> Dict[str, object]:
    split_counts = sample.groupby("split").size().to_dict() if "split" in sample.columns else {}
    best_factor = factor_ranking.iloc[0]["factor"] if not factor_ranking.empty else ""
    best_metric = model_metrics.iloc[-1].to_dict() if not model_metrics.empty else {}
    return {
        "run_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": asdict(config),
        "rows_raw": int(len(raw_df)),
        "rows_sample": int(len(sample)),
        "symbols": int(sample["stock_code"].nunique()) if not sample.empty else 0,
        "date_start": str(sample["date"].min()) if not sample.empty else config.start_date,
        "date_end": str(sample["date"].max()) if not sample.empty else config.end_date,
        "feature_count": int(len(feature_columns)),
        "split_counts": {str(k): int(v) for k, v in split_counts.items()},
        "best_factor": str(best_factor),
        "best_model_test_rank_ic": float(best_metric.get("test_rank_ic", 0.0) or 0.0),
        "best_model_test_top20_ret": float(best_metric.get("test_top20_ret", 0.0) or 0.0),
    }


def _write_report(
    report_path: Path,
    summary: Dict[str, object],
    factor_ranking: pd.DataFrame,
    model_metrics: pd.DataFrame,
    feature_importance: pd.DataFrame,
) -> None:
    report_path.write_text(_build_report_text(summary, factor_ranking, model_metrics, feature_importance), encoding="utf-8")


def _build_report_text(
    summary: Dict[str, object],
    factor_ranking: pd.DataFrame,
    model_metrics: pd.DataFrame,
    feature_importance: pd.DataFrame,
) -> str:
    lines = [
        "# Factor Lab Research Report",
        "",
        "## Summary",
        "",
        "- Pool: `%s`" % summary["config"]["pool"],
        "- Label: `%s`" % summary["config"]["label"],
        "- Sample rows: `%s`" % summary["rows_sample"],
        "- Symbols: `%s`" % summary["symbols"],
        "- Feature count: `%s`" % summary["feature_count"],
        "- Best factor: `%s`" % summary["best_factor"],
        "- Model blend: Ridge `%s%%`, RandomForest `%s%%`" % (
            round(float(summary.get("model_recipe", {}).get("baseline_weight", DEFAULT_BASELINE_WEIGHT)) * 100),
            round(float(summary.get("model_recipe", {}).get("nonlinear_weight", DEFAULT_NONLINEAR_WEIGHT)) * 100),
        ),
        "- Research note: %s" % summary.get("research_note", ""),
        "",
        "## Model Metrics",
        "",
        model_metrics.to_markdown(index=False) if not model_metrics.empty else "No model metrics.",
        "",
        "## Top Factors",
        "",
        factor_ranking.head(15).to_markdown(index=False) if not factor_ranking.empty else "No factor ranking.",
        "",
        "## Top Feature Importance",
        "",
        feature_importance.head(20).to_markdown(index=False) if not feature_importance.empty else "No feature importance.",
        "",
        "## Notes",
        "",
        "- Features use current and historical OHLCV/valuation fields only.",
        "- Labels are shifted forward and are not used during feature construction.",
        "- Time split is chronological train/valid/test.",
    ]
    return "\n".join(lines)


def _records(df: pd.DataFrame, limit: Optional[int] = None) -> List[Dict[str, object]]:
    data = df.head(limit).replace([np.inf, -np.inf], np.nan)
    return _json_safe(data.where(pd.notna(data), None).to_dict(orient="records"))


def _score_preview_records(signals: pd.DataFrame, top_n: int, limit: int = 100) -> List[Dict[str, object]]:
    if signals.empty or "date" not in signals.columns:
        return []

    preview = signals.copy()
    preview["score"] = pd.to_numeric(preview.get("score"), errors="coerce")
    preview["daily_rank"] = pd.to_numeric(preview.get("daily_rank"), errors="coerce")
    preview = preview[preview["score"].notna()].copy()
    if preview.empty:
        return []

    latest_date = preview["date"].max()
    latest = preview[preview["date"] == latest_date].copy()
    sort_cols = [column for column in ["signal", "daily_rank", "score", "stock_code"] if column in latest.columns]
    ascending = []
    for column in sort_cols:
        ascending.append(False if column in {"signal", "score"} else True)
    if sort_cols:
        latest = latest.sort_values(sort_cols, ascending=ascending)

    if len(latest) >= limit:
        return _records(latest, limit)

    selected_keys = set(zip(latest.get("date", []), latest.get("stock_code", [])))
    supplemental = preview[
        ~preview.apply(lambda row: (row.get("date"), row.get("stock_code")) in selected_keys, axis=1)
    ].copy()
    if not supplemental.empty:
        supplemental = supplemental.sort_values(
            ["date", "signal", "daily_rank", "score", "stock_code"],
            ascending=[False, False, True, False, True],
        )
        latest = pd.concat([latest, supplemental.head(limit - len(latest))], ignore_index=True, sort=False)

    return _records(latest, limit)


def _metric_cards(model_metrics: pd.DataFrame) -> List[Dict[str, object]]:
    if model_metrics.empty:
        return []
    preferred = model_metrics.loc[model_metrics["model"] == "walk_forward_composite"]
    if preferred.empty:
        preferred = model_metrics.loc[model_metrics["model"] == "composite_score"]
    row = preferred.iloc[0] if not preferred.empty else model_metrics.iloc[-1]
    metric_specs = [
        ("train_rank_ic", "训练 RankIC", "ratio"),
        ("valid_rank_ic", "验证 RankIC", "ratio"),
        ("test_rank_ic", "测试 RankIC", "ratio"),
        ("train_top20_ret", "训练 Top20 收益", "percent"),
        ("valid_top20_ret", "验证 Top20 收益", "percent"),
        ("test_top20_ret", "测试 Top20 收益", "percent"),
    ]
    items = []
    for key, label, fmt in metric_specs:
        items.append(
            {
                "key": key,
                "label": label,
                "value": float(row.get(key, 0.0) or 0.0),
                "format": fmt,
                "note": row.get("model", "composite_score"),
            }
        )
    return items


def _bucket_items(frame: pd.DataFrame, score_col: str) -> List[Dict[str, object]]:
    parts = []
    for _, group in frame.groupby("date"):
        valid = group[[score_col, "label_reg"]].dropna()
        if len(valid) < 5 or valid[score_col].nunique() < 5:
            continue
        ranked = valid.copy()
        ranked["bucket"] = pd.qcut(ranked[score_col].rank(method="first"), 5, labels=False) + 1
        parts.append(ranked)
    if not parts:
        return []
    bucket_df = pd.concat(parts, ignore_index=True)
    overall = float(bucket_df["label_reg"].mean()) if not bucket_df.empty else 0.0
    items = []
    for bucket, group in bucket_df.groupby("bucket"):
        items.append(
            {
                "bucket": "Q%d" % int(bucket),
                "return": float(group["label_reg"].mean()),
                "excess_return": float(group["label_reg"].mean() - overall),
                "win_rate": float((group["label_reg"] > 0).mean()),
                "samples": int(len(group)),
            }
        )
    return items


def _stability_cards(factor_ranking: pd.DataFrame, sample_size: int) -> List[Dict[str, object]]:
    if factor_ranking.empty:
        return []
    row = factor_ranking.iloc[0]
    coverage = float(row["sample_count"] / sample_size) if sample_size > 0 else 0.0
    return [
        {
            "key": "best_factor_coverage",
            "label": "最佳因子覆盖率",
            "value": coverage,
            "format": "percent",
            "note": row["factor"],
        },
        {
            "key": "best_factor_rank_ic",
            "label": "最佳因子 RankIC",
            "value": float(row.get("rank_ic_mean", 0.0) or 0.0),
            "format": "ratio",
            "note": row["factor"],
        },
        {
            "key": "best_factor_recent_rank_ic",
            "label": "近一年 RankIC",
            "value": float(row.get("recent_rank_ic_mean", 0.0) or 0.0),
            "format": "ratio",
            "note": row["factor"],
        },
        {
            "key": "best_factor_monotonicity",
            "label": "分桶单调性",
            "value": float(row.get("monotonicity", 0.0) or 0.0),
            "format": "ratio",
            "note": row["factor"],
        },
    ]


def _feature_importance_records(
    feature_importance: pd.DataFrame,
    feature_groups: Dict[str, List[str]],
) -> List[Dict[str, object]]:
    group_lookup = {}
    for group_name, features in feature_groups.items():
        for feature in features:
            group_lookup[feature] = group_name
    preferred = feature_importance[feature_importance["model"] == "random_forest"].copy()
    base = preferred if not preferred.empty else feature_importance.copy()
    base = base.sort_values("importance", ascending=False).head(30).copy()
    base["group"] = base["feature"].map(group_lookup).fillna("other")
    return _records(base[["feature", "importance", "group"]], 30)


def _factor_weight_records(
    feature_importance: pd.DataFrame,
    factor_ranking: pd.DataFrame,
    feature_groups: Dict[str, List[str]],
    model_recipe: Dict[str, object],
    limit: int = 20,
) -> List[Dict[str, object]]:
    if feature_importance.empty:
        return []

    group_lookup = {}
    for group_name, features in feature_groups.items():
        for feature in features:
            group_lookup[feature] = group_name

    pivot = feature_importance.pivot_table(
        index="feature",
        columns="model",
        values="importance",
        aggfunc="sum",
        fill_value=0.0,
    )
    rf = pivot["random_forest"] if "random_forest" in pivot.columns else pd.Series(0.0, index=pivot.index)
    ridge = pivot["ridge_abs_coef"] if "ridge_abs_coef" in pivot.columns else pd.Series(0.0, index=pivot.index)
    baseline_weight = float(model_recipe.get("baseline_weight", DEFAULT_BASELINE_WEIGHT) or DEFAULT_BASELINE_WEIGHT)
    nonlinear_weight = float(model_recipe.get("nonlinear_weight", DEFAULT_NONLINEAR_WEIGHT) or DEFAULT_NONLINEAR_WEIGHT)
    blended = ridge * baseline_weight + rf * nonlinear_weight
    blended = blended / max(float(blended.sum()), 1e-12)

    ranking_lookup = {
        str(row["factor"]): row.to_dict()
        for _, row in factor_ranking.iterrows()
    } if not factor_ranking.empty else {}

    rows = []
    for feature, weight in blended.sort_values(ascending=False).head(limit).items():
        ranking = ranking_lookup.get(str(feature), {})
        direction = "long" if float(ranking.get("rank_ic_mean", 0.0) or 0.0) >= 0 else "short"
        rows.append(
            {
                "feature": str(feature),
                "name_cn": _factor_name_cn(str(feature)),
                "group": group_lookup.get(str(feature), "other"),
                "weight": float(weight),
                "importance": float(weight),
                "direction": direction,
                "direction_text": _direction_text(direction),
                "explanation": _factor_plain_explanation(str(feature)),
                "rank_ic": float(ranking.get("rank_ic_mean", 0.0) or 0.0),
                "recent_rank_ic": float(ranking.get("recent_rank_ic_mean", 0.0) or 0.0),
                "source": "本轮验证集调权后的模型解释权重",
            }
        )
    return _json_safe(rows)


def _factor_ranking_records(factor_ranking: pd.DataFrame, sample_size: int) -> List[Dict[str, object]]:
    if factor_ranking.empty:
        return []
    frame = factor_ranking.copy()
    frame["score"] = frame["factor_score"]
    frame["ic"] = frame["ic_mean"]
    frame["rank_ic"] = frame["rank_ic_mean"]
    frame["coverage"] = frame["sample_count"] / max(sample_size, 1)
    frame["stability"] = frame["recent_rank_ic_mean"]
    frame["direction"] = np.where(frame["rank_ic_mean"] >= 0, "long", "short")
    return _records(frame[["factor", "score", "ic", "rank_ic", "coverage", "stability", "direction"]], 50)


def _external_factor_ideas(mining_report: Dict[str, object]) -> List[Dict[str, object]]:
    promoted = set(mining_report.get("promoted_factors", []) or [])
    ideas = [
        {
            "idea_id": "risk_adjusted_momentum",
            "name_cn": "风险调整动量",
            "plain_text": "不是只看涨得快，还要看这段上涨是不是付出了过高波动。",
            "status": "included_this_run" if "risk_adjusted_mom_20d" in promoted else "tested_this_run",
            "source_type": "经典动量/低波动研究启发",
            "mapped_factor": "risk_adjusted_mom_20d",
        },
        {
            "idea_id": "liquidity_confirmed_momentum",
            "name_cn": "成交确认动量",
            "plain_text": "价格走强同时成交放大，通常比无量上涨更值得检验。",
            "status": "included_this_run" if "liquidity_momentum_20d" in promoted else "tested_this_run",
            "source_type": "量价结构研究启发",
            "mapped_factor": "liquidity_momentum_20d",
        },
        {
            "idea_id": "low_volatility_momentum",
            "name_cn": "低波动动量",
            "plain_text": "优先看走势强但波动不过度失控的股票。",
            "status": "included_this_run" if "low_vol_momentum_20d" in promoted else "tested_this_run",
            "source_type": "低波动/质量动量研究启发",
            "mapped_factor": "low_vol_momentum_20d",
        },
    ]
    return ideas


def _build_run_difference_notes(previous: Dict[str, object], summary: Dict[str, object], mining_report: Dict[str, object]) -> Dict[str, object]:
    previous_summary = previous.get("summary", {}) if isinstance(previous, dict) else {}
    reasons = []
    if not previous_summary:
        reasons.append("这是当前目录下第一份可比较的新式研究报告。")
    else:
        for key, label in [
            ("start_date", "开始日期"),
            ("end_date", "结束日期"),
            ("pool", "股票池"),
            ("label", "收益标签"),
            ("top_n", "Top N"),
            ("max_symbols", "样本上限"),
        ]:
            old_value = previous_summary.get(key)
            new_value = summary.get(key)
            if old_value != new_value:
                reasons.append(f"{label}从 {old_value or '未记录'} 改为 {new_value or '未记录'}。")
    promoted = mining_report.get("promoted", 0)
    tested = mining_report.get("tested", 0)
    reasons.append(f"本轮重新测试 {tested} 个候选组合因子，{promoted} 个进入训练。")
    reasons.append("模型融合比例每次都会在验证集重新选择，不再固定为单一手写比例。")
    note = "本轮结果来自重新选样、重新挖掘候选因子、重新训练模型和重新调权。"
    return {
        "run_difference_note": note,
        "run_difference_reasons": reasons,
    }


def run_factor_lab(
    raw_df: pd.DataFrame,
    config: FactorLabConfig,
    output_dir: Path = REPORT_ROOT,
    write_latest_summary: bool = True,
) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    previous_result = load_latest_result(output_dir=output_dir)
    run_config_hash = _config_hash(config)

    sample, feature_columns, feature_groups = build_model_sample(raw_df, target_label=config.label, winsorize=False)
    sample = sample[(sample["date"] >= config.start_date) & (sample["date"] <= config.end_date)].copy()
    sample = split_by_time(sample)
    sample = winsorize_features(sample, feature_columns, fit_split="train")
    sample, feature_columns, discovered_groups, mining_report = mine_candidate_factors(sample, feature_columns)
    if discovered_groups.get("discovered"):
        feature_groups = dict(feature_groups)
        feature_groups["discovered"] = discovered_groups["discovered"]
        sample = winsorize_features(sample, feature_columns, fit_split="train")
    if len(sample) < 80:
        raise ValueError("Factor Lab sample too small after feature/label preparation: %d rows" % len(sample))
    if len(feature_columns) < 5:
        raise ValueError("Factor Lab needs at least 5 usable features, got %d" % len(feature_columns))

    factor_ranking = evaluate_factors(sample, feature_columns)
    model_bundle = train_models(
        sample,
        feature_columns,
        random_state=config.random_state,
        rf_n_estimators=config.rf_n_estimators,
        rf_max_samples=config.rf_max_samples,
        rf_n_jobs=config.rf_n_jobs,
    )
    walk_forward_bundle = generate_walk_forward_predictions(
        model_bundle["scored"],
        model_bundle["feature_columns"],
        random_state=config.random_state,
        max_windows=config.walk_forward_max_windows,
        max_train_rows=config.walk_forward_max_train_rows,
        rf_n_estimators=config.walk_forward_rf_n_estimators,
        rf_max_samples=config.rf_max_samples,
        rf_n_jobs=config.rf_n_jobs,
        baseline_weight=float(model_bundle["model_recipe"].get("baseline_weight", DEFAULT_BASELINE_WEIGHT)),
        nonlinear_weight=float(model_bundle["model_recipe"].get("nonlinear_weight", DEFAULT_NONLINEAR_WEIGHT)),
    )
    scored = walk_forward_bundle["scored"]
    model_metrics = pd.concat(
        [model_bundle["metrics"], walk_forward_bundle["metrics"]],
        ignore_index=True,
        sort=False,
    )
    feature_importance = model_bundle["feature_importance"]
    score_source = walk_forward_bundle["summary"].get("score_source", "composite_score")
    signals = _signals_from_scores(scored, top_n=config.top_n, score_col=score_source)

    bucket_rows = []
    for factor in factor_ranking.head(20)["factor"].tolist() if not factor_ranking.empty else []:
        row = {"factor": factor}
        row.update(_bucket_returns_for_output(sample, factor))
        bucket_rows.append(row)
    bucket_returns = pd.DataFrame(bucket_rows)

    stability = factor_ranking[
        ["factor", "ic_mean", "rank_ic_mean", "ic_positive_ratio", "recent_rank_ic_mean", "monotonicity"]
    ].copy() if not factor_ranking.empty else pd.DataFrame()

    summary = _summary_dict(config, raw_df, sample, model_bundle["feature_columns"], factor_ranking, model_metrics)
    summary["config_hash"] = run_config_hash
    summary["feature_groups"] = feature_groups
    summary["start_date"] = config.start_date
    summary["end_date"] = config.end_date
    summary["pool"] = config.pool
    summary["label"] = config.label
    summary["top_n"] = config.top_n
    summary["max_symbols"] = config.max_symbols
    summary["total_symbols"] = summary["symbols"]
    summary["train_samples"] = int(summary["split_counts"].get("train", 0))
    summary["inference_date"] = summary["generated_at"]
    summary["universe"] = "%s 股票池" % config.pool
    summary["research_note"] = "本次策略体检已更新两套 ML 策略卡、专家模式研究摘要和详细回测结果。"
    summary["walk_forward"] = walk_forward_bundle["summary"]
    summary["score_source"] = score_source
    summary["model_recipe"] = {
        "baseline_model": "Ridge 线性基线",
        "nonlinear_model": "RandomForest 非线性模型",
        "baseline_weight": float(model_bundle["model_recipe"].get("baseline_weight", DEFAULT_BASELINE_WEIGHT)),
        "nonlinear_weight": float(model_bundle["model_recipe"].get("nonlinear_weight", DEFAULT_NONLINEAR_WEIGHT)),
        "selection_metric": model_bundle["model_recipe"].get("selection_metric"),
        "selection_split": model_bundle["model_recipe"].get("selection_split"),
        "valid_rank_ic": model_bundle["model_recipe"].get("valid_rank_ic"),
        "valid_top20_ret": model_bundle["model_recipe"].get("valid_top20_ret"),
        "reason": model_bundle["model_recipe"].get("reason"),
    }
    summary["research_note"] = (
        f"本次自动测试 {mining_report.get('tested', 0)} 个候选组合因子，"
        f"{mining_report.get('promoted', 0)} 个进入模型；"
        f"融合比例为线性 {summary['model_recipe']['baseline_weight']:.0%}、非线性 {summary['model_recipe']['nonlinear_weight']:.0%}。"
    )
    summary.update(_build_run_difference_notes(previous_result, summary, mining_report))
    run_manifest = {
        "run_id": summary["run_id"],
        "config": asdict(config),
        "config_hash": run_config_hash,
        "score_source": score_source,
        "feature_columns": list(model_bundle["feature_columns"]),
        "feature_groups": feature_groups,
        "oos_start_date": str(signals.loc[signals["is_oos_score"], "date"].min()) if not signals.empty and "is_oos_score" in signals else None,
        "oos_end_date": str(signals.loc[signals["is_oos_score"], "date"].max()) if not signals.empty and "is_oos_score" in signals else None,
        "generated_at": summary["generated_at"],
    }
    signals["run_id"] = summary["run_id"]
    signals["config_hash"] = run_config_hash

    with FACTOR_LAB_WRITE_LOCK:
        _atomic_to_csv(factor_ranking, output_dir / "factor_ranking.csv")
        _atomic_to_csv(model_metrics, output_dir / "model_metrics.csv")
        _atomic_to_csv(feature_importance, output_dir / "feature_importance.csv")
        _atomic_to_csv(pd.DataFrame(mining_report.get("candidates", [])), output_dir / "candidate_factors.csv")
        _atomic_to_csv(bucket_returns, output_dir / "bucket_returns.csv")
        _atomic_to_csv(stability, output_dir / "stability.csv")
        _atomic_to_csv(signals, output_dir / "latest_scores.csv")
        _atomic_to_csv(scored, output_dir / "training_sample_scored.csv")
        _atomic_joblib_dump(
            {
                "model": model_bundle["nonlinear_model"],
                "baseline_model": model_bundle["baseline_model"],
                "feature_columns": model_bundle["feature_columns"],
                "config": asdict(config),
                "config_hash": run_config_hash,
                "run_id": summary["run_id"],
                "feature_groups": feature_groups,
                "model_recipe": summary["model_recipe"],
            },
            output_dir / "latest_model.joblib",
        )
        _atomic_write_json(output_dir / "latest_manifest.json", run_manifest)

    result = {
        "summary": summary,
        "factor_ranking": _factor_ranking_records(factor_ranking, len(sample)),
        "feature_importance": _feature_importance_records(feature_importance, feature_groups),
        "factor_weights": _factor_weight_records(feature_importance, factor_ranking, feature_groups, summary["model_recipe"]),
        "research_iteration": {
            "mode": "sample_prescreen + candidate_factor_mining + validation_blend_tuning",
            "actions": mining_report.get("actions", []),
            "tested_candidate_factors": int(mining_report.get("tested", 0) or 0),
            "promoted_candidate_factors": int(mining_report.get("promoted", 0) or 0),
            "promotion_cutoff": mining_report.get("promotion_cutoff"),
            "candidates": mining_report.get("candidates", []),
            "model_recipe": summary["model_recipe"],
            "external_research_status": "已预留外部论文/帖子因子队列；当前一键运行先使用本地可审计候选库，避免 live web 噪声直接污染结果。",
        },
        "external_factor_ideas": _external_factor_ideas(mining_report),
        "model_metrics": _metric_cards(model_metrics),
        "bucket_returns": _bucket_items(scored, score_source),
        "stability": _stability_cards(factor_ranking, len(sample)),
        "scores_preview": _score_preview_records(signals, config.top_n, 100),
        "artifacts": {
            "report_dir": str(output_dir),
            "manifest_json": str(output_dir / "latest_manifest.json"),
            "factor_ranking_csv": str(output_dir / "factor_ranking.csv"),
            "feature_importance_csv": str(output_dir / "feature_importance.csv"),
            "candidate_factors_csv": str(output_dir / "candidate_factors.csv"),
            "model_metrics_csv": str(output_dir / "model_metrics.csv"),
            "bucket_returns_csv": str(output_dir / "bucket_returns.csv"),
            "stability_csv": str(output_dir / "stability.csv"),
            "scores_csv": str(output_dir / "latest_scores.csv"),
            "model_joblib": str(output_dir / "latest_model.joblib"),
            "report_md": str(output_dir / "research_report.md"),
        },
    }
    result = _json_safe(result)
    if write_latest_summary:
        with FACTOR_LAB_WRITE_LOCK:
            _atomic_write_json(output_dir / "latest_summary.json", result)
    with FACTOR_LAB_WRITE_LOCK:
        _atomic_write_text(
            output_dir / "research_report.md",
            _build_report_text(summary, factor_ranking, model_metrics, feature_importance),
        )
    return result


def _bucket_returns_for_output(sample: pd.DataFrame, factor: str) -> Dict[str, float]:
    label = "label_reg"
    rows = []
    for _, group in sample.groupby("date"):
        valid = group[[factor, label]].dropna()
        if len(valid) < 5 or valid[factor].nunique() < 5:
            continue
        try:
            valid = valid.copy()
            valid["bucket"] = pd.qcut(valid[factor].rank(method="first"), 5, labels=False) + 1
            rows.append(valid)
        except ValueError:
            continue
    if not rows:
        return {}
    bucket_df = pd.concat(rows, ignore_index=True)
    return {
        "bucket_%d" % int(bucket): float(value)
        for bucket, value in bucket_df.groupby("bucket")[label].mean().to_dict().items()
    }


def load_latest_result(output_dir: Path = REPORT_ROOT) -> Dict[str, object]:
    path = output_dir / "latest_summary.json"
    if not path.exists():
        return {
            "summary": {"status": "missing", "message": "No Factor Lab result has been generated yet."},
            "run_readiness": None,
            "factor_ranking": [],
            "feature_importance": [],
            "model_metrics": [],
            "bucket_returns": [],
            "stability": [],
            "backtest": None,
            "strategy_backtests": {},
            "backtest_compare": {"factors": []},
            "scores_preview": [],
            "artifacts": {"report_dir": str(output_dir)},
        }
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)
