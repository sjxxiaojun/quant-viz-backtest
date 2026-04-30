import json
import os

import pandas as pd
from fastapi.testclient import TestClient

import main
from strategy_versioning import StrategyVersionStore


client = TestClient(main.app)


def _write_factor_lab_artifacts(report_dir, run_id="run_a", config_hash="cfg_a"):
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "latest_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "config_hash": config_hash,
                "generated_at": "2026-04-29T10:00:00",
                "oos_start_date": "2026-01-01",
                "oos_end_date": "2026-04-20",
            }
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        [
            {
                "date": "2026-04-20",
                "stock_code": "000001",
                "score": 0.95,
                "run_id": run_id,
                "config_hash": config_hash,
                "is_oos_score": True,
            },
            {
                "date": "2026-04-20",
                "stock_code": "000002",
                "score": 0.10,
                "run_id": run_id,
                "config_hash": config_hash,
                "is_oos_score": True,
            },
        ]
    ).to_csv(report_dir / "latest_scores.csv", index=False)


def _factor_lab_result(report_dir, run_id="run_a", config_hash="cfg_a"):
    return {
        "summary": {
            "run_id": run_id,
            "start_date": "2026-01-01",
            "end_date": "2026-04-20",
            "pool": "core",
            "label": "next_5d_ret",
            "top_n": 3,
            "score_source": "walk_forward_composite_score",
            "walk_forward": {"coverage_ratio": 0.8},
        },
        "model_metrics": [{"key": "test_rank_ic", "label": "测试 RankIC", "value": 0.04}],
        "strategy_backtests": {
            "ml_factor_ranker": {
                "factor": "ml_factor_ranker",
                "with_cost": {
                    "total_return": 0.08,
                    "summary": {"annual_return": 0.12, "max_drawdown": -0.08},
                },
                "cost_drag": {"total_return_diff": 0.01, "cost_pct_initial": 0.005},
            }
        },
        "research_iteration": {"tested_candidate_factors": 10, "promoted_candidate_factors": 2},
        "self_iteration": {
            "stress_gate": {"available": True, "passed": True, "message": "三行情景压力测评通过。"},
            "promotion_decision": {"status": "shadow", "decision": "进入影子观察。"},
        },
        "factor_ranking": [{"factor": "mom_20d", "score": 0.8}],
        "feature_importance": [],
        "bucket_returns": [],
        "stability": [],
        "backtest": None,
        "artifacts": {"report_dir": str(report_dir)},
    }


def _write_run_dir(report_dir, run_id, payload="x", mtime=1_000_000):
    run_dir = report_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "latest_scores.csv").write_text(payload, encoding="utf-8")
    os.utime(run_dir, (mtime, mtime))
    os.utime(run_dir / "latest_scores.csv", (mtime, mtime))
    return run_dir


def test_promote_creates_candidate_from_immutable_run_artifact(tmp_path, monkeypatch):
    report_dir = tmp_path / "factor_lab"
    _write_factor_lab_artifacts(report_dir)
    store = StrategyVersionStore(tmp_path / "versions.db")
    result = _factor_lab_result(report_dir)

    monkeypatch.setattr(main, "FACTOR_LAB_REPORT_DIR", report_dir)
    monkeypatch.setattr(main, "strategy_version_store", store)
    monkeypatch.setattr(main, "load_latest_factor_lab_result", lambda: result)
    monkeypatch.setattr(main, "persist_factor_lab_result", lambda payload, target: None)

    response = client.post(
        "/api/factor-lab/candidates/run_a/promote",
        json={"strategy_id": "ai_ml", "candidate_factor": "ml_factor_ranker"},
    )

    assert response.status_code == 200
    version = response.json()["version"]
    assert version["strategy_id"] == "ai_ml"
    assert version["status"] == "research_pass"
    assert version["source_run_id"] == "run_a"
    assert "/runs/run_a" in version["artifact_ref"]
    assert version["artifact_ref"] != str(report_dir)
    assert version["metrics"]["artifact_hash"]
    assert response.json()["strategy_lifecycle"]["status"] == "research_pass"


def test_factor_lab_artifact_cleanup_keeps_referenced_and_recent_runs(tmp_path, monkeypatch):
    report_dir = tmp_path / "factor_lab"
    _write_factor_lab_artifacts(report_dir)
    result = main.materialize_factor_lab_run_archive(_factor_lab_result(report_dir), report_dir)
    os.utime(report_dir / "runs" / "run_a", (1_000_000, 1_000_000))
    _write_run_dir(report_dir, "run_recent", payload="recent", mtime=3_000_000)
    obsolete = _write_run_dir(report_dir, "run_obsolete", payload="obsolete", mtime=2_000_000)
    training_sample = report_dir / "training_sample_scored.csv"
    training_sample.write_text("debug rows", encoding="utf-8")

    store = StrategyVersionStore(tmp_path / "versions.db")
    store.create_factor_lab_candidate(result, strategy_id="ai_ml", candidate_factor="ml_factor_ranker")
    monkeypatch.setattr(main, "FACTOR_LAB_REPORT_DIR", report_dir)
    monkeypatch.setattr(main, "strategy_version_store", store)

    dry_run = client.post(
        "/api/factor-lab/artifacts/cleanup",
        json={"keep_recent_runs": 1, "dry_run": True, "delete_training_sample": True},
    )

    assert dry_run.status_code == 200
    assert obsolete.exists()
    assert training_sample.exists()
    assert [item["run_id"] for item in dry_run.json()["deleted_runs"]] == ["run_obsolete"]
    assert dry_run.json()["freed_bytes"] == 0
    assert dry_run.json()["potential_freed_bytes"] > 0

    cleaned = client.post(
        "/api/factor-lab/artifacts/cleanup",
        json={"keep_recent_runs": 1, "dry_run": False, "delete_training_sample": True},
    )

    assert cleaned.status_code == 200
    assert (report_dir / "runs" / "run_a").exists()
    assert (report_dir / "runs" / "run_recent").exists()
    assert not obsolete.exists()
    assert not training_sample.exists()
    assert [item["run_id"] for item in cleaned.json()["deleted_runs"]] == ["run_obsolete"]


def test_iterate_strategy_version_creates_anchored_plan(tmp_path, monkeypatch):
    report_dir = tmp_path / "factor_lab"
    _write_factor_lab_artifacts(report_dir)
    store = StrategyVersionStore(tmp_path / "versions.db")
    result = _factor_lab_result(report_dir)

    monkeypatch.setattr(main, "FACTOR_LAB_REPORT_DIR", report_dir)
    monkeypatch.setattr(main, "strategy_version_store", store)
    monkeypatch.setattr(main, "load_latest_factor_lab_result", lambda: result)
    monkeypatch.setattr(main, "persist_factor_lab_result", lambda payload, target: None)

    version = client.post(
        "/api/factor-lab/candidates/run_a/promote",
        json={"strategy_id": "ai_ml", "candidate_factor": "ml_factor_ranker"},
    ).json()["version"]

    response = client.post(
        f"/api/strategy-versions/{version['version_id']}/iterate",
        json={"user": "tester", "note": "continue current candidate"},
    )

    assert response.status_code == 200
    iteration = response.json()["iteration"]
    assert iteration["parent_version_id"] == version["version_id"]
    assert iteration["mode"] == "candidate_anchored_refinement"
    assert iteration["status"] == "planned"
    assert iteration["source_run_id"] == version["source_run_id"]
    assert iteration["config_hash"] == version["config_hash"]
    assert iteration["artifact_ref"] == version["artifact_ref"]
    assert iteration["artifact_hash"] == version["metrics"]["artifact_hash"]
    assert iteration["next_run_config"]["locked_artifact_hash"] == version["metrics"]["artifact_hash"]
    assert "不能把 latest_* 当作生产真相源" in iteration["next_run_config"]["constraints"]
    assert any(action["type"] == "continue_shadow_observation" for action in iteration["actions"])
    assert response.json()["version"]["status"] == "research_pass"


def test_latest_results_include_latest_iteration_plan(tmp_path, monkeypatch):
    report_dir = tmp_path / "factor_lab"
    _write_factor_lab_artifacts(report_dir)
    store = StrategyVersionStore(tmp_path / "versions.db")
    result = _factor_lab_result(report_dir)

    monkeypatch.setattr(main, "FACTOR_LAB_REPORT_DIR", report_dir)
    monkeypatch.setattr(main, "strategy_version_store", store)
    monkeypatch.setattr(main, "load_latest_factor_lab_result", lambda: result)
    monkeypatch.setattr(main, "persist_factor_lab_result", lambda payload, target: None)

    version = client.post(
        "/api/factor-lab/candidates/run_a/promote",
        json={"strategy_id": "ai_ml", "candidate_factor": "ml_factor_ranker"},
    ).json()["version"]
    created = client.post(
        f"/api/strategy-versions/{version['version_id']}/iterate",
        json={"user": "tester"},
    ).json()["iteration"]

    response = client.get("/api/factor-lab/results")

    assert response.status_code == 200
    lifecycle = response.json()["strategy_lifecycle"]
    assert lifecycle["latest_iteration"]["iteration_id"] == created["iteration_id"]
    assert lifecycle["latest_iteration"]["parent_version_id"] == version["version_id"]
    assert "定向迭代计划" in lifecycle["next_action"]


def test_strategy_version_shadow_approval_activation_and_rollback(tmp_path, monkeypatch):
    report_dir = tmp_path / "factor_lab"
    _write_factor_lab_artifacts(report_dir)
    store = StrategyVersionStore(tmp_path / "versions.db")
    result = _factor_lab_result(report_dir)

    monkeypatch.setattr(main, "FACTOR_LAB_REPORT_DIR", report_dir)
    monkeypatch.setattr(main, "strategy_version_store", store)
    monkeypatch.setattr(main, "load_latest_factor_lab_result", lambda: result)
    monkeypatch.setattr(main, "persist_factor_lab_result", lambda payload, target: None)

    promoted = client.post(
        "/api/factor-lab/candidates/run_a/promote",
        json={"strategy_id": "ai_ml", "candidate_factor": "ml_factor_ranker"},
    ).json()["version"]
    version_id = promoted["version_id"]

    shadow = client.post(f"/api/strategy-versions/{version_id}/shadow", json={"user": "tester"})
    assert shadow.status_code == 200
    assert shadow.json()["version"]["status"] == "shadow"

    blocked = client.post(f"/api/strategy-versions/{version_id}/approve", json={"user": "tester"})
    assert blocked.status_code == 400
    assert "影子观察" in blocked.json()["detail"]

    store.record_shadow_observation(
        version_id,
        date="2026-04-21",
        total_value=1005000.0,
        cash=300000.0,
        selected_symbols=["000001"],
    )

    approved = client.post(f"/api/strategy-versions/{version_id}/approve", json={"user": "tester"})
    assert approved.status_code == 200
    assert approved.json()["version"]["status"] == "approved"

    activated = client.post(
        "/api/strategies/ai_ml/activate-version",
        json={"version_id": version_id, "user": "tester"},
    )
    assert activated.status_code == 200
    assert activated.json()["active_version_id"] == version_id
    assert store.get_active_version_id("ai_ml") == version_id

    rolled_back = client.post("/api/strategies/ai_ml/rollback", json={"user": "tester", "reason": "test"})
    assert rolled_back.status_code == 200
    assert rolled_back.json()["rolled_back_version_id"] == version_id
    assert store.get_active_version_id("ai_ml") is None


def test_resolved_strategy_version_uses_pinned_artifact(tmp_path):
    report_dir = tmp_path / "factor_lab"
    _write_factor_lab_artifacts(report_dir)
    result = _factor_lab_result(report_dir)
    result = main.materialize_factor_lab_run_archive(result, report_dir)

    store = StrategyVersionStore(tmp_path / "versions.db")
    version = store.create_factor_lab_candidate(result, strategy_id="ai_ml", candidate_factor="ml_factor_ranker")
    spec = store.resolve_strategy_spec(version["version_id"])

    latest_scores = report_dir / "latest_scores.csv"
    pd.DataFrame(
        [
            {
                "date": "2026-04-20",
                "stock_code": "000001",
                "score": 0.01,
                "run_id": "different",
                "config_hash": "different",
                "is_oos_score": True,
            }
        ]
    ).to_csv(latest_scores, index=False)

    signals = spec.func(
        pd.DataFrame(
            [
                {"date": "2026-04-20", "stock_code": "000001", "close": 10.0},
                {"date": "2026-04-20", "stock_code": "000002", "close": 10.0},
            ]
        )
    )

    selected = signals[signals["signal"] == 1]["stock_code"].tolist()
    assert selected == ["000001", "000002"]
