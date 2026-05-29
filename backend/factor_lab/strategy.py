from pathlib import Path
from typing import Optional, Union

import numpy as np
import pandas as pd

from .data_prep import FEATURE_COLUMNS, generate_features

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_ROOT = PROJECT_ROOT / "results" / "quant-factor-mining" / "reports" / "factor_lab"
LATEST_MODEL_PATH = REPORT_ROOT / "latest_model.joblib"
LATEST_SCORES_PATH = REPORT_ROOT / "latest_scores.csv"
LATEST_MANIFEST_PATH = REPORT_ROOT / "latest_manifest.json"


class FactorLabScoringError(RuntimeError):
    """Raised when a Factor Lab strategy cannot use a verified scoring artifact."""


def _load_manifest(manifest_path: Path = LATEST_MANIFEST_PATH) -> Optional[dict]:
    if not manifest_path.exists():
        return None
    try:
        import json

        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        return None
    return manifest if isinstance(manifest, dict) else None


def get_factor_lab_artifact_readiness(report_root: Path = REPORT_ROOT) -> dict:
    manifest_path = report_root / "latest_manifest.json"
    scores_path = report_root / "latest_scores.csv"
    model_path = report_root / "latest_model.joblib"
    manifest = _load_manifest(manifest_path)
    if not manifest:
        return {
            "ready": False,
            "status": "missing",
            "message": "缺少 Factor Lab manifest，请先运行一次因子体检。",
        }

    run_id = str(manifest.get("run_id") or "")
    config_hash = str(manifest.get("config_hash") or "")
    if not run_id or not config_hash:
        return {
            "ready": False,
            "status": "incompatible",
            "message": "Factor Lab manifest 缺少 run_id/config_hash，请重新运行因子体检。",
        }
    if not scores_path.exists():
        return {
            "ready": False,
            "status": "missing",
            "message": "缺少 Factor Lab scores artifact，请先运行一次因子体检。",
            "run_id": run_id,
            "config_hash": config_hash,
        }

    try:
        scores = pd.read_csv(scores_path, dtype={"stock_code": str})
    except Exception:
        return {
            "ready": False,
            "status": "incompatible",
            "message": "Factor Lab scores artifact 无法读取，请重新运行因子体检。",
            "run_id": run_id,
            "config_hash": config_hash,
        }

    required_columns = {"date", "stock_code", "score", "run_id", "config_hash", "is_oos_score"}
    if scores.empty or not required_columns.issubset(scores.columns):
        return {
            "ready": False,
            "status": "incompatible",
            "message": "Factor Lab scores artifact 字段不完整，请重新运行因子体检。",
            "run_id": run_id,
            "config_hash": config_hash,
        }

    matching = scores[
        (scores["run_id"].astype(str) == run_id)
        & (scores["config_hash"].astype(str) == config_hash)
    ].copy()
    if matching.empty:
        return {
            "ready": False,
            "status": "stale",
            "message": "Factor Lab scores 与最新 manifest 不匹配，请重新运行因子体检。",
            "run_id": run_id,
            "config_hash": config_hash,
        }

    oos_mask = matching["is_oos_score"]
    if oos_mask.dtype == object:
        oos_mask = oos_mask.astype(str).str.lower().isin(["true", "1", "yes"])
    else:
        oos_mask = oos_mask.astype(bool)
    oos_scores = matching[oos_mask].copy()
    if oos_scores.empty:
        return {
            "ready": False,
            "status": "incompatible",
            "message": "Factor Lab scores 缺少样本外分数，拒绝用于 ML 策略。",
            "run_id": run_id,
            "config_hash": config_hash,
        }

    return {
        "ready": True,
        "status": "ready",
        "message": "Factor Lab scoring artifact 可用于 ML 策略。",
        "run_id": run_id,
        "config_hash": config_hash,
        "generated_at": manifest.get("generated_at"),
        "oos_start_date": manifest.get("oos_start_date"),
        "oos_end_date": manifest.get("oos_end_date"),
        "score_rows": int(len(matching)),
        "oos_score_rows": int(len(oos_scores)),
        "model_available": model_path.exists(),
    }


def _merge_persisted_scores(
    df: pd.DataFrame,
    scores_path: Path = LATEST_SCORES_PATH,
    manifest_path: Path = LATEST_MANIFEST_PATH,
) -> Optional[pd.DataFrame]:
    manifest = _load_manifest(manifest_path)
    if not manifest:
        return None
    expected_run_id = str(manifest.get("run_id") or "")
    expected_config_hash = str(manifest.get("config_hash") or "")
    if not expected_run_id or not expected_config_hash:
        return None
    if not scores_path.exists():
        return None
    try:
        scores = pd.read_csv(scores_path, dtype={"stock_code": str})
    except Exception:
        return None
    if scores.empty or "date" not in scores.columns or "stock_code" not in scores.columns:
        return None
    if "run_id" not in scores.columns or "config_hash" not in scores.columns:
        return None
    scores = scores[
        (scores["run_id"].astype(str) == expected_run_id)
        & (scores["config_hash"].astype(str) == expected_config_hash)
    ].copy()
    if scores.empty:
        return None
    if "is_oos_score" in scores.columns:
        oos_mask = scores["is_oos_score"]
        if oos_mask.dtype == object:
            oos_mask = oos_mask.astype(str).str.lower().isin(["true", "1", "yes"])
        else:
            oos_mask = oos_mask.astype(bool)
        scores = scores[oos_mask].copy()
        if scores.empty:
            return None
    else:
        return None
    score_cols = ["date", "stock_code", "score", "composite_score", "ml_score", "daily_rank", "is_oos_score"]
    score_cols = [column for column in score_cols if column in scores.columns]
    merged = df.drop(columns=["signal", "score"], errors="ignore").merge(
        scores[score_cols],
        on=["date", "stock_code"],
        how="left",
    )
    score = merged.get("score")
    if score is None:
        score = merged.get("composite_score")
    merged["score"] = pd.to_numeric(score, errors="coerce")
    return merged


def _score_with_latest_model(
    df: pd.DataFrame,
    model_path: Path = LATEST_MODEL_PATH,
    manifest_path: Path = LATEST_MANIFEST_PATH,
) -> Optional[pd.DataFrame]:
    manifest = _load_manifest(manifest_path)
    if not manifest:
        return None
    expected_run_id = str(manifest.get("run_id") or "")
    expected_config_hash = str(manifest.get("config_hash") or "")
    if not expected_run_id or not expected_config_hash:
        return None
    if not model_path.exists():
        return None
    try:
        import joblib

        bundle = joblib.load(model_path)
        if str(bundle.get("run_id") or "") != expected_run_id:
            return None
        if str(bundle.get("config_hash") or "") != expected_config_hash:
            return None
        model = bundle["model"]
        baseline_model = bundle.get("baseline_model")
        recipe = bundle.get("model_recipe", {}) if isinstance(bundle.get("model_recipe", {}), dict) else {}
        feature_columns = [str(column) for column in bundle.get("feature_columns", FEATURE_COLUMNS)]
    except Exception:
        return None

    features, _ = generate_features(df)
    try:
        from .pipeline import _candidate_factor_recipes
        for name, _, dependencies, builder in _candidate_factor_recipes():
            if name in feature_columns and name not in features.columns:
                if set(dependencies).issubset(features.columns):
                    features[name] = builder(features).replace([np.inf, -np.inf], np.nan)
    except Exception:
        pass

    missing_features = [column for column in feature_columns if column not in features.columns]
    if missing_features or not feature_columns:
        return None

    scored = features.copy()
    try:
        scored["ml_pred"] = model.predict(scored[feature_columns])
        if baseline_model is not None:
            scored["baseline_pred"] = baseline_model.predict(scored[feature_columns])
    except Exception:
        return None
    scored["ml_score"] = scored.groupby("date")["ml_pred"].rank(pct=True)
    if "baseline_pred" in scored.columns:
        baseline_weight = float(recipe.get("baseline_weight", 0.35) or 0.35)
        nonlinear_weight = float(recipe.get("nonlinear_weight", 0.65) or 0.65)
        total_weight = max(baseline_weight + nonlinear_weight, 1e-9)
        scored["baseline_score"] = scored.groupby("date")["baseline_pred"].rank(pct=True)
        scored["score"] = (
            scored["baseline_score"].fillna(0.5) * baseline_weight
            + scored["ml_score"].fillna(0.5) * nonlinear_weight
        ) / total_weight
    else:
        scored["score"] = scored["ml_score"]
    return scored


def _fallback_composite_score(df: pd.DataFrame) -> pd.DataFrame:
    features, _ = generate_features(df)
    scored = features.copy()
    component_specs = [
        ("mom_20d_rank", 0.22),
        ("relative_strength_20d", 0.18),
        ("reversal_5d_rank", 0.12),
        ("volume_ratio_20d_rank", 0.12),
        ("value_pb_rank", 0.14),
        ("volatility_20d_rank", 0.12),
        ("market_breadth_20d", 0.10),
    ]
    score = pd.Series(0.0, index=scored.index)
    total_weight = 0.0
    for column, weight in component_specs:
        if column not in scored.columns:
            continue
        values = pd.to_numeric(scored[column], errors="coerce")
        if column == "volatility_20d_rank":
            values = 1.0 - values
        if values.abs().max(skipna=True) > 2:
            values = values.groupby(scored["date"]).rank(pct=True)
        score = score + values.fillna(0.5) * weight
        total_weight += weight
    scored["score"] = score / max(total_weight, 1e-9)
    return scored


def _build_ml_signals(df: pd.DataFrame, top_n: int, min_score: float = 0.0) -> pd.DataFrame:
    scored = _merge_persisted_scores(df)
    if scored is None or scored["score"].notna().sum() == 0:
        scored = _score_with_latest_model(df)
    if scored is None or scored["score"].notna().sum() == 0:
        raise FactorLabScoringError(
            "Factor Lab scoring artifact is missing, stale, or incompatible. "
            "Run /api/factor-lab/run before using ML factor strategies."
        )

    out = scored.copy()
    out["score"] = pd.to_numeric(out["score"], errors="coerce").replace([np.inf, -np.inf], np.nan)
    out["daily_rank"] = out.groupby("date")["score"].rank(method="first", ascending=False)
    out["signal"] = ((out["daily_rank"] <= top_n) & (out["score"] >= min_score)).astype(int)
    return out


def build_ml_factor_signal_func(
    artifact_ref: Union[str, Path],
    *,
    top_n: int,
    min_score: float = 0.0,
):
    """Build an ML signal function pinned to an immutable Factor Lab artifact dir."""
    artifact_dir = Path(artifact_ref)
    scores_path = artifact_dir / "latest_scores.csv"
    model_path = artifact_dir / "latest_model.joblib"
    manifest_path = artifact_dir / "latest_manifest.json"

    def _signal_func(df: pd.DataFrame) -> pd.DataFrame:
        scored = _merge_persisted_scores(df, scores_path=scores_path, manifest_path=manifest_path)
        if scored is None or scored["score"].notna().sum() == 0:
            scored = _score_with_latest_model(df, model_path=model_path, manifest_path=manifest_path)
        if scored is None or scored["score"].notna().sum() == 0:
            raise FactorLabScoringError(
                f"Factor Lab version artifact is missing, stale, or incompatible: {artifact_dir}"
            )
        out = scored.copy()
        out["score"] = pd.to_numeric(out["score"], errors="coerce").replace([np.inf, -np.inf], np.nan)
        out["daily_rank"] = out.groupby("date")["score"].rank(method="first", ascending=False)
        out["signal"] = ((out["daily_rank"] <= top_n) & (out["score"] >= min_score)).astype(int)
        return out

    return _signal_func


def calculate_ml_factor_ranker_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Daily top-N ML factor ranking strategy."""
    return _build_ml_signals(df, top_n=3, min_score=0.0)


def calculate_ml_factor_filter_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Stricter ML score filter for concentrated portfolios."""
    return _build_ml_signals(df, top_n=5, min_score=0.60)
