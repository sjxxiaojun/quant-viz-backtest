import { useCallback, useEffect, useRef, useState } from 'react';
import { apiGet, apiPost, getApiErrorMessage, getApiErrorPayload, isRequestCanceled } from '../api/client';
import { assertBacktestResult } from '../api/guards';
import type {
  BacktestResult,
  FactorLabBucketReturnItem,
  FactorLabFailureState,
  FactorLabFeatureImportanceItem,
  FactorLabHookState,
  FactorLabMetricItem,
  FactorLabResult,
  FactorLabRunConfig,
  FactorLabRunReadiness,
  FactorLabSelfIteration,
  FactorLabArtifactStatus,
  FactorLabStrategyBacktest,
  FactorLabStrategyLifecycle,
  FactorLabStrategyUserView,
  FactorLabStressScenario,
  FactorLabStressTest,
  FactorLabSummary,
  StrategyVersionIteration,
  StrategyVersionRecord,
  StrategyVersionShadowLedger,
} from '../types';

const DEFAULT_FACTOR_LAB_RUN_CONFIG: FactorLabRunConfig = {
  start_date: '2022-01-01',
  end_date: new Date().toISOString().slice(0, 10),
  pool: 'core',
  label: 'next_5d_ret',
  top_n: 5,
  max_symbols: 300,
};

const PREVIOUS_REAL_RESULT_NOTICE = '当前展示的是上次真实结果';

const LABEL_MAP: Record<string, string> = {
  auc: 'AUC',
  accuracy: '准确率',
  precision: '精确率',
  recall: '召回率',
  f1: 'F1',
  ic: 'IC',
  ic_ir: 'IC IR',
  rank_ic: 'Rank IC',
  coverage: '覆盖率',
  turnover_stability: '换手稳定度',
  positive_month_ratio: '月度正贡献占比',
  generalization_gap: '泛化偏差',
  bucket_spread: '分桶收益差',
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function toNumber(value: unknown, fallback = 0): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

function toString(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

function inferMetricFormat(key: string): FactorLabMetricItem['format'] {
  if (/coverage|return|drawdown|win_rate|positive_month_ratio|gap/.test(key)) return 'percent';
  if (/count|samples|symbols|top_n|trades/.test(key)) return 'integer';
  if (/auc|ic|rank_ic|ir|sharpe|precision|recall|f1|accuracy/.test(key)) return 'ratio';
  return 'number';
}

function prettifyLabel(key: string): string {
  return LABEL_MAP[key] || key.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function normalizeReadiness(source: unknown): FactorLabRunReadiness | null {
  if (!isRecord(source)) return null;
  return {
    requested_start_date: toString(source.requested_start_date, ''),
    requested_end_date: toString(source.requested_end_date, ''),
    effective_warmup_start: source.effective_warmup_start == null ? null : toString(source.effective_warmup_start, ''),
    cache_window_start: source.cache_window_start == null ? null : toString(source.cache_window_start, ''),
    cache_window_end: source.cache_window_end == null ? null : toString(source.cache_window_end, ''),
    missing_start: source.missing_start == null ? null : toString(source.missing_start, ''),
    missing_end: source.missing_end == null ? null : toString(source.missing_end, ''),
    needs_backfill: Boolean(source.needs_backfill),
    warning_message: source.warning_message == null ? null : toString(source.warning_message, ''),
    checked_symbols: Array.isArray(source.checked_symbols) ? source.checked_symbols.map((item) => String(item)) : [],
  };
}

function normalizeMetricEntries(source: unknown): FactorLabMetricItem[] {
  if (Array.isArray(source)) {
    return source
      .map((entry, index) => {
        if (!isRecord(entry)) return null;
        const key = toString(entry.key ?? entry.metric ?? entry.name, `metric_${index}`);
        return {
          key,
          label: toString(entry.label, prettifyLabel(key)),
          value: typeof entry.value === 'string' ? entry.value : toNumber(entry.value, 0),
          format: (entry.format as FactorLabMetricItem['format']) ?? inferMetricFormat(key),
          note: toString(entry.note, ''),
        };
      })
      .filter(Boolean) as FactorLabMetricItem[];
  }

  if (isRecord(source)) {
    return Object.entries(source).map(([key, value]) => {
      if (isRecord(value)) {
        return {
          key,
          label: toString(value.label, prettifyLabel(key)),
          value: typeof value.value === 'string' ? value.value : toNumber(value.value, 0),
          format: (value.format as FactorLabMetricItem['format']) ?? inferMetricFormat(key),
          note: toString(value.note, ''),
        };
      }
      return {
        key,
        label: prettifyLabel(key),
        value: typeof value === 'string' ? value : toNumber(value, 0),
        format: inferMetricFormat(key),
      };
    });
  }

  return [];
}

function normalizeFactorRanking(source: unknown): FactorLabResult['factor_ranking'] {
  if (Array.isArray(source)) {
    const items: FactorLabResult['factor_ranking'] = [];
    source.forEach((entry) => {
      if (!isRecord(entry)) return;
      const factor = toString(entry.factor ?? entry.name ?? entry.feature, '');
      if (!factor) return;
      items.push({
        factor,
        score: toNumber(entry.score, 0),
        ic: entry.ic !== undefined ? toNumber(entry.ic, 0) : undefined,
        rank_ic: entry.rank_ic !== undefined ? toNumber(entry.rank_ic, 0) : undefined,
        coverage: entry.coverage !== undefined ? toNumber(entry.coverage, 0) : undefined,
        stability: entry.stability !== undefined ? toNumber(entry.stability, 0) : undefined,
        direction: toString(entry.direction, ''),
      });
    });
    return items;
  }

  if (isRecord(source)) {
    return Object.entries(source).map(([factor, value]) => {
      if (isRecord(value)) {
        return {
          factor,
          score: toNumber(value.score, 0),
          ic: value.ic !== undefined ? toNumber(value.ic, 0) : undefined,
          rank_ic: value.rank_ic !== undefined ? toNumber(value.rank_ic, 0) : undefined,
          coverage: value.coverage !== undefined ? toNumber(value.coverage, 0) : undefined,
          stability: value.stability !== undefined ? toNumber(value.stability, 0) : undefined,
          direction: toString(value.direction, ''),
        };
      }
      return {
        factor,
        score: toNumber(value, 0),
      };
    });
  }

  return [];
}

function normalizeFeatureImportance(source: unknown): FactorLabFeatureImportanceItem[] {
  if (Array.isArray(source)) {
    const items: FactorLabFeatureImportanceItem[] = [];
    source.forEach((entry) => {
      if (!isRecord(entry)) return;
      const feature = toString(entry.feature ?? entry.name, '');
      if (!feature) return;
      items.push({
        feature,
        importance: toNumber(entry.importance ?? entry.score, 0),
        group: toString(entry.group, ''),
        direction: toString(entry.direction ?? entry.sign, ''),
      });
    });
    return items;
  }

  if (isRecord(source)) {
    return Object.entries(source).map(([feature, value]) => {
      if (isRecord(value)) {
        return {
          feature,
          importance: toNumber(value.importance ?? value.score, 0),
          group: toString(value.group, ''),
          direction: toString(value.direction ?? value.sign, ''),
        };
      }
      return {
        feature,
        importance: toNumber(value, 0),
      };
    });
  }

  return [];
}

function normalizeFactorWeights(source: unknown): FactorLabResult['factor_weights'] {
  if (!Array.isArray(source)) return [];
  return source
    .map((entry) => {
      if (!isRecord(entry)) return null;
      const feature = toString(entry.feature ?? entry.factor ?? entry.name, '');
      if (!feature) return null;
      return {
        feature,
        name_cn: toString(entry.name_cn, ''),
        group: toString(entry.group, ''),
        weight: toNumber(entry.weight ?? entry.importance, 0),
        importance: entry.importance !== undefined ? toNumber(entry.importance, 0) : undefined,
        direction: toString(entry.direction, ''),
        direction_text: toString(entry.direction_text, ''),
        explanation: toString(entry.explanation, ''),
        rank_ic: entry.rank_ic !== undefined ? toNumber(entry.rank_ic, 0) : undefined,
        recent_rank_ic: entry.recent_rank_ic !== undefined ? toNumber(entry.recent_rank_ic, 0) : undefined,
        source: toString(entry.source, ''),
      };
    })
    .filter(Boolean) as FactorLabResult['factor_weights'];
}

function normalizeBucketReturns(source: unknown): FactorLabBucketReturnItem[] {
  if (Array.isArray(source)) {
    const items: FactorLabBucketReturnItem[] = [];
    source.forEach((entry, index) => {
      if (!isRecord(entry)) return;
      const bucket = toString(entry.bucket ?? entry.group ?? entry.label, `Bucket ${index + 1}`);
      if (!bucket) return;
      items.push({
        bucket,
        return: toNumber(entry.return ?? entry.ret, 0),
        excess_return: entry.excess_return !== undefined ? toNumber(entry.excess_return, 0) : undefined,
        win_rate: entry.win_rate !== undefined ? toNumber(entry.win_rate, 0) : undefined,
        samples: entry.samples !== undefined ? toNumber(entry.samples, 0) : undefined,
      });
    });
    return items;
  }

  if (isRecord(source)) {
    return Object.entries(source).map(([bucket, value]) => {
      if (isRecord(value)) {
        return {
          bucket,
          return: toNumber(value.return ?? value.ret, 0),
          excess_return: value.excess_return !== undefined ? toNumber(value.excess_return, 0) : undefined,
          win_rate: value.win_rate !== undefined ? toNumber(value.win_rate, 0) : undefined,
          samples: value.samples !== undefined ? toNumber(value.samples, 0) : undefined,
        };
      }
      return {
        bucket,
        return: toNumber(value, 0),
      };
    });
  }

  return [];
}

function normalizeScoresPreview(source: unknown): FactorLabResult['scores_preview'] {
  if (!Array.isArray(source)) return [];
  return source
    .map((entry) => {
      if (!isRecord(entry)) return null;
      const stockCode = toString(entry.stock_code ?? entry.symbol ?? entry.code, '');
      if (!stockCode) return null;
      return {
        date: toString(entry.date, ''),
        stock_code: stockCode,
        stock_name: toString(entry.stock_name ?? entry.name, stockCode),
        score: entry.score !== undefined ? toNumber(entry.score, 0) : undefined,
        daily_rank: entry.daily_rank !== undefined ? toNumber(entry.daily_rank, 0) : undefined,
        signal: entry.signal !== undefined ? toNumber(entry.signal, 0) : undefined,
        is_oos_score: entry.is_oos_score !== undefined ? Boolean(entry.is_oos_score) : undefined,
        score_source: toString(entry.score_source, ''),
        close: entry.close !== undefined ? toNumber(entry.close, 0) : undefined,
      };
    })
    .filter(Boolean) as FactorLabResult['scores_preview'];
}

function normalizeDataSources(source: unknown): Record<string, string> | undefined {
  if (!isRecord(source)) return undefined;
  const normalized = Object.entries(source).reduce<Record<string, string>>((acc, [symbol, dataSource]) => {
    acc[symbol] = String(dataSource);
    return acc;
  }, {});
  return Object.keys(normalized).length > 0 ? normalized : undefined;
}

function normalizeBacktest(source: unknown): BacktestResult | null {
  if (!isRecord(source) || !isRecord(source.summary)) return null;
  return assertBacktestResult(source);
}

function normalizeUserView(source: unknown): FactorLabStrategyUserView | undefined {
  if (!isRecord(source)) return undefined;
  return {
    name_cn: toString(source.name_cn, ''),
    description_cn: toString(source.description_cn, ''),
    focus_points: Array.isArray(source.focus_points) ? source.focus_points.map((item) => String(item)) : [],
    suitable_for: Array.isArray(source.suitable_for) ? source.suitable_for.map((item) => String(item)) : [],
    total_return: toNumber(source.total_return, 0),
    annual_return: toNumber(source.annual_return, 0),
    max_drawdown: toNumber(source.max_drawdown, 0),
    win_rate: toNumber(source.win_rate, 0),
    trigger_days: toNumber(source.trigger_days, 0),
    total_trades: toNumber(source.total_trades, 0),
    last_signal_date: source.last_signal_date == null ? null : toString(source.last_signal_date, ''),
    recent_signal_symbols: Array.isArray(source.recent_signal_symbols)
      ? source.recent_signal_symbols.map((item) => String(item))
      : [],
    cost_drag: isRecord(source.cost_drag)
      ? {
          total_return_diff: toNumber(source.cost_drag.total_return_diff, 0),
          annual_return_diff: toNumber(source.cost_drag.annual_return_diff, 0),
          cost_pct_initial: toNumber(source.cost_drag.cost_pct_initial, 0),
        }
      : undefined,
  };
}

function normalizeStrategyBacktests(source: unknown): Record<string, FactorLabStrategyBacktest> | undefined {
  if (!isRecord(source)) return undefined;

  const normalized: Record<string, FactorLabStrategyBacktest> = {};
  Object.entries(source).forEach(([key, value]) => {
    if (!isRecord(value) || !isRecord(value.with_cost) || !isRecord(value.without_cost)) return;
    const costDrag = isRecord(value.cost_drag) ? value.cost_drag : {};
    normalized[key] = {
      factor: toString(value.factor, key),
      with_cost: {
        total_return: toNumber(value.with_cost.total_return, 0),
        summary: (value.with_cost.summary as BacktestResult['summary']) ?? {
          initial_capital: 0,
          final_value: 0,
          max_drawdown: 0,
          sharpe_ratio: 0,
        },
        resolved_pool: value.with_cost.resolved_pool as BacktestResult['resolved_pool'],
      },
      without_cost: {
        total_return: toNumber(value.without_cost.total_return, 0),
        summary: (value.without_cost.summary as BacktestResult['summary']) ?? {
          initial_capital: 0,
          final_value: 0,
          max_drawdown: 0,
          sharpe_ratio: 0,
        },
        resolved_pool: value.without_cost.resolved_pool as BacktestResult['resolved_pool'],
      },
      cost_drag: {
        total_return_diff: toNumber(costDrag.total_return_diff, 0),
        annual_return_diff: toNumber(costDrag.annual_return_diff, 0),
        cost_pct_initial: toNumber(costDrag.cost_pct_initial, 0),
      },
      user_view: normalizeUserView(value.user_view),
    };
  });

  return Object.keys(normalized).length > 0 ? normalized : undefined;
}

function normalizeNumberRecord(source: unknown): Record<string, number> | undefined {
  if (!isRecord(source)) return undefined;
  return Object.entries(source).reduce<Record<string, number>>((acc, [key, value]) => {
    acc[key] = toNumber(value, 0);
    return acc;
  }, {});
}

function normalizeModelRecipe(source: unknown) {
  if (!isRecord(source)) return undefined;
  return {
    baseline_model: toString(source.baseline_model, ''),
    nonlinear_model: toString(source.nonlinear_model, ''),
    baseline_weight: source.baseline_weight !== undefined ? toNumber(source.baseline_weight, 0) : undefined,
    nonlinear_weight: source.nonlinear_weight !== undefined ? toNumber(source.nonlinear_weight, 0) : undefined,
    selection_metric: toString(source.selection_metric, ''),
    selection_split: toString(source.selection_split, ''),
    valid_rank_ic: source.valid_rank_ic !== undefined ? toNumber(source.valid_rank_ic, 0) : undefined,
    valid_top20_ret: source.valid_top20_ret !== undefined ? toNumber(source.valid_top20_ret, 0) : undefined,
    reason: toString(source.reason, ''),
  };
}

function normalizeResearchIteration(source: unknown): FactorLabResult['research_iteration'] {
  if (!isRecord(source)) return null;
  return {
    mode: toString(source.mode, ''),
    actions: Array.isArray(source.actions) ? source.actions.map((item) => String(item)) : [],
    tested_candidate_factors: source.tested_candidate_factors !== undefined
      ? toNumber(source.tested_candidate_factors, 0)
      : undefined,
    promoted_candidate_factors: source.promoted_candidate_factors !== undefined
      ? toNumber(source.promoted_candidate_factors, 0)
      : undefined,
    promotion_cutoff: source.promotion_cutoff == null ? null : toNumber(source.promotion_cutoff, 0),
    candidates: Array.isArray(source.candidates)
      ? source.candidates
          .map((candidate) => {
            if (!isRecord(candidate)) return null;
            return {
              factor: toString(candidate.factor, ''),
              name_cn: toString(candidate.name_cn, ''),
              status: toString(candidate.status, ''),
              formula: toString(candidate.formula, ''),
              dependencies: Array.isArray(candidate.dependencies)
                ? candidate.dependencies.map((item) => String(item))
                : [],
              score: candidate.score !== undefined ? toNumber(candidate.score, 0) : undefined,
              rank_ic: candidate.rank_ic !== undefined ? toNumber(candidate.rank_ic, 0) : undefined,
              recent_rank_ic: candidate.recent_rank_ic !== undefined ? toNumber(candidate.recent_rank_ic, 0) : undefined,
              test_rank_ic: candidate.test_rank_ic !== undefined ? toNumber(candidate.test_rank_ic, 0) : undefined,
              reason: toString(candidate.reason, ''),
            };
          })
          .filter(Boolean) as NonNullable<FactorLabResult['research_iteration']>['candidates']
      : [],
    model_recipe: normalizeModelRecipe(source.model_recipe),
    external_research_status: toString(source.external_research_status, ''),
  };
}

function normalizeExternalIdeas(source: unknown): FactorLabResult['external_factor_ideas'] {
  if (!Array.isArray(source)) return [];
  return source
    .map((idea) => {
      if (!isRecord(idea)) return null;
      return {
        idea_id: toString(idea.idea_id, ''),
        name_cn: toString(idea.name_cn, ''),
        plain_text: toString(idea.plain_text, ''),
        status: toString(idea.status, ''),
        source_type: toString(idea.source_type, ''),
        mapped_factor: toString(idea.mapped_factor, ''),
      };
    })
    .filter(Boolean) as FactorLabResult['external_factor_ideas'];
}

function normalizeSelfIteration(source: unknown): FactorLabSelfIteration | null {
  if (!isRecord(source)) return null;
  const evidence = isRecord(source.evidence) ? source.evidence : {};
  const pipeline = isRecord(source.candidate_pipeline) ? source.candidate_pipeline : {};
  const stressGate = isRecord(source.stress_gate) ? source.stress_gate : {};
  const decision = isRecord(source.promotion_decision) ? source.promotion_decision : {};
  const production = isRecord(source.production_candidate) ? source.production_candidate : {};
  return {
    run_id: toString(source.run_id, ''),
    generated_at: toString(source.generated_at, ''),
    mode: toString(source.mode, ''),
    production_candidate: {
      candidate_id: toString(production.candidate_id, ''),
      score_source: toString(production.score_source, ''),
      leading_factor: toString(production.leading_factor, ''),
    },
    evidence: {
      score: toNumber(evidence.score, 0),
      note: toString(evidence.note, ''),
      metrics: normalizeNumberRecord(evidence.metrics),
    },
    candidate_pipeline: {
      generated: toNumber(pipeline.generated, 0),
      research_pass: toNumber(pipeline.research_pass, 0),
      shadow: toNumber(pipeline.shadow, 0),
      production_promoted: toNumber(pipeline.production_promoted, 0),
    },
    candidates: Array.isArray(source.candidates)
      ? source.candidates
          .map((candidate) => {
            if (!isRecord(candidate)) return null;
            return {
              candidate_id: toString(candidate.candidate_id, ''),
              name_cn: toString(candidate.name_cn, ''),
              status: toString(candidate.status, ''),
              parent_id: candidate.parent_id == null ? null : toString(candidate.parent_id, ''),
              formula: toString(candidate.formula, ''),
              feature_dependencies: Array.isArray(candidate.feature_dependencies)
                ? candidate.feature_dependencies.map((item) => String(item))
                : [],
              complexity_score: toNumber(candidate.complexity_score, 0),
              rationale: toString(candidate.rationale, ''),
            };
          })
          .filter(Boolean) as FactorLabSelfIteration['candidates']
      : [],
    stress_gate: {
      available: Boolean(stressGate.available),
      passed: Boolean(stressGate.passed),
      score: toNumber(stressGate.score, 0),
      failures: Array.isArray(stressGate.failures) ? stressGate.failures.map((item) => String(item)) : [],
      message: toString(stressGate.message, ''),
    },
    promotion_decision: {
      status: toString(decision.status, ''),
      decision: toString(decision.decision, ''),
      failures: Array.isArray(decision.failures) ? decision.failures.map((item) => String(item)) : [],
      next_action: toString(decision.next_action, ''),
    },
  };
}

function normalizeStressScenario(source: unknown): FactorLabStressScenario | null {
  if (!isRecord(source)) return null;
  const factors: FactorLabStressScenario['factors'] = {};
  if (isRecord(source.factors)) {
    Object.entries(source.factors).forEach(([factor, value]) => {
      if (!isRecord(value)) return;
      factors[factor] = {
        median_total_return: toNumber(value.median_total_return, 0),
        p05_total_return: toNumber(value.p05_total_return, 0),
        p95_total_return: toNumber(value.p95_total_return, 0),
        prob_positive: toNumber(value.prob_positive, 0),
        median_max_drawdown: toNumber(value.median_max_drawdown, 0),
        p95_max_drawdown_abs: toNumber(value.p95_max_drawdown_abs, 0),
        median_sharpe: toNumber(value.median_sharpe, 0),
        median_final_value: toNumber(value.median_final_value, 0),
        survival_rate: toNumber(value.survival_rate, 0),
        median_total_trades: toNumber(value.median_total_trades, 0),
      };
    });
  }
  return {
    scenario: toString(source.scenario, ''),
    name_cn: toString(source.name_cn, toString(source.scenario, '')),
    assumptions: isRecord(source.assumptions)
      ? {
          annual_drift: toNumber(source.assumptions.annual_drift, 0),
          annual_vol: toNumber(source.assumptions.annual_vol, 0),
          market_beta_bias: toNumber(source.assumptions.market_beta_bias, 0),
          mean_reversion: toNumber(source.assumptions.mean_reversion, 0),
        }
      : undefined,
    factors,
    sample_paths: Array.isArray(source.sample_paths)
      ? source.sample_paths
          .map((path) => {
            if (!isRecord(path)) return null;
            return {
              path_id: toNumber(path.path_id, 0),
              factor: toString(path.factor, ''),
              history: Array.isArray(path.history)
                ? path.history
                    .map((point) => {
                      if (!isRecord(point)) return null;
                      return {
                        date: toString(point.date, ''),
                        total_value: toNumber(point.total_value, 0),
                        drawdown: toNumber(point.drawdown, 0),
                      };
                    })
                    .filter(Boolean)
                : [],
            };
          })
          .filter(Boolean) as FactorLabStressScenario['sample_paths']
      : [],
  };
}

function normalizeStressTest(source: unknown): FactorLabStressTest | null {
  if (!isRecord(source)) return null;
  const config = isRecord(source.config) ? source.config : {};
  return {
    run_id: toString(source.run_id, ''),
    generated_at: toString(source.generated_at, ''),
    config: {
      pool: toString(config.pool, ''),
      max_symbols: toNumber(config.max_symbols, 0),
      top_n: toNumber(config.top_n, 0),
      horizon_days: toNumber(config.horizon_days, 0),
      paths_per_scenario: toNumber(config.paths_per_scenario, 0),
      seed: toNumber(config.seed, 0),
      anchor_date: toString(config.anchor_date, ''),
      symbols: toNumber(config.symbols, 0),
    },
    scenarios: Array.isArray(source.scenarios)
      ? (source.scenarios.map(normalizeStressScenario).filter(Boolean) as FactorLabStressScenario[])
      : [],
    disclaimer: toString(source.disclaimer, ''),
  };
}

function normalizeArtifactStatus(source: unknown): FactorLabArtifactStatus | null {
  if (!isRecord(source)) return null;
  return {
    ready: Boolean(source.ready),
    status: toString(source.status, ''),
    message: toString(source.message, ''),
    run_id: toString(source.run_id, ''),
    config_hash: toString(source.config_hash, ''),
    generated_at: toString(source.generated_at, ''),
    oos_start_date: toString(source.oos_start_date, ''),
    oos_end_date: toString(source.oos_end_date, ''),
    score_rows: source.score_rows !== undefined ? toNumber(source.score_rows, 0) : undefined,
    oos_score_rows: source.oos_score_rows !== undefined ? toNumber(source.oos_score_rows, 0) : undefined,
    model_available: source.model_available !== undefined ? Boolean(source.model_available) : undefined,
  };
}

function normalizeShadowLedger(source: unknown): StrategyVersionShadowLedger | undefined {
  if (!isRecord(source)) return undefined;
  return {
    version_id: toString(source.version_id, ''),
    strategy_id: toString(source.strategy_id, ''),
    shadow_strategy_id: toString(source.shadow_strategy_id, ''),
    started_at: toString(source.started_at, ''),
    status: toString(source.status, ''),
    observation_days: toNumber(source.observation_days, 0),
    latest_observation_date: source.latest_observation_date !== undefined && source.latest_observation_date !== null
      ? toString(source.latest_observation_date, '')
      : null,
    baseline_strategy_id: source.baseline_strategy_id !== undefined && source.baseline_strategy_id !== null
      ? toString(source.baseline_strategy_id, '')
      : null,
    note: source.note !== undefined && source.note !== null ? toString(source.note, '') : null,
    metrics: isRecord(source.metrics) ? source.metrics : {},
  };
}

function normalizeStrategyVersionIteration(source: unknown): StrategyVersionIteration | null {
  if (!isRecord(source)) return null;
  const objective = isRecord(source.objective) ? source.objective : {};
  const nextRunConfig = isRecord(source.next_run_config) ? source.next_run_config : {};
  return {
    iteration_id: toString(source.iteration_id, ''),
    parent_version_id: toString(source.parent_version_id, ''),
    strategy_id: toString(source.strategy_id, ''),
    source_run_id: toString(source.source_run_id, ''),
    config_hash: toString(source.config_hash, ''),
    artifact_ref: toString(source.artifact_ref, ''),
    artifact_hash: toString(source.artifact_hash, ''),
    mode: toString(source.mode, ''),
    status: toString(source.status, ''),
    created_at: toString(source.created_at, ''),
    created_by: source.created_by !== undefined && source.created_by !== null ? toString(source.created_by, '') : null,
    objective: {
      ...objective,
      summary: toString(objective.summary, ''),
      primary_blockers: Array.isArray(objective.primary_blockers) ? objective.primary_blockers.map((item) => String(item)) : [],
      research_failures: Array.isArray(objective.research_failures) ? objective.research_failures.map((item) => String(item)) : [],
      target_metrics: isRecord(objective.target_metrics) ? objective.target_metrics : {},
    },
    next_run_config: {
      ...nextRunConfig,
      mode: toString(nextRunConfig.mode, ''),
      parent_version_id: toString(nextRunConfig.parent_version_id, ''),
      strategy_id: toString(nextRunConfig.strategy_id, ''),
      source_run_id: toString(nextRunConfig.source_run_id, ''),
      candidate_factor: toString(nextRunConfig.candidate_factor, ''),
      config_hash: toString(nextRunConfig.config_hash, ''),
      artifact_ref: toString(nextRunConfig.artifact_ref, ''),
      locked_artifact_hash: toString(nextRunConfig.locked_artifact_hash, ''),
      constraints: Array.isArray(nextRunConfig.constraints) ? nextRunConfig.constraints.map((item) => String(item)) : [],
      suggested_actions: Array.isArray(nextRunConfig.suggested_actions)
        ? nextRunConfig.suggested_actions.filter(isRecord)
        : [],
    },
    actions: Array.isArray(source.actions)
      ? source.actions.filter(isRecord).map((action) => ({
          ...action,
          type: toString(action.type, ''),
          label: toString(action.label, ''),
          rationale: toString(action.rationale, ''),
          blocking: action.blocking !== undefined ? Boolean(action.blocking) : undefined,
        }))
      : [],
    result_version_id: source.result_version_id !== undefined && source.result_version_id !== null
      ? toString(source.result_version_id, '')
      : null,
    note: source.note !== undefined && source.note !== null ? toString(source.note, '') : null,
  };
}

function normalizeStrategyVersion(source: unknown): StrategyVersionRecord | null {
  if (!isRecord(source)) return null;
  const metrics = isRecord(source.metrics) ? source.metrics : {};
  const gates = isRecord(source.gates) ? source.gates : {};
  return {
    version_id: toString(source.version_id, ''),
    strategy_id: toString(source.strategy_id, ''),
    parent_version_id: source.parent_version_id !== undefined && source.parent_version_id !== null
      ? toString(source.parent_version_id, '')
      : null,
    source_run_id: toString(source.source_run_id, ''),
    config_hash: toString(source.config_hash, ''),
    artifact_ref: toString(source.artifact_ref, ''),
    status: toString(source.status, 'draft'),
    created_at: toString(source.created_at, ''),
    approved_at: source.approved_at !== undefined && source.approved_at !== null ? toString(source.approved_at, '') : null,
    approved_by: source.approved_by !== undefined && source.approved_by !== null ? toString(source.approved_by, '') : null,
    approval_note: source.approval_note !== undefined && source.approval_note !== null ? toString(source.approval_note, '') : null,
    active: source.active !== undefined ? Boolean(source.active) : undefined,
    metrics: {
      ...metrics,
      candidate_factor: toString(metrics.candidate_factor, ''),
      artifact_hash: toString(metrics.artifact_hash, ''),
      score_source: toString(metrics.score_source, ''),
      test_rank_ic: metrics.test_rank_ic !== undefined ? toNumber(metrics.test_rank_ic, 0) : undefined,
      with_cost_total_return: metrics.with_cost_total_return !== undefined ? toNumber(metrics.with_cost_total_return, 0) : undefined,
      annual_return: metrics.annual_return !== undefined ? toNumber(metrics.annual_return, 0) : undefined,
      max_drawdown_abs: metrics.max_drawdown_abs !== undefined ? toNumber(metrics.max_drawdown_abs, 0) : undefined,
      cost_drag: metrics.cost_drag !== undefined ? toNumber(metrics.cost_drag, 0) : undefined,
      walk_forward_coverage: metrics.walk_forward_coverage !== undefined ? toNumber(metrics.walk_forward_coverage, 0) : undefined,
      stress_gate_available: metrics.stress_gate_available !== undefined ? Boolean(metrics.stress_gate_available) : undefined,
      stress_gate_passed: metrics.stress_gate_passed !== undefined ? Boolean(metrics.stress_gate_passed) : undefined,
      tested_candidate_factors: metrics.tested_candidate_factors !== undefined ? toNumber(metrics.tested_candidate_factors, 0) : undefined,
      promoted_candidate_factors: metrics.promoted_candidate_factors !== undefined ? toNumber(metrics.promoted_candidate_factors, 0) : undefined,
      parent_strategy_name: toString(metrics.parent_strategy_name, ''),
    },
    gates: {
      oos_rank_ic_positive: gates.oos_rank_ic_positive !== undefined ? Boolean(gates.oos_rank_ic_positive) : undefined,
      with_cost_return_positive: gates.with_cost_return_positive !== undefined ? Boolean(gates.with_cost_return_positive) : undefined,
      max_drawdown_ok: gates.max_drawdown_ok !== undefined ? Boolean(gates.max_drawdown_ok) : undefined,
      cost_drag_ok: gates.cost_drag_ok !== undefined ? Boolean(gates.cost_drag_ok) : undefined,
      stress_test_passed: gates.stress_test_passed !== undefined ? Boolean(gates.stress_test_passed) : undefined,
      shadow_min_observation_passed: gates.shadow_min_observation_passed !== undefined ? Boolean(gates.shadow_min_observation_passed) : undefined,
      shadow_observation_days: gates.shadow_observation_days !== undefined ? toNumber(gates.shadow_observation_days, 0) : undefined,
      research_gate_passed: gates.research_gate_passed !== undefined ? Boolean(gates.research_gate_passed) : undefined,
      approval_gate_passed: gates.approval_gate_passed !== undefined ? Boolean(gates.approval_gate_passed) : undefined,
      failures: Array.isArray(gates.failures) ? gates.failures.map((item) => String(item)) : [],
      research_failures: Array.isArray(gates.research_failures) ? gates.research_failures.map((item) => String(item)) : [],
    },
    shadow: normalizeShadowLedger(source.shadow),
    latest_iteration: normalizeStrategyVersionIteration(source.latest_iteration),
  };
}

function normalizeStrategyLifecycle(source: unknown): FactorLabStrategyLifecycle | null {
  if (!isRecord(source)) return null;
  return {
    status: toString(source.status, ''),
    parent_strategy_id: toString(source.parent_strategy_id, ''),
    parent_strategy_name: toString(source.parent_strategy_name, ''),
    active_version_id: source.active_version_id !== undefined && source.active_version_id !== null
      ? toString(source.active_version_id, '')
      : null,
    current_run_id: toString(source.current_run_id, ''),
    current_run_versions: Array.isArray(source.current_run_versions)
      ? (source.current_run_versions.map(normalizeStrategyVersion).filter(Boolean) as StrategyVersionRecord[])
      : [],
    recent_versions: Array.isArray(source.recent_versions)
      ? (source.recent_versions.map(normalizeStrategyVersion).filter(Boolean) as StrategyVersionRecord[])
      : [],
    latest_iteration: normalizeStrategyVersionIteration(source.latest_iteration),
    next_action: toString(source.next_action, ''),
    decision: isRecord(source.decision)
      ? {
          status: toString(source.decision.status, ''),
          decision: toString(source.decision.decision, ''),
          failures: Array.isArray(source.decision.failures) ? source.decision.failures.map((item) => String(item)) : [],
          next_action: toString(source.decision.next_action, ''),
        }
      : undefined,
  };
}

function isMissingResultPayload(source: Record<string, unknown>): boolean {
  const summary = isRecord(source.summary) ? source.summary : null;
  if (summary && toString(summary.status, '') === 'missing') return true;
  return false;
}

function normalizeFactorLabResult(
  source: unknown,
  config: Partial<FactorLabRunConfig> = DEFAULT_FACTOR_LAB_RUN_CONFIG
): FactorLabResult | null {
  if (!isRecord(source) || isMissingResultPayload(source)) {
    return null;
  }

  const summarySource = isRecord(source.summary) ? source.summary : {};
  const nestedConfig = isRecord(summarySource.config) ? summarySource.config : {};
  const walkForwardSource = isRecord(summarySource.walk_forward) ? summarySource.walk_forward : undefined;
  const fallbackConfig = { ...DEFAULT_FACTOR_LAB_RUN_CONFIG, ...config };
  const summary: FactorLabSummary = {
    run_id: toString(summarySource.run_id, ''),
    start_date: toString(summarySource.start_date ?? nestedConfig.start_date ?? summarySource.date_start, fallbackConfig.start_date),
    end_date: toString(summarySource.end_date ?? nestedConfig.end_date ?? summarySource.date_end, fallbackConfig.end_date),
    pool: toString(summarySource.pool ?? nestedConfig.pool, fallbackConfig.pool),
    label: toString(summarySource.label ?? nestedConfig.label, fallbackConfig.label),
    top_n: toNumber(summarySource.top_n ?? nestedConfig.top_n, fallbackConfig.top_n),
    max_symbols: summarySource.max_symbols !== undefined || nestedConfig.max_symbols !== undefined
      ? toNumber(summarySource.max_symbols ?? nestedConfig.max_symbols, fallbackConfig.max_symbols)
      : fallbackConfig.max_symbols,
    total_symbols: summarySource.total_symbols !== undefined || summarySource.symbols !== undefined
      ? toNumber(summarySource.total_symbols ?? summarySource.symbols, 0)
      : undefined,
    train_samples: summarySource.train_samples !== undefined || (isRecord(summarySource.split_counts) && summarySource.split_counts.train !== undefined)
      ? toNumber(summarySource.train_samples ?? (isRecord(summarySource.split_counts) ? summarySource.split_counts.train : undefined), 0)
      : undefined,
    rows_raw: summarySource.rows_raw !== undefined ? toNumber(summarySource.rows_raw, 0) : undefined,
    rows_sample: summarySource.rows_sample !== undefined ? toNumber(summarySource.rows_sample, 0) : undefined,
    feature_count: summarySource.feature_count !== undefined ? toNumber(summarySource.feature_count, 0) : undefined,
    best_factor: summarySource.best_factor !== undefined ? toString(summarySource.best_factor, '') : undefined,
    best_model_test_rank_ic: summarySource.best_model_test_rank_ic !== undefined
      ? toNumber(summarySource.best_model_test_rank_ic, 0)
      : undefined,
    best_model_test_top20_ret: summarySource.best_model_test_top20_ret !== undefined
      ? toNumber(summarySource.best_model_test_top20_ret, 0)
      : undefined,
    inference_date: toString(summarySource.inference_date ?? summarySource.generated_at, ''),
    universe: toString(summarySource.universe, ''),
    sample_source_note: toString(summarySource.sample_source_note, ''),
    universe_selection: isRecord(summarySource.universe_selection)
      ? {
          requested_pool: toString(summarySource.universe_selection.requested_pool, ''),
          selection_method: toString(summarySource.universe_selection.selection_method, ''),
          method_cn: toString(summarySource.universe_selection.method_cn, ''),
          local_universe_size: summarySource.universe_selection.local_universe_size !== undefined
            ? toNumber(summarySource.universe_selection.local_universe_size, 0)
            : undefined,
          prescreen_universe_size: summarySource.universe_selection.prescreen_universe_size !== undefined
            ? toNumber(summarySource.universe_selection.prescreen_universe_size, 0)
            : undefined,
          requested_max_symbols: summarySource.universe_selection.requested_max_symbols !== undefined && summarySource.universe_selection.requested_max_symbols !== null
            ? toNumber(summarySource.universe_selection.requested_max_symbols, 0)
            : null,
          selected_symbols: summarySource.universe_selection.selected_symbols !== undefined
            ? toNumber(summarySource.universe_selection.selected_symbols, 0)
            : undefined,
          deep_research_symbols: summarySource.universe_selection.deep_research_symbols !== undefined
            ? toNumber(summarySource.universe_selection.deep_research_symbols, 0)
            : undefined,
          is_budget_sample: Boolean(summarySource.universe_selection.is_budget_sample),
          deep_scored_all_symbols: summarySource.universe_selection.deep_scored_all_symbols !== undefined
            ? Boolean(summarySource.universe_selection.deep_scored_all_symbols)
            : undefined,
          availability_cutoff: summarySource.universe_selection.availability_cutoff !== undefined && summarySource.universe_selection.availability_cutoff !== null
            ? toString(summarySource.universe_selection.availability_cutoff, '')
            : null,
          history_coverage_start: summarySource.universe_selection.history_coverage_start !== undefined && summarySource.universe_selection.history_coverage_start !== null
            ? toString(summarySource.universe_selection.history_coverage_start, '')
            : null,
          legacy_result: summarySource.universe_selection.legacy_result !== undefined
            ? Boolean(summarySource.universe_selection.legacy_result)
            : undefined,
          rerun_selection_method: toString(summarySource.universe_selection.rerun_selection_method, ''),
          sample_refresh_rule: toString(summarySource.universe_selection.sample_refresh_rule, ''),
        }
      : undefined,
    research_note: toString(summarySource.research_note, ''),
    run_difference_note: toString(summarySource.run_difference_note, ''),
    run_difference_reasons: Array.isArray(summarySource.run_difference_reasons)
      ? summarySource.run_difference_reasons.map((item) => String(item))
      : [],
    score_source: summarySource.score_source !== undefined ? toString(summarySource.score_source, '') : undefined,
    model_recipe: normalizeModelRecipe(summarySource.model_recipe),
    walk_forward: walkForwardSource
      ? {
          enabled: Boolean(walkForwardSource.enabled),
          score_source: toString(walkForwardSource.score_source, ''),
          first_prediction_date: toString(walkForwardSource.first_prediction_date, ''),
          last_prediction_date: toString(walkForwardSource.last_prediction_date, ''),
          retrain_windows: walkForwardSource.retrain_windows !== undefined
            ? toNumber(walkForwardSource.retrain_windows, 0)
            : undefined,
          retrain_interval_dates: walkForwardSource.retrain_interval_dates !== undefined
            ? toNumber(walkForwardSource.retrain_interval_dates, 0)
            : undefined,
          coverage_ratio: walkForwardSource.coverage_ratio !== undefined
            ? toNumber(walkForwardSource.coverage_ratio, 0)
            : undefined,
          message: toString(walkForwardSource.message, ''),
        }
      : undefined,
  };

  return {
    summary,
    factor_ranking: normalizeFactorRanking(source.factor_ranking),
    feature_importance: normalizeFeatureImportance(source.feature_importance),
    factor_weights: normalizeFactorWeights(source.factor_weights),
    research_iteration: normalizeResearchIteration(source.research_iteration),
    external_factor_ideas: normalizeExternalIdeas(source.external_factor_ideas),
    model_metrics: normalizeMetricEntries(source.model_metrics),
    bucket_returns: normalizeBucketReturns(source.bucket_returns),
    stability: normalizeMetricEntries(source.stability),
    backtest: normalizeBacktest(source.backtest),
    run_readiness: normalizeReadiness(source.run_readiness),
    strategy_backtests: normalizeStrategyBacktests(source.strategy_backtests),
    backtest_compare: isRecord(source.backtest_compare)
      ? {
          factors: Array.isArray(source.backtest_compare.factors) ? source.backtest_compare.factors.map((item) => String(item)) : [],
          best_total_return_factor: toString(source.backtest_compare.best_total_return_factor, ''),
        }
      : undefined,
    scores_preview: normalizeScoresPreview(source.scores_preview),
    data_sources_used: normalizeDataSources(source.data_sources_used),
    self_iteration: normalizeSelfIteration(source.self_iteration),
    stress_test: normalizeStressTest(source.stress_test),
    artifact_status: normalizeArtifactStatus(source.artifact_status),
    strategy_lifecycle: normalizeStrategyLifecycle(source.strategy_lifecycle),
  };
}

function buildBacktestRequest(config: FactorLabRunConfig) {
  return {
    start_date: config.start_date,
    end_date: config.end_date,
    initial_capital: 1000000,
    factor: 'ml_factor_ranker',
    commission_rate: 0.0003,
    slippage_rate: 0.0003,
    pool: config.pool,
    max_positions: config.top_n,
    weight_mode: 'score',
    stop_loss: -0.08,
    label: config.label,
    top_n: config.top_n,
    max_symbols: config.max_symbols,
  };
}

function buildStressTestRequest(config: FactorLabRunConfig) {
  return {
    pool: config.pool,
    max_symbols: Math.max(3, Math.min(config.max_symbols ?? 300, 500)),
    top_n: config.top_n,
    initial_capital: 1000000,
    factors: ['ml_factor_ranker'],
    horizon_days: 260,
    paths_per_scenario: 2,
    seed: 42,
    scenarios: ['bull', 'bear', 'sideways'],
    anchor_date: config.end_date,
    lookback_days: 260,
    commission_rate: 0.0003,
    stamp_tax_rate: 0.001,
    slippage_rate: 0.0003,
    stop_loss: -0.08,
  };
}

function buildFailure(
  action: FactorLabFailureState['action'],
  error: unknown,
  config?: FactorLabRunConfig,
  fallbackDetail = 'Factor Lab 请求失败'
): FactorLabFailureState {
  const payload = getApiErrorPayload(error);
  if (payload) {
    const detail = isRecord(payload)
      ? toString(payload.detail, getApiErrorMessage(error, fallbackDetail))
      : getApiErrorMessage(error, fallbackDetail);
    return {
      action,
      detail,
      error_code: isRecord(payload) ? toString(payload.error_code, '') || null : null,
      config,
      run_readiness: isRecord(payload) ? normalizeReadiness(payload.run_readiness) : null,
    };
  }

  if (error instanceof Error) {
    return {
      action,
      detail: error.message || fallbackDetail,
      error_code: null,
      config,
      run_readiness: null,
    };
  }

  return {
    action,
    detail: fallbackDetail,
    error_code: null,
    config,
    run_readiness: null,
  };
}

async function fetchReadiness(config: FactorLabRunConfig, signal?: AbortSignal): Promise<{
  readiness: FactorLabRunReadiness | null;
  failure: FactorLabFailureState | null;
}> {
  try {
    const response = await apiPost<unknown>('/api/factor-lab/readiness', config, { timeout: 20000, signal });
    const payload = isRecord(response) ? response.run_readiness ?? response : response;
    return {
      readiness: normalizeReadiness(payload),
      failure: null,
    };
  } catch (error) {
    if (isRequestCanceled(error)) {
      return {
        readiness: null,
        failure: null,
      };
    }
    const failure = buildFailure('checkReadiness', error, config, '运行前检查失败');
    return {
      readiness: failure.run_readiness ?? null,
      failure,
    };
  }
}

export function useFactorLab(currentConfig?: FactorLabRunConfig) {
  const effectiveConfig = currentConfig ?? DEFAULT_FACTOR_LAB_RUN_CONFIG;
  const [state, setState] = useState<FactorLabHookState>({
    result: null,
    latestRealResult: null,
    readiness: null,
    checkingReadiness: false,
    loading: false,
    loadingAction: null,
    error: null,
    notice: null,
    lastFailure: null,
    versionActionLoading: null,
  });
  const requestSeq = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  const updateState = useCallback((patch: Partial<FactorLabHookState>) => {
    setState((prev) => ({ ...prev, ...patch }));
  }, []);

  const beginRequest = useCallback(() => {
    const requestId = requestSeq.current + 1;
    requestSeq.current = requestId;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    return { requestId, signal: controller.signal };
  }, []);

  const isLatestRequest = useCallback((requestId: number) => requestSeq.current === requestId, []);

  const loadLatest = useCallback(async () => {
    const { requestId, signal } = beginRequest();
    updateState({ loading: true, loadingAction: 'load', error: null, notice: null, lastFailure: null });
    try {
      const response = await apiGet<unknown>('/api/factor-lab/results', { timeout: 20000, signal });
      if (!isLatestRequest(requestId)) return null;
      const normalized = normalizeFactorLabResult(response, DEFAULT_FACTOR_LAB_RUN_CONFIG);
      setState((prev) => ({
        ...prev,
        result: normalized,
        latestRealResult: normalized,
        readiness: normalized?.run_readiness ?? prev.readiness,
        loading: false,
        loadingAction: null,
        error: null,
        notice: normalized ? null : '暂无历史真实结果。',
        lastFailure: null,
      }));
    } catch (error) {
      if (isRequestCanceled(error) || !isLatestRequest(requestId)) return null;
      const failure = buildFailure('loadLatest', error, undefined, '读取最新真实结果失败');
      setState((prev) => ({
        ...prev,
        result: prev.latestRealResult,
        readiness: failure.run_readiness ?? prev.readiness,
        loading: false,
        loadingAction: null,
        error: failure.detail,
        notice: prev.latestRealResult ? PREVIOUS_REAL_RESULT_NOTICE : null,
        lastFailure: failure,
      }));
      console.error(error);
    }
  }, [beginRequest, isLatestRequest, updateState]);

  const runResearch = async (config: FactorLabRunConfig) => {
    const { requestId, signal } = beginRequest();
    updateState({
      loading: true,
      loadingAction: 'run',
      checkingReadiness: true,
      error: null,
      notice: null,
      lastFailure: null,
    });

    const { readiness, failure: readinessFailure } = await fetchReadiness(config, signal);
    if (!isLatestRequest(requestId)) return null;
    if (readinessFailure) {
      const failure: FactorLabFailureState = {
        action: 'runResearch',
        detail: readinessFailure.detail,
        error_code: readinessFailure.error_code,
        config,
        run_readiness: readiness ?? readinessFailure.run_readiness,
      };
      setState((prev) => ({
        ...prev,
        result: prev.latestRealResult,
        readiness: readiness ?? prev.readiness,
        checkingReadiness: false,
        loading: false,
        loadingAction: null,
        error: failure.detail,
        notice: prev.latestRealResult ? PREVIOUS_REAL_RESULT_NOTICE : null,
        lastFailure: failure,
      }));
      return null;
    }

    try {
      const response = await apiPost<unknown>('/api/factor-lab/run', config, { timeout: 600000, signal });
      if (!isLatestRequest(requestId)) return null;
      const normalized = normalizeFactorLabResult(response, config);
      if (!normalized) {
        throw new Error('后端未返回可展示的真实研究结果。');
      }
      setState((prev) => ({
        ...prev,
        result: normalized,
        latestRealResult: normalized,
        readiness: normalized.run_readiness ?? readiness ?? prev.readiness,
        checkingReadiness: false,
        loading: false,
        loadingAction: null,
        error: null,
        notice: null,
        lastFailure: null,
      }));
      return normalized;
    } catch (error) {
      if (isRequestCanceled(error) || !isLatestRequest(requestId)) return null;
      const failure = buildFailure('runResearch', error, config, '因子研究执行失败');
      setState((prev) => ({
        ...prev,
        result: prev.latestRealResult,
        readiness: failure.run_readiness ?? readiness ?? prev.readiness,
        checkingReadiness: false,
        loading: false,
        loadingAction: null,
        error: failure.detail,
        notice: prev.latestRealResult ? PREVIOUS_REAL_RESULT_NOTICE : null,
        lastFailure: failure,
      }));
      console.error(error);
      return null;
    }
  };

  const runBacktest = async (config: FactorLabRunConfig) => {
    const { requestId, signal } = beginRequest();
    updateState({ loading: true, loadingAction: 'backtest', error: null, notice: null, lastFailure: null });
    try {
      const response = await apiPost<unknown>('/api/factor-lab/backtest', buildBacktestRequest(config), { timeout: 180000, signal });
      if (!isLatestRequest(requestId)) return null;
      const backtest = normalizeBacktest(response);
      if (!backtest) {
        throw new Error('后端未返回有效的回测摘要。');
      }
      setState((prev) => {
        const baseResult = prev.result ?? prev.latestRealResult;
        const nextResult = baseResult ? { ...baseResult, backtest } : null;
        return {
          ...prev,
          result: nextResult ?? null,
          loading: false,
          loadingAction: null,
          error: null,
          notice: null,
          lastFailure: null,
        };
      });
      return backtest;
    } catch (error) {
      if (isRequestCanceled(error) || !isLatestRequest(requestId)) return null;
      const failure = buildFailure('runBacktest', error, config, 'ML 回测执行失败');
      setState((prev) => {
        const fallbackBacktest = prev.latestRealResult?.backtest ?? null;
        const baseResult = prev.result ?? prev.latestRealResult;
        const nextResult = baseResult ? { ...baseResult, backtest: fallbackBacktest } : null;
        return {
          ...prev,
          result: nextResult,
          readiness: failure.run_readiness ?? prev.readiness,
          loading: false,
          loadingAction: null,
          error: failure.detail,
          notice: fallbackBacktest ? PREVIOUS_REAL_RESULT_NOTICE : null,
          lastFailure: failure,
        };
      });
      console.error(error);
      return state.latestRealResult?.backtest ?? null;
    }
  };

  const runStressTest = async (config: FactorLabRunConfig) => {
    const { requestId, signal } = beginRequest();
    updateState({ loading: true, loadingAction: 'stress', error: null, notice: null, lastFailure: null });
    try {
      const response = await apiPost<unknown>('/api/factor-lab/stress-test', buildStressTestRequest(config), { timeout: 240000, signal });
      if (!isLatestRequest(requestId)) return null;
      const payload = isRecord(response) ? response : {};
      const stressTest = normalizeStressTest(payload.stress_test);
      const selfIteration = normalizeSelfIteration(payload.self_iteration);
      const strategyLifecycle = normalizeStrategyLifecycle(payload.strategy_lifecycle);
      if (!stressTest) {
        throw new Error('后端未返回有效的三行情景测评结果。');
      }
      setState((prev) => {
        const baseResult = prev.result ?? prev.latestRealResult;
        const nextResult = baseResult ? {
          ...baseResult,
          stress_test: stressTest,
          self_iteration: selfIteration ?? baseResult.self_iteration ?? null,
          strategy_lifecycle: strategyLifecycle ?? baseResult.strategy_lifecycle ?? null,
        } : null;
        return {
          ...prev,
          result: nextResult,
          latestRealResult: nextResult ?? prev.latestRealResult,
          loading: false,
          loadingAction: null,
          error: null,
          notice: nextResult ? '三行情景测评已完成，候选版本门禁已刷新。' : '三行情景测评已完成，请先生成一次策略体检报告后再查看完整结论。',
          lastFailure: null,
        };
      });
      return stressTest;
    } catch (error) {
      if (isRequestCanceled(error) || !isLatestRequest(requestId)) return null;
      const failure = buildFailure('runStressTest', error, config, '三行情景测评执行失败');
      setState((prev) => ({
        ...prev,
        result: prev.latestRealResult,
        readiness: failure.run_readiness ?? prev.readiness,
        loading: false,
        loadingAction: null,
        error: failure.detail,
        notice: prev.latestRealResult ? PREVIOUS_REAL_RESULT_NOTICE : null,
        lastFailure: failure,
      }));
      console.error(error);
      return null;
    }
  };

  const runVersionAction = async (
    actionKey: string,
    path: string,
    body?: unknown,
    successNotice = '策略版本状态已更新。'
  ) => {
    const { requestId, signal } = beginRequest();
    updateState({ loading: true, loadingAction: null, versionActionLoading: actionKey, error: null, notice: null, lastFailure: null });
    try {
      await apiPost<unknown>(path, body, { timeout: 60000, signal });
      if (!isLatestRequest(requestId)) return null;
      const latest = await apiGet<unknown>('/api/factor-lab/results', { timeout: 20000, signal });
      if (!isLatestRequest(requestId)) return null;
      const normalized = normalizeFactorLabResult(latest, DEFAULT_FACTOR_LAB_RUN_CONFIG);
      setState((prev) => ({
        ...prev,
        result: normalized ?? prev.result,
        latestRealResult: normalized ?? prev.latestRealResult,
        readiness: normalized?.run_readiness ?? prev.readiness,
        loading: false,
        loadingAction: null,
        versionActionLoading: null,
        error: null,
        notice: successNotice,
        lastFailure: null,
      }));
      return normalized;
    } catch (error) {
      if (isRequestCanceled(error) || !isLatestRequest(requestId)) return null;
      const failure = buildFailure('versionAction', error, undefined, '策略版本操作失败');
      setState((prev) => ({
        ...prev,
        loading: false,
        loadingAction: null,
        versionActionLoading: null,
        error: failure.detail,
        notice: prev.latestRealResult ? PREVIOUS_REAL_RESULT_NOTICE : null,
        lastFailure: failure,
      }));
      console.error(error);
      return null;
    }
  };

  const promoteCurrentRun = async (runId: string, candidateFactor = 'ml_factor_ranker') => (
    runVersionAction(
      `promote:${runId}`,
      `/api/factor-lab/candidates/${encodeURIComponent(runId)}/promote`,
      {
        strategy_id: 'ai_ml',
        candidate_factor: candidateFactor,
        created_by: 'local_user',
        note: '从 Factor Lab 前端提升为候选策略版本',
      },
      '已生成候选策略版本。'
    )
  );

  const startShadow = async (versionId: string) => (
    runVersionAction(
      `shadow:${versionId}`,
      `/api/strategy-versions/${encodeURIComponent(versionId)}/shadow`,
      { user: 'local_user', note: '从 Factor Lab 前端启动影子观察' },
      '已启动影子观察账户。'
    )
  );

  const approveVersion = async (versionId: string) => (
    runVersionAction(
      `approve:${versionId}`,
      `/api/strategy-versions/${encodeURIComponent(versionId)}/approve`,
      { user: 'local_user', note: 'Factor Lab 门禁通过后审批' },
      '候选版本已审批。'
    )
  );

  const activateVersion = async (versionId: string, strategyId = 'ai_ml') => (
    runVersionAction(
      `activate:${versionId}`,
      `/api/strategies/${encodeURIComponent(strategyId)}/activate-version`,
      { version_id: versionId, user: 'local_user', note: '切换 Factor Lab 活动版本' },
      '活动版本已切换。'
    )
  );

  const rollbackVersion = async (strategyId = 'ai_ml') => (
    runVersionAction(
      `rollback:${strategyId}`,
      `/api/strategies/${encodeURIComponent(strategyId)}/rollback`,
      { user: 'local_user', reason: 'Factor Lab 前端请求回滚' },
      '策略已回滚到上一版本或基线。'
    )
  );

  const iterateVersion = async (versionId: string) => (
    runVersionAction(
      `iterate:${versionId}`,
      `/api/strategy-versions/${encodeURIComponent(versionId)}/iterate`,
      { user: 'local_user', note: '从 Factor Lab 前端创建候选定向迭代计划' },
      '已生成候选定向迭代计划。'
    )
  );

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const syncReadiness = async () => {
      setState((prev) => ({ ...prev, checkingReadiness: true }));
      const { readiness, failure } = await fetchReadiness(effectiveConfig, controller.signal);
      if (!active) return;
      setState((prev) => ({
        ...prev,
        readiness: readiness ?? prev.readiness,
        checkingReadiness: false,
        notice: failure ? `运行前检查失败：${failure.detail}` : prev.notice,
        lastFailure: failure ?? prev.lastFailure,
      }));
    };
    void syncReadiness();
    return () => {
      active = false;
      controller.abort();
    };
  }, [effectiveConfig]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadLatest();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadLatest]);

  return {
    ...state,
    loadLatest,
    runResearch,
    runBacktest,
    runStressTest,
    promoteCurrentRun,
    startShadow,
    approveVersion,
    activateVersion,
    rollbackVersion,
    iterateVersion,
  };
}
