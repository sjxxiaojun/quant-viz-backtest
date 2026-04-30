import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np


def _as_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        number = float(value)
        if np.isnan(number) or np.isinf(number):
            return default
        return number
    except Exception:
        return default


def _fmt_factor_list(items: List[Dict[str, object]], limit: int = 3) -> List[str]:
    return [str(item.get("factor") or item.get("feature") or "") for item in items[:limit] if item.get("factor") or item.get("feature")]


def _leading_strategy(result: Dict[str, object]) -> Dict[str, object]:
    comparisons = result.get("strategy_backtests", {})
    if not isinstance(comparisons, dict) or not comparisons:
        return {}
    best_key = result.get("backtest_compare", {}).get("best_total_return_factor")
    if best_key in comparisons:
        return comparisons[best_key]
    return max(
        comparisons.values(),
        key=lambda item: _as_float(item.get("with_cost", {}).get("total_return")) if isinstance(item, dict) else -999.0,
    )


def _stress_gate(stress_test: Optional[Dict[str, object]], factor: str) -> Dict[str, object]:
    if not stress_test:
        return {
            "available": False,
            "passed": False,
            "message": "尚未运行牛市、熊市、震荡年压力测评。",
        }

    failures = []
    scenario_scores = []
    for scenario in stress_test.get("scenarios", []):
        factor_stats = scenario.get("factors", {}).get(factor, {})
        if not factor_stats:
            failures.append(f"{scenario.get('name_cn', scenario.get('scenario'))}缺少统计结果")
            continue
        prob_positive = _as_float(factor_stats.get("prob_positive"))
        survival_rate = _as_float(factor_stats.get("survival_rate"))
        p95_dd = _as_float(factor_stats.get("p95_max_drawdown_abs"))
        scenario_scores.append(prob_positive * 0.5 + survival_rate * 0.35 + max(0.0, 1.0 - p95_dd / 0.35) * 0.15)
        if survival_rate < 0.70:
            failures.append(f"{scenario.get('name_cn', scenario.get('scenario'))}生存率偏低")
        if p95_dd > 0.32:
            failures.append(f"{scenario.get('name_cn', scenario.get('scenario'))}极端回撤偏深")

    return {
        "available": True,
        "passed": len(failures) == 0 and len(scenario_scores) > 0,
        "score": float(np.mean(scenario_scores)) if scenario_scores else 0.0,
        "failures": failures,
        "message": "三行情景压力测评通过。" if not failures else "；".join(failures),
    }


def _build_candidates(result: Dict[str, object]) -> List[Dict[str, object]]:
    summary = result.get("summary", {})
    factors = result.get("factor_ranking", []) if isinstance(result.get("factor_ranking"), list) else []
    features = result.get("feature_importance", []) if isinstance(result.get("feature_importance"), list) else []
    top_factors = _fmt_factor_list(factors, 3)
    top_features = _fmt_factor_list(features, 5)
    leading = _leading_strategy(result)
    cost_drag = _as_float(leading.get("cost_drag", {}).get("total_return_diff")) if isinstance(leading, dict) else 0.0
    max_drawdown = abs(_as_float(leading.get("with_cost", {}).get("summary", {}).get("max_drawdown"))) if isinstance(leading, dict) else 0.0

    candidates = [
        {
            "candidate_id": "current_walk_forward_production",
            "name_cn": "当前样本外打分规则",
            "status": "production",
            "parent_id": None,
            "formula": summary.get("score_source", "walk_forward_composite_score"),
            "feature_dependencies": top_features,
            "complexity_score": 1.0,
            "rationale": "当前生产候选，只使用样本外分数进入策略卡和回测。",
        },
        {
            "candidate_id": "top_factor_blend_v1",
            "name_cn": "前三因子增强组合",
            "status": "draft",
            "parent_id": "current_walk_forward_production",
            "formula": "weighted_blend(%s)" % ", ".join(top_factors or top_features[:3]),
            "feature_dependencies": top_factors or top_features[:3],
            "complexity_score": 2.0,
            "rationale": "用本轮排名靠前的因子生成更集中的候选组合，下一轮只允许在验证集选择权重。",
        },
        {
            "candidate_id": "cost_aware_filter_v1",
            "name_cn": "成本敏感过滤版",
            "status": "draft",
            "parent_id": "current_walk_forward_production",
            "formula": "score_rank + turnover/cost_penalty",
            "feature_dependencies": ["turnover_rate", "turnover_z20", *top_features[:3]],
            "complexity_score": 2.5,
            "rationale": "如果交易成本拖累明显，就降低高换手信号的权重。",
        },
        {
            "candidate_id": "drawdown_guard_v1",
            "name_cn": "回撤保护版",
            "status": "draft",
            "parent_id": "current_walk_forward_production",
            "formula": "score_rank with volatility/drawdown guard",
            "feature_dependencies": ["volatility_20d", "drawdown_20d", *top_features[:3]],
            "complexity_score": 2.5,
            "rationale": "当最大回撤偏深时，给高波动和深回撤标的降权。",
        },
    ]

    if cost_drag > 0.02:
        candidates[2]["status"] = "research_pass"
    if max_drawdown > 0.15:
        candidates[3]["status"] = "research_pass"
    if top_factors:
        candidates[1]["status"] = "research_pass"

    research_iteration = result.get("research_iteration", {}) if isinstance(result.get("research_iteration"), dict) else {}
    mined_candidates = research_iteration.get("candidates", []) if isinstance(research_iteration.get("candidates"), list) else []
    for item in mined_candidates[:5]:
        if not isinstance(item, dict):
            continue
        factor = str(item.get("factor") or item.get("candidate_id") or "")
        if not factor:
            continue
        status = "research_pass" if item.get("status") == "promoted" else "draft"
        candidates.append(
            {
                "candidate_id": f"mined_{factor}",
                "name_cn": str(item.get("name_cn") or factor),
                "status": status,
                "parent_id": "candidate_factor_mining",
                "formula": str(item.get("formula") or factor),
                "feature_dependencies": item.get("dependencies", []) if isinstance(item.get("dependencies"), list) else [],
                "complexity_score": 2.0,
                "rationale": str(item.get("reason") or "本轮自动候选因子挖掘产生，等待更多滚动样本复核。"),
            }
        )
    return candidates


def build_self_iteration_report(result: Dict[str, object], output_dir: Path) -> Dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = "iter_%s" % datetime.now().strftime("%Y%m%d_%H%M%S")
    summary = result.get("summary", {})
    leading = _leading_strategy(result)
    leading_factor = leading.get("factor", result.get("backtest_compare", {}).get("best_total_return_factor", "ml_factor_ranker")) if isinstance(leading, dict) else "ml_factor_ranker"
    leading_with_cost = leading.get("with_cost", {}) if isinstance(leading, dict) else {}
    leading_summary = leading_with_cost.get("summary", {}) if isinstance(leading_with_cost, dict) else {}
    walk_forward = summary.get("walk_forward", {}) if isinstance(summary, dict) else {}
    bucket_returns = result.get("bucket_returns", []) if isinstance(result.get("bucket_returns"), list) else []
    bucket_spread = 0.0
    if len(bucket_returns) >= 2:
        bucket_spread = _as_float(bucket_returns[-1].get("return")) - _as_float(bucket_returns[0].get("return"))

    total_return = _as_float(leading_with_cost.get("total_return"))
    max_drawdown = abs(_as_float(leading_summary.get("max_drawdown")))
    cost_drag = _as_float(leading.get("cost_drag", {}).get("total_return_diff")) if isinstance(leading, dict) else 0.0
    coverage = _as_float(walk_forward.get("coverage_ratio"))
    test_rank_ic = 0.0
    for metric in result.get("model_metrics", []) if isinstance(result.get("model_metrics"), list) else []:
        if metric.get("key") == "test_rank_ic":
            test_rank_ic = _as_float(metric.get("value"))
            break

    evidence_score = 50.0
    evidence_score += 12 if coverage >= 0.80 else 6 if coverage >= 0.60 else -8
    evidence_score += 12 if test_rank_ic >= 0.03 else 6 if test_rank_ic >= 0.015 else -6
    evidence_score += 10 if bucket_spread > 0.01 else 2 if bucket_spread > 0 else -8
    evidence_score += 10 if total_return > 0.03 else 4 if total_return > 0 else -10
    evidence_score += 8 if max_drawdown <= 0.12 else 2 if max_drawdown <= 0.20 else -8
    evidence_score += 6 if cost_drag <= 0.015 else -6 if cost_drag >= 0.03 else 0
    evidence_score = max(0.0, min(100.0, evidence_score))

    candidates = _build_candidates(result)
    stress_gate = _stress_gate(result.get("stress_test"), leading_factor)
    hard_failures = []
    if coverage < 0.60:
        hard_failures.append("样本外覆盖率低于 60%")
    if test_rank_ic <= 0:
        hard_failures.append("测试 RankIC 未转正")
    if total_return <= 0:
        hard_failures.append("含成本收益未转正")
    if max_drawdown > 0.25:
        hard_failures.append("最大回撤超过 25%")
    if stress_gate["available"] and not stress_gate["passed"]:
        hard_failures.append("牛熊震荡压力测评未通过")

    if not hard_failures and stress_gate["available"] and evidence_score >= 72:
        promotion_status = "shadow"
        decision = "进入影子观察，暂不覆盖生产模型。"
    elif not hard_failures and evidence_score >= 66:
        promotion_status = "research_pass"
        decision = "研究层通过，等待三行情景压力测评。"
    else:
        promotion_status = "no_promotion"
        decision = "暂不晋级，继续保留当前生产候选。"

    report = {
        "run_id": run_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "candidate_factory_with_promotion_gate",
        "production_candidate": {
            "candidate_id": "current_walk_forward_production",
            "score_source": summary.get("score_source"),
            "leading_factor": leading_factor,
        },
        "evidence": {
            "score": round(evidence_score, 2),
            "note": "证据分衡量样本外、分层、成本、回撤和压力测评完整性，不是收益概率。",
            "metrics": {
                "walk_forward_coverage": coverage,
                "test_rank_ic": test_rank_ic,
                "bucket_spread": bucket_spread,
                "with_cost_total_return": total_return,
                "max_drawdown_abs": max_drawdown,
                "cost_drag": cost_drag,
            },
        },
        "candidate_pipeline": {
            "generated": len(candidates),
            "research_pass": sum(1 for candidate in candidates if candidate["status"] == "research_pass"),
            "shadow": 1 if promotion_status == "shadow" else 0,
            "production_promoted": 0,
        },
        "candidates": candidates,
        "stress_gate": stress_gate,
        "promotion_decision": {
            "status": promotion_status,
            "decision": decision,
            "failures": hard_failures,
            "next_action": "先运行未来一年牛市、熊市、震荡年压力测评。" if not stress_gate["available"] else "继续观察下一次真实数据更新后的表现。",
        },
        "artifacts": {
            "summary_json": str(output_dir / "latest_summary.json"),
            "candidates_csv": str(output_dir / "candidates.csv"),
        },
    }

    with (output_dir / "latest_summary.json").open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with (output_dir / "candidates.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["candidate_id", "name_cn", "status", "parent_id", "formula", "complexity_score", "rationale"],
        )
        writer.writeheader()
        for candidate in candidates:
            writer.writerow({key: candidate.get(key) for key in writer.fieldnames})
    return report
