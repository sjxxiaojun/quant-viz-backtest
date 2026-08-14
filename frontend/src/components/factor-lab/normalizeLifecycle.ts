/**
 * Factor Lab 生命周期侧响应收敛：自我复盘、压力测试、策略版本/影子/迭代。
 */
import type {
  FactorLabArtifactStatus,
  FactorLabSelfIteration,
  FactorLabStrategyLifecycle,
  FactorLabStressScenario,
  FactorLabStressTest,
  StrategyVersionIteration,
  StrategyVersionRecord,
  StrategyVersionShadowLedger,
} from '../../types';
import {
  isRecord,
  mapItems,
  parseFields,
  parseFieldsOrNull,
  toNum,
  toNumberRecord,
  toStr,
  toStrArray,
} from './parse';

export function normalizeSelfIteration(source: unknown): FactorLabSelfIteration | null {
  if (!isRecord(source)) return null;
  const evidence = isRecord(source.evidence) ? source.evidence : {};
  return {
    run_id: toStr(source.run_id),
    generated_at: toStr(source.generated_at),
    mode: toStr(source.mode),
    production_candidate: parseFields<NonNullable<FactorLabSelfIteration['production_candidate']>>(
      source.production_candidate,
      { candidate_id: 'str', score_source: 'str', leading_factor: 'str' }
    ),
    evidence: {
      score: toNum(evidence.score),
      note: toStr(evidence.note),
      metrics: toNumberRecord(evidence.metrics),
    },
    candidate_pipeline: parseFields<NonNullable<FactorLabSelfIteration['candidate_pipeline']>>(
      source.candidate_pipeline,
      { generated: 'num', research_pass: 'num', shadow: 'num', production_promoted: 'num' }
    ),
    candidates: mapItems(source.candidates, (candidate) =>
      isRecord(candidate)
        ? parseFields<NonNullable<FactorLabSelfIteration['candidates']>[number]>(candidate, {
            candidate_id: 'str',
            name_cn: 'str',
            status: 'str',
            parent_id: 'str|null',
            formula: 'str',
            feature_dependencies: 'str[]',
            complexity_score: 'num',
            rationale: 'str',
          })
        : null
    ),
    stress_gate: parseFields<NonNullable<FactorLabSelfIteration['stress_gate']>>(source.stress_gate, {
      available: 'bool',
      passed: 'bool',
      score: 'num',
      failures: 'str[]',
      message: 'str',
    }),
    promotion_decision: parseFields<NonNullable<FactorLabSelfIteration['promotion_decision']>>(
      source.promotion_decision,
      { status: 'str', decision: 'str', failures: 'str[]', next_action: 'str' }
    ),
  };
}

type StressFactorStats = FactorLabStressScenario['factors'][string];

function normalizeStressScenario(source: unknown): FactorLabStressScenario | null {
  if (!isRecord(source)) return null;
  const factors: FactorLabStressScenario['factors'] = {};
  if (isRecord(source.factors)) {
    Object.entries(source.factors).forEach(([factor, value]) => {
      if (!isRecord(value)) return;
      factors[factor] = parseFields<StressFactorStats>(value, {
        median_total_return: 'num',
        p05_total_return: 'num',
        p95_total_return: 'num',
        prob_positive: 'num',
        median_max_drawdown: 'num',
        p95_max_drawdown_abs: 'num',
        median_sharpe: 'num',
        median_final_value: 'num',
        survival_rate: 'num',
        median_total_trades: 'num',
      });
    });
  }
  return {
    scenario: toStr(source.scenario),
    name_cn: toStr(source.name_cn, toStr(source.scenario)),
    assumptions: parseFieldsOrNull<NonNullable<FactorLabStressScenario['assumptions']>>(source.assumptions, {
      annual_drift: 'num',
      annual_vol: 'num',
      market_beta_bias: 'num',
      mean_reversion: 'num',
    }) ?? undefined,
    factors,
    sample_paths: mapItems(source.sample_paths, (path) => {
      if (!isRecord(path)) return null;
      return {
        path_id: toNum(path.path_id),
        factor: toStr(path.factor),
        history: mapItems(path.history, (point) =>
          isRecord(point)
            ? parseFields<NonNullable<FactorLabStressScenario['sample_paths']>[number]['history'][number]>(point, {
                date: 'str',
                total_value: 'num',
                drawdown: 'num',
              })
            : null
        ),
      };
    }),
  };
}

export function normalizeStressTest(source: unknown): FactorLabStressTest | null {
  if (!isRecord(source)) return null;
  return {
    run_id: toStr(source.run_id),
    generated_at: toStr(source.generated_at),
    config: parseFields<NonNullable<FactorLabStressTest['config']>>(source.config, {
      pool: 'str',
      max_symbols: 'num',
      top_n: 'num',
      horizon_days: 'num',
      paths_per_scenario: 'num',
      seed: 'num',
      anchor_date: 'str',
      symbols: 'num',
    }),
    scenarios: mapItems(source.scenarios, normalizeStressScenario),
    disclaimer: toStr(source.disclaimer),
  };
}

export function normalizeArtifactStatus(source: unknown): FactorLabArtifactStatus | null {
  return parseFieldsOrNull<FactorLabArtifactStatus>(source, {
    ready: 'bool',
    status: 'str',
    message: 'str',
    run_id: 'str',
    config_hash: 'str',
    generated_at: 'str',
    oos_start_date: 'str',
    oos_end_date: 'str',
    score_rows: 'num?',
    oos_score_rows: 'num?',
    model_available: 'bool?',
  });
}

function normalizeShadowLedger(source: unknown): StrategyVersionShadowLedger | undefined {
  if (!isRecord(source)) return undefined;
  return {
    ...parseFields<Omit<StrategyVersionShadowLedger, 'metrics'>>(source, {
      version_id: 'str',
      strategy_id: 'str',
      shadow_strategy_id: 'str',
      started_at: 'str',
      status: 'str',
      observation_days: 'num',
      latest_observation_date: 'str|null',
      baseline_strategy_id: 'str|null',
      note: 'str|null',
    }),
    metrics: isRecord(source.metrics) ? source.metrics : {},
  };
}

export function normalizeStrategyVersionIteration(source: unknown): StrategyVersionIteration | null {
  if (!isRecord(source)) return null;
  const objective = isRecord(source.objective) ? source.objective : {};
  const nextRunConfig = isRecord(source.next_run_config) ? source.next_run_config : {};
  return {
    ...parseFields<Pick<StrategyVersionIteration, 'iteration_id' | 'parent_version_id' | 'strategy_id' | 'source_run_id' | 'config_hash' | 'artifact_ref' | 'artifact_hash' | 'mode' | 'status' | 'created_at' | 'created_by' | 'result_version_id' | 'note'>>(source, {
      iteration_id: 'str',
      parent_version_id: 'str',
      strategy_id: 'str',
      source_run_id: 'str',
      config_hash: 'str',
      artifact_ref: 'str',
      artifact_hash: 'str',
      mode: 'str',
      status: 'str',
      created_at: 'str',
      created_by: 'str|null',
      result_version_id: 'str|null',
      note: 'str|null',
    }),
    objective: {
      ...objective,
      summary: toStr(objective.summary),
      primary_blockers: toStrArray(objective.primary_blockers),
      research_failures: toStrArray(objective.research_failures),
      target_metrics: isRecord(objective.target_metrics) ? objective.target_metrics : {},
    },
    next_run_config: {
      ...nextRunConfig,
      ...parseFields<Record<string, string>>(nextRunConfig, {
        mode: 'str',
        parent_version_id: 'str',
        strategy_id: 'str',
        source_run_id: 'str',
        candidate_factor: 'str',
        config_hash: 'str',
        artifact_ref: 'str',
        locked_artifact_hash: 'str',
      }),
      constraints: toStrArray(nextRunConfig.constraints),
      suggested_actions: Array.isArray(nextRunConfig.suggested_actions)
        ? nextRunConfig.suggested_actions.filter(isRecord)
        : [],
    },
    actions: Array.isArray(source.actions)
      ? source.actions.filter(isRecord).map((action) => ({
          ...action,
          type: toStr(action.type),
          label: toStr(action.label),
          rationale: toStr(action.rationale),
          blocking: action.blocking !== undefined ? Boolean(action.blocking) : undefined,
        }))
      : [],
  };
}

export function normalizeStrategyVersion(source: unknown): StrategyVersionRecord | null {
  if (!isRecord(source)) return null;
  const metrics = isRecord(source.metrics) ? source.metrics : {};
  const gates = isRecord(source.gates) ? source.gates : {};
  return {
    ...parseFields<Pick<StrategyVersionRecord, 'version_id' | 'strategy_id' | 'parent_version_id' | 'source_run_id' | 'config_hash' | 'artifact_ref' | 'created_at' | 'approved_at' | 'approved_by' | 'approval_note' | 'active'>>(source, {
      version_id: 'str',
      strategy_id: 'str',
      parent_version_id: 'str|null',
      source_run_id: 'str',
      config_hash: 'str',
      artifact_ref: 'str',
      created_at: 'str',
      approved_at: 'str|null',
      approved_by: 'str|null',
      approval_note: 'str|null',
      active: 'bool?',
    }),
    status: toStr(source.status, 'draft'),
    metrics: {
      ...metrics,
      ...parseFields<Record<string, unknown>>(metrics, {
        candidate_factor: 'str',
        artifact_hash: 'str',
        score_source: 'str',
        test_rank_ic: 'num?',
        with_cost_total_return: 'num?',
        annual_return: 'num?',
        max_drawdown_abs: 'num?',
        cost_drag: 'num?',
        walk_forward_coverage: 'num?',
        stress_gate_available: 'bool?',
        stress_gate_passed: 'bool?',
        tested_candidate_factors: 'num?',
        promoted_candidate_factors: 'num?',
        parent_strategy_name: 'str',
      }),
    },
    gates: parseFields<StrategyVersionRecord['gates']>(gates, {
      oos_rank_ic_positive: 'bool?',
      with_cost_return_positive: 'bool?',
      max_drawdown_ok: 'bool?',
      cost_drag_ok: 'bool?',
      stress_test_passed: 'bool?',
      shadow_min_observation_passed: 'bool?',
      shadow_observation_days: 'num?',
      research_gate_passed: 'bool?',
      approval_gate_passed: 'bool?',
      failures: 'str[]',
      research_failures: 'str[]',
    }),
    shadow: normalizeShadowLedger(source.shadow),
    latest_iteration: normalizeStrategyVersionIteration(source.latest_iteration),
  };
}

export function normalizeStrategyLifecycle(source: unknown): FactorLabStrategyLifecycle | null {
  if (!isRecord(source)) return null;
  return {
    status: toStr(source.status),
    parent_strategy_id: toStr(source.parent_strategy_id),
    parent_strategy_name: toStr(source.parent_strategy_name),
    active_version_id: source.active_version_id == null ? null : toStr(source.active_version_id),
    current_run_id: toStr(source.current_run_id),
    current_run_versions: mapItems(source.current_run_versions, normalizeStrategyVersion),
    recent_versions: mapItems(source.recent_versions, normalizeStrategyVersion),
    latest_iteration: normalizeStrategyVersionIteration(source.latest_iteration),
    next_action: toStr(source.next_action),
    decision: parseFieldsOrNull<NonNullable<FactorLabStrategyLifecycle['decision']>>(source.decision, {
      status: 'str',
      decision: 'str',
      failures: 'str[]',
      next_action: 'str',
    }) ?? undefined,
  };
}
