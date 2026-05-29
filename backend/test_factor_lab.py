import json

import numpy as np
import pandas as pd
import pytest

from factor_lab.data_prep import add_labels, standardize_market_frame
from factor_lab.pipeline import FactorLabConfig, generate_walk_forward_predictions, run_factor_lab
from factor_lab.strategy import FactorLabScoringError, _build_ml_signals, _merge_persisted_scores, _score_with_latest_model
from strategy_registry import STRATEGY_REGISTRY


def test_standardize_market_frame_derives_missing_columns():
    raw = pd.DataFrame(
        [
            {
                "date": "2024-01-02",
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "open": 100.0,
                "high": 106.0,
                "low": 99.0,
                "close": 105.0,
                "volume": 1000,
                "amount": 105000,
                "pct_chg": 5.0,
                "pe": 20.0,
                "pb": 5.0,
            },
            {
                "date": "2024-01-03",
                "stock_code": "600519",
                "stock_name": "贵州茅台",
                "open": 106.0,
                "high": 108.0,
                "low": 104.0,
                "close": 107.0,
                "volume": 1100,
                "amount": 117700,
                "pct_chg": 1.9,
                "pe": 19.5,
                "pb": 4.9,
            },
        ]
    )

    normalized = standardize_market_frame(raw)

    assert {"turnover_rate", "amplitude", "prev_close", "intraday_ret", "open_gap"}.issubset(normalized.columns)
    assert normalized.loc[0, "prev_close"] == 100.0
    assert normalized.loc[1, "prev_close"] == 105.0
    assert normalized.loc[1, "open_gap"] == 106.0 / 105.0 - 1.0
    assert normalized["amplitude"].notna().all()


def test_add_labels_creates_shifted_forward_returns():
    feature_df = pd.DataFrame(
        [
            {"date": "2024-01-02", "stock_code": "000001", "stock_name": "平安银行", "open": 10.0, "close": 10.0},
            {"date": "2024-01-03", "stock_code": "000001", "stock_name": "平安银行", "open": 10.5, "close": 11.0},
            {"date": "2024-01-04", "stock_code": "000001", "stock_name": "平安银行", "open": 11.0, "close": 10.0},
            {"date": "2024-01-05", "stock_code": "000001", "stock_name": "平安银行", "open": 9.8, "close": 10.3},
            {"date": "2024-01-08", "stock_code": "000001", "stock_name": "平安银行", "open": 10.4, "close": 10.5},
            {"date": "2024-01-09", "stock_code": "000001", "stock_name": "平安银行", "open": 10.6, "close": 10.8},
        ]
    )

    labeled = add_labels(feature_df, target_label="next_close_ret")

    first = labeled.iloc[0]
    assert round(first["next_open_ret"], 6) == round(10.5 / 10.0 - 1.0, 6)
    assert round(first["next_close_ret"], 6) == round(11.0 / 10.0 - 1.0, 6)
    assert round(first["next_5d_ret"], 6) == round(10.8 / 10.0 - 1.0, 6)
    assert first["label_cls"] == 1


def test_ml_factor_strategies_registered():
    ranker = STRATEGY_REGISTRY["ml_factor_ranker"]
    filt = STRATEGY_REGISTRY["ml_factor_filter"]

    assert ranker.category == "Factor Lab"
    assert ranker.signal_type == "ranking"
    assert filt.holding_policy == "hold_while_selected"


def test_run_factor_lab_emits_walk_forward_summary(tmp_path):
    rows = []
    dates = pd.bdate_range("2024-01-01", periods=120)
    for stock_idx, code in enumerate(["000001", "000002", "000003", "000004", "000005", "000006"]):
        price = 10.0 + stock_idx
        for idx, dt in enumerate(dates):
            drift = 0.002 * ((stock_idx % 3) - 1) + 0.0005 * (idx % 5)
            price = price * (1 + drift)
            rows.append(
                {
                    "date": dt.strftime("%Y-%m-%d"),
                    "stock_code": code,
                    "stock_name": code,
                    "open": price * 0.995,
                    "high": price * 1.01,
                    "low": price * 0.99,
                    "close": price,
                    "volume": 100000 + stock_idx * 5000 + idx * 100,
                    "amount": (100000 + stock_idx * 5000 + idx * 100) * price,
                    "pct_chg": drift * 100,
                    "turn": 1.0 + stock_idx * 0.1,
                    "pe": 10.0 + stock_idx,
                    "pb": 1.0 + stock_idx * 0.1,
                    "ps": 2.0 + stock_idx * 0.1,
                    "pcf": 5.0 + stock_idx * 0.2,
                }
            )

    result = run_factor_lab(
        pd.DataFrame(rows),
        FactorLabConfig(
            start_date="2024-01-01",
            end_date=dates[-1].strftime("%Y-%m-%d"),
            pool="core",
            label="next_5d_ret",
            top_n=3,
            max_symbols=6,
            random_state=7,
        ),
        output_dir=tmp_path / "factor_lab",
    )

    assert result["summary"]["walk_forward"]["enabled"] is True
    assert result["summary"]["score_source"] == "walk_forward_composite_score"
    assert any(item["key"] == "test_rank_ic" for item in result["model_metrics"])
    assert result["scores_preview"]
    assert result["scores_preview"][0]["daily_rank"] == 1.0
    assert result["summary"]["config_hash"]
    assert (tmp_path / "factor_lab" / "latest_manifest.json").exists()
    assert result["artifacts"]["manifest_json"].endswith("latest_manifest.json")

    scores = pd.read_csv(tmp_path / "factor_lab" / "latest_scores.csv", dtype={"stock_code": str})
    with (tmp_path / "factor_lab" / "latest_manifest.json").open("r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert {"run_id", "config_hash", "is_oos_score"}.issubset(scores.columns)
    assert scores["run_id"].eq(manifest["run_id"]).all()
    assert scores["config_hash"].eq(manifest["config_hash"]).all()


def test_ml_factor_strategy_fails_without_verified_scores(monkeypatch):
    market_df = pd.DataFrame(
        [
            {"date": "2024-01-02", "stock_code": "000001", "stock_name": "平安银行", "open": 10.0, "high": 10.2, "low": 9.8, "close": 10.1, "volume": 1000, "amount": 10100},
            {"date": "2024-01-02", "stock_code": "000002", "stock_name": "万科A", "open": 11.0, "high": 11.2, "low": 10.8, "close": 11.1, "volume": 1000, "amount": 11100},
        ]
    )
    monkeypatch.setattr("factor_lab.strategy._merge_persisted_scores", lambda df: None)
    monkeypatch.setattr("factor_lab.strategy._score_with_latest_model", lambda df: None)

    with pytest.raises(FactorLabScoringError):
        _build_ml_signals(market_df, top_n=1)


def test_persisted_scores_require_matching_manifest_and_oos(tmp_path):
    market_df = pd.DataFrame(
        [
            {"date": "2024-01-02", "stock_code": "000001", "stock_name": "平安银行"},
            {"date": "2024-01-02", "stock_code": "000002", "stock_name": "万科A"},
        ]
    )
    manifest_path = tmp_path / "latest_manifest.json"
    scores_path = tmp_path / "latest_scores.csv"
    manifest_path.write_text(json.dumps({"run_id": "run-new", "config_hash": "hash-new"}), encoding="utf-8")
    pd.DataFrame(
        [
            {"date": "2024-01-02", "stock_code": "000001", "score": 0.9, "run_id": "run-old", "config_hash": "hash-old", "is_oos_score": True},
            {"date": "2024-01-02", "stock_code": "000002", "score": 0.1, "run_id": "run-old", "config_hash": "hash-old", "is_oos_score": True},
        ]
    ).to_csv(scores_path, index=False)

    assert _merge_persisted_scores(market_df, scores_path=scores_path, manifest_path=manifest_path) is None

    manifest_path.write_text(json.dumps({"run_id": "run-new", "config_hash": "hash-new"}), encoding="utf-8")
    pd.DataFrame(
        [
            {"date": "2024-01-02", "stock_code": "000001", "score": 0.9, "run_id": "run-new", "config_hash": "hash-new", "is_oos_score": False},
            {"date": "2024-01-02", "stock_code": "000002", "score": 0.1, "run_id": "run-new", "config_hash": "hash-new", "is_oos_score": False},
        ]
    ).to_csv(scores_path, index=False)

    assert _merge_persisted_scores(market_df, scores_path=scores_path, manifest_path=manifest_path) is None


def test_latest_model_requires_matching_manifest(tmp_path, monkeypatch):
    import joblib

    manifest_path = tmp_path / "latest_manifest.json"
    model_path = tmp_path / "latest_model.joblib"
    manifest_path.write_text(json.dumps({"run_id": "run-new", "config_hash": "hash-new"}), encoding="utf-8")
    model_path.write_bytes(b"placeholder")
    monkeypatch.setattr(
        joblib,
        "load",
        lambda path: {
            "run_id": "run-old",
            "config_hash": "hash-new",
            "model": object(),
            "feature_columns": ["close"],
        },
    )

    assert _score_with_latest_model(pd.DataFrame(), model_path=model_path, manifest_path=manifest_path) is None


def test_walk_forward_predictions_cap_retrain_windows(monkeypatch):
    rows = []
    dates = pd.bdate_range("2024-01-01", periods=130)
    features = ["f%d" % idx for idx in range(5)]
    for date_idx, dt in enumerate(dates):
        for stock_idx in range(6):
            row = {
                "date": dt.strftime("%Y-%m-%d"),
                "stock_code": "%06d" % stock_idx,
                "label_reg": (stock_idx - 2) * 0.01 + date_idx * 0.0001,
                "label_end_date": dt.strftime("%Y-%m-%d"),
                "split": "test",
            }
            for feature_idx, feature in enumerate(features):
                row[feature] = stock_idx * 0.1 + date_idx * 0.001 + feature_idx
            rows.append(row)

    fit_calls = {"count": 0}

    class DummyModel:
        def fit(self, x, y):
            fit_calls["count"] += 1
            return self

        def predict(self, x):
            return np.linspace(0, 1, len(x))

    monkeypatch.setattr(
        "factor_lab.pipeline._build_model_pipelines",
        lambda *args, **kwargs: {
            "baseline": DummyModel(),
            "nonlinear": DummyModel(),
            "nonlinear_v2": DummyModel(),
        },
    )

    result = generate_walk_forward_predictions(
        pd.DataFrame(rows),
        features,
        random_state=7,
        max_windows=3,
        max_train_rows=200,
        rf_n_estimators=8,
    )

    summary = result["summary"]
    assert summary["enabled"] is True
    assert summary["retrain_windows"] <= 3
    assert summary["max_retrain_windows"] == 3
    assert summary["sampled_walk_forward"] is True
    assert fit_calls["count"] == summary["retrain_windows"] * 3
