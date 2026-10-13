"""Fold-local research. Neither recipe selection nor transforms see inference labels."""
import numpy as np
import pandas as pd

from research_contracts import EVALUATION_VERSION


def generate_predictions(frame, features, random_state, max_windows=0, max_train_rows=80000,
                         rf_n_estimators=24, rf_max_samples=0.65, rf_n_jobs=1, enable_hist_gradient_boosting=False, **ignored):
    from .pipeline import mine_candidate_factors, train_models, _model_metrics, _blend_score_multi
    scored = frame.copy()
    names = ["baseline", "", "v2"]
    for name in names:
        col = "walk_forward_" + (name + "_" if name else "") + "pred"
        scored[col] = np.nan
    scored["walk_forward_composite_score"] = np.nan
    dates = sorted(scored.date.dropna().unique())
    folds = []
    latest = None
    for index in range(160, len(dates), 20):
        if max_windows and len(folds) >= max_windows:
            break
        train_dates, valid_dates, infer_dates = dates[index-160:index-40], dates[index-40:index], dates[index:index+20]
        historical = scored[scored.date.isin(train_dates + valid_dates)].copy()
        historical["split"] = np.where(historical.date.isin(train_dates), "train", "valid")
        historical = historical.dropna(subset=["label_reg", "label_end_date"])
        historical = historical[historical.label_end_date < infer_dates[0]]
        historical = historical[~((historical.split == "train") & (historical.label_end_date >= valid_dates[0]))]
        if len(historical[historical.split == "train"]) < 100:
            continue
        if max_train_rows and len(historical) > max_train_rows:
            raise ValueError("滚动训练超过行预算，请减少标的；不能通过删除窗口或改变折边界伪造覆盖率。")
        historical, selected, _, mining = mine_candidate_factors(historical, list(features))
        infer = scored[scored.date.isin(infer_dates)].copy()
        from .pipeline import _candidate_factor_recipes
        for name, _, dependencies, builder in _candidate_factor_recipes():
            if name in selected and name not in infer and set(dependencies).issubset(infer.columns):
                infer[name] = builder(infer)
        bounds = {}
        for feature in selected:
            values = historical.loc[historical.split == "train", feature].dropna()
            if not values.empty:
                lo, hi = values.quantile(.01), values.quantile(.99)
                if lo < hi:
                    historical[feature] = historical[feature].clip(lo, hi)
                    infer[feature] = infer[feature].clip(lo, hi)
                    bounds[feature] = [float(lo), float(hi)]
        infer["split"] = "test"
        # Remove labels before any fitting/selection function is invoked.
        infer["label_reg"] = np.nan
        combined = pd.concat([historical, infer], sort=False)
        bundle = train_models(combined, selected, random_state + len(folds), rf_n_estimators, rf_max_samples, 1, enable_hist_gradient_boosting=enable_hist_gradient_boosting)
        predictions = bundle["scored"].loc[infer.index]
        for source, target in [("baseline_pred", "walk_forward_baseline_pred"), ("nonlinear_pred", "walk_forward_pred"), ("nonlinear_v2_pred", "walk_forward_v2_pred")]:
            scored.loc[infer.index, target] = predictions[source]
        recipe = bundle["model_recipe"]
        scored.loc[infer.index, "walk_forward_composite_score"] = _blend_score_multi(predictions, recipe["baseline_weight"], recipe["nonlinear_weight"], recipe.get("nonlinear_v2_weight", 0))
        scored.loc[infer.index, "fold_id"] = len(folds)
        scored.loc[infer.index, "recipe_as_of"] = valid_dates[-1]
        folds.append({"fold_id": len(folds), "train_start": train_dates[0], "train_end": train_dates[-1], "validation_end": valid_dates[-1], "prediction_start": infer_dates[0], "prediction_end": infer_dates[-1], "validation_start": valid_dates[0], "feature_columns": selected, "model_recipe": recipe, "mining": mining})
        latest = {**bundle, "feature_bounds": bounds, "trained_through": valid_dates[-1]}
    for source, target in [("walk_forward_baseline_pred", "walk_forward_baseline_score"), ("walk_forward_pred", "walk_forward_score"), ("walk_forward_v2_pred", "walk_forward_v2_score")]:
        scored[target] = scored.groupby("date")[source].rank(pct=True)
    predicted = scored.loc[scored.walk_forward_composite_score.notna(), "date"]
    metrics = []
    if len(predicted):
        metrics = [_model_metrics(scored, "walk_forward_composite_score", "walk_forward_pred", "walk_forward_composite")]
    return {"scored": scored, "metrics": pd.DataFrame(metrics), "latest_bundle": latest,
            "summary": {"enabled": bool(len(predicted)), "evaluation_version": EVALUATION_VERSION,
                        "score_source": "walk_forward_composite_score", "first_prediction_date": predicted.min() if len(predicted) else None,
                        "last_prediction_date": predicted.max() if len(predicted) else None, "retrain_windows": len(folds),
                        "retrain_interval_dates": 20, "train_dates": 120, "validation_dates": 40, "prediction_dates": 20,
                        "coverage_ratio": float(scored.walk_forward_composite_score.notna().mean()), "oos_enforced": True,
                        "max_retrain_windows": max_windows or None, "sampled_walk_forward": bool(max_windows and len(folds) >= max_windows),
                        "folds": folds, "message": "需要至少160个交易日预热；预算截断时明确展示未预测区间。" if len(predicted) else "无法完成样本外评估：需要超过160个交易日及足够的历史训练样本。"}}
