import { marketDate } from '../../api/marketDate';
/**
 * Factor Lab /results /run 响应主体的运行时收敛。
 * 字段表驱动 (见 parse.ts)；生命周期/压测相关见 normalizeLifecycle.ts。
 */
import { assertBacktestResult } from '../../api/guards';
import type {
  BacktestResult,
  FactorLabBucketReturnItem,
  FactorLabExternalIdea,
  FactorLabFactorRankingItem,
  FactorLabFactorWeightItem,
  FactorLabFeatureImportanceItem,
  FactorLabMetricItem,
  FactorLabModelRecipe,
  FactorLabPool,
  FactorLabResearchIteration,
  FactorLabResult,
  FactorLabRunConfig,
  FactorLabRunReadiness,
  FactorLabScorePreviewItem,
  FactorLabStrategyBacktest,
  FactorLabStrategyUserView,
  FactorLabSummary,
  FactorLabWalkForwardSummary,
} from '../../types';
import {
  firstOf,
  isRecord,
  mapItems,
  parseFields,
  parseFieldsOrNull,
  toNum,
  toStr,
  toStrArray,
} from './parse';
import {
  normalizeArtifactStatus,
  normalizeSelfIteration,
  normalizeStrategyLifecycle,
  normalizeStressTest,
} from './normalizeLifecycle';

/** 可选回看区间下界(本地数据湖起始年份) */
export const DEFAULT_START_DATE = '2022-01-01';
/** 可选回看区间上界(今天) */
export const DEFAULT_END_DATE = marketDate();

export const DEFAULT_FACTOR_LAB_RUN_CONFIG: FactorLabRunConfig = {
  start_date: DEFAULT_START_DATE,
  end_date: DEFAULT_END_DATE,
  pool: 'core',
  label: 'next_5d_ret',
  top_n: 5,
  max_symbols: 300,
};

const FACTOR_LAB_POOLS: FactorLabPool[] = ['core', 'blackhorse', 'all'];

export function isFactorLabPool(value: unknown): value is FactorLabPool {
  return typeof value === 'string' && (FACTOR_LAB_POOLS as string[]).includes(value);
}

const METRIC_LABEL_MAP: Record<string, string> = {
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

function inferMetricFormat(key: string): FactorLabMetricItem['format'] {
  if (/coverage|return|drawdown|win_rate|positive_month_ratio|gap/.test(key)) return 'percent';
  if (/count|samples|symbols|top_n|trades/.test(key)) return 'integer';
  if (/auc|ic|rank_ic|ir|sharpe|precision|recall|f1|accuracy/.test(key)) return 'ratio';
  return 'number';
}

function prettifyLabel(key: string): string {
  return METRIC_LABEL_MAP[key] || key.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

export function normalizeReadiness(source: unknown): FactorLabRunReadiness | null {
  return parseFieldsOrNull<FactorLabRunReadiness>(source, {
    requested_start_date: 'str',
    requested_end_date: 'str',
    effective_warmup_start: 'str|null',
    cache_window_start: 'str|null',
    cache_window_end: 'str|null',
    missing_start: 'str|null',
    missing_end: 'str|null',
    needs_backfill: 'bool',
    warning_message: 'str|null',
    checked_symbols: 'str[]',
  });
}

function metricFromPair(key: string, value: unknown): FactorLabMetricItem {
  if (isRecord(value)) {
    return {
      key,
      label: toStr(value.label, prettifyLabel(key)),
      value: typeof value.value === 'string' ? value.value : toNum(value.value),
      format: (value.format as FactorLabMetricItem['format']) ?? inferMetricFormat(key),
      note: toStr(value.note),
    };
  }
  return {
    key,
    label: prettifyLabel(key),
    value: typeof value === 'string' ? value : toNum(value),
    format: inferMetricFormat(key),
  };
}

export function normalizeMetricEntries(source: unknown): FactorLabMetricItem[] {
  if (Array.isArray(source)) {
    return mapItems(source, (entry, index) => {
      if (!isRecord(entry)) return null;
      const key = toStr(firstOf(entry, ['key', 'metric', 'name']), `metric_${index}`);
      return {
        key,
        label: toStr(entry.label, prettifyLabel(key)),
        value: typeof entry.value === 'string' ? entry.value : toNum(entry.value),
        format: (entry.format as FactorLabMetricItem['format']) ?? inferMetricFormat(key),
        note: toStr(entry.note),
      };
    });
  }
  if (isRecord(source)) {
    return Object.entries(source).map(([key, value]) => metricFromPair(key, value));
  }
  return [];
}

const RANKING_FIELDS = {
  score: 'num',
  ic: 'num?',
  rank_ic: 'num?',
  coverage: 'num?',
  stability: 'num?',
  direction: 'str',
} as const;

export function normalizeFactorRanking(source: unknown): FactorLabFactorRankingItem[] {
  if (Array.isArray(source)) {
    return mapItems(source, (entry) => {
      if (!isRecord(entry)) return null;
      const factor = toStr(firstOf(entry, ['factor', 'name', 'feature']));
      if (!factor) return null;
      return { factor, ...parseFields<Omit<FactorLabFactorRankingItem, 'factor'>>(entry, RANKING_FIELDS) };
    });
  }
  if (isRecord(source)) {
    return Object.entries(source).map(([factor, value]) =>
      isRecord(value)
        ? { factor, ...parseFields<Omit<FactorLabFactorRankingItem, 'factor'>>(value, RANKING_FIELDS) }
        : { factor, score: toNum(value) }
    );
  }
  return [];
}

export function normalizeFeatureImportance(source: unknown): FactorLabFeatureImportanceItem[] {
  const fromRecord = (feature: string, value: Record<string, unknown>): FactorLabFeatureImportanceItem => ({
    feature,
    importance: toNum(firstOf(value, ['importance', 'score'])),
    group: toStr(value.group),
    direction: toStr(firstOf(value, ['direction', 'sign'])),
  });
  if (Array.isArray(source)) {
    return mapItems(source, (entry) => {
      if (!isRecord(entry)) return null;
      const feature = toStr(firstOf(entry, ['feature', 'name']));
      return feature ? fromRecord(feature, entry) : null;
    });
  }
  if (isRecord(source)) {
    return Object.entries(source).map(([feature, value]) =>
      isRecord(value) ? fromRecord(feature, value) : { feature, importance: toNum(value) }
    );
  }
  return [];
}

export function normalizeFactorWeights(source: unknown): FactorLabFactorWeightItem[] {
  return mapItems(source, (entry) => {
    if (!isRecord(entry)) return null;
    const feature = toStr(firstOf(entry, ['feature', 'factor', 'name']));
    if (!feature) return null;
    return {
      feature,
      weight: toNum(firstOf(entry, ['weight', 'importance'])),
      ...parseFields<Omit<FactorLabFactorWeightItem, 'feature' | 'weight'>>(entry, {
        name_cn: 'str',
        group: 'str',
        importance: 'num?',
        direction: 'str',
        direction_text: 'str',
        explanation: 'str',
        rank_ic: 'num?',
        recent_rank_ic: 'num?',
        source: 'str',
      }),
    };
  });
}

export function normalizeBucketReturns(source: unknown): FactorLabBucketReturnItem[] {
  const extras = { excess_return: 'num?', win_rate: 'num?', samples: 'num?' } as const;
  if (Array.isArray(source)) {
    return mapItems(source, (entry, index) => {
      if (!isRecord(entry)) return null;
      const bucket = toStr(firstOf(entry, ['bucket', 'group', 'label']), `Bucket ${index + 1}`);
      return {
        bucket,
        return: toNum(firstOf(entry, ['return', 'ret'])),
        ...parseFields<Omit<FactorLabBucketReturnItem, 'bucket' | 'return'>>(entry, extras),
      };
    });
  }
  if (isRecord(source)) {
    return Object.entries(source).map(([bucket, value]) =>
      isRecord(value)
        ? {
            bucket,
            return: toNum(firstOf(value, ['return', 'ret'])),
            ...parseFields<Omit<FactorLabBucketReturnItem, 'bucket' | 'return'>>(value, extras),
          }
        : { bucket, return: toNum(value) }
    );
  }
  return [];
}

export function normalizeScoresPreview(source: unknown): FactorLabScorePreviewItem[] {
  return mapItems(source, (entry) => {
    if (!isRecord(entry)) return null;
    const stockCode = toStr(firstOf(entry, ['stock_code', 'symbol', 'code']));
    if (!stockCode) return null;
    return {
      stock_code: stockCode,
      stock_name: toStr(firstOf(entry, ['stock_name', 'name']), stockCode),
      ...parseFields<Omit<FactorLabScorePreviewItem, 'stock_code' | 'stock_name'>>(entry, {
        date: 'str',
        score: 'num?',
        daily_rank: 'num?',
        signal: 'num?',
        is_oos_score: 'bool?',
        score_source: 'str',
        close: 'num?',
      }),
    };
  });
}

export function normalizeDataSources(source: unknown): Record<string, string> | undefined {
  if (!isRecord(source)) return undefined;
  const normalized = Object.entries(source).reduce<Record<string, string>>((acc, [symbol, dataSource]) => {
    acc[symbol] = String(dataSource);
    return acc;
  }, {});
  return Object.keys(normalized).length > 0 ? normalized : undefined;
}

export function normalizeBacktest(source: unknown): BacktestResult | null {
  if (!isRecord(source) || !isRecord(source.summary)) return null;
  return assertBacktestResult(source);
}

export function normalizeUserView(source: unknown): FactorLabStrategyUserView | undefined {
  if (!isRecord(source)) return undefined;
  return {
    ...parseFields<Omit<FactorLabStrategyUserView, 'cost_drag'>>(source, {
      name_cn: 'str',
      description_cn: 'str',
      focus_points: 'str[]',
      suitable_for: 'str[]',
      total_return: 'num',
      annual_return: 'num',
      max_drawdown: 'num',
      win_rate: 'num',
      trigger_days: 'num',
      total_trades: 'num',
      last_signal_date: 'str|null',
      recent_signal_symbols: 'str[]',
    }),
    cost_drag: isRecord(source.cost_drag)
      ? parseFields<NonNullable<FactorLabStrategyUserView['cost_drag']>>(source.cost_drag, {
          total_return_diff: 'num',
          annual_return_diff: 'num',
          cost_pct_initial: 'num',
        })
      : undefined,
  };
}

const EMPTY_BACKTEST_SUMMARY = {
  initial_capital: 0,
  final_value: 0,
  max_drawdown: 0,
  sharpe_ratio: 0,
};

function normalizeCostLeg(source: Record<string, unknown>): FactorLabStrategyBacktest['with_cost'] {
  return {
    total_return: toNum(source.total_return),
    summary: (source.summary as BacktestResult['summary']) ?? EMPTY_BACKTEST_SUMMARY,
    resolved_pool: source.resolved_pool as BacktestResult['resolved_pool'],
  };
}

export function normalizeStrategyBacktests(source: unknown): Record<string, FactorLabStrategyBacktest> | undefined {
  if (!isRecord(source)) return undefined;
  const normalized: Record<string, FactorLabStrategyBacktest> = {};
  Object.entries(source).forEach(([key, value]) => {
    if (!isRecord(value) || !isRecord(value.with_cost) || !isRecord(value.without_cost)) return;
    normalized[key] = {
      factor: toStr(value.factor, key),
      with_cost: normalizeCostLeg(value.with_cost),
      without_cost: normalizeCostLeg(value.without_cost),
      cost_drag: parseFields<FactorLabStrategyBacktest['cost_drag']>(value.cost_drag, {
        total_return_diff: 'num',
        annual_return_diff: 'num',
        cost_pct_initial: 'num',
      }),
      user_view: normalizeUserView(value.user_view),
    };
  });
  return Object.keys(normalized).length > 0 ? normalized : undefined;
}

export function normalizeModelRecipe(source: unknown): FactorLabModelRecipe | undefined {
  return parseFieldsOrNull<FactorLabModelRecipe>(source, {
    baseline_model: 'str',
    nonlinear_model: 'str',
    nonlinear_v2_model: 'str',
    nonlinear_v2_weight: 'num?',
    baseline_weight: 'num?',
    nonlinear_weight: 'num?',
    selection_metric: 'str',
    selection_split: 'str',
    valid_rank_ic: 'num?',
    valid_top20_ret: 'num?',
    reason: 'str',
  }) ?? undefined;
}

export function normalizeResearchIteration(source: unknown): FactorLabResearchIteration | null {
  if (!isRecord(source)) return null;
  return {
    mode: toStr(source.mode),
    actions: toStrArray(source.actions),
    tested_candidate_factors: source.tested_candidate_factors !== undefined ? toNum(source.tested_candidate_factors) : undefined,
    promoted_candidate_factors: source.promoted_candidate_factors !== undefined ? toNum(source.promoted_candidate_factors) : undefined,
    promotion_cutoff: source.promotion_cutoff == null ? null : toNum(source.promotion_cutoff),
    candidates: mapItems(source.candidates, (candidate) =>
      isRecord(candidate)
        ? parseFields<NonNullable<FactorLabResearchIteration['candidates']>[number]>(candidate, {
            factor: 'str',
            name_cn: 'str',
            status: 'str',
            formula: 'str',
            dependencies: 'str[]',
            score: 'num?',
            rank_ic: 'num?',
            recent_rank_ic: 'num?',
            test_rank_ic: 'num?',
            reason: 'str',
          })
        : null
    ),
    model_recipe: normalizeModelRecipe(source.model_recipe),
    external_research_status: toStr(source.external_research_status),
  };
}

export function normalizeExternalIdeas(source: unknown): FactorLabExternalIdea[] {
  return mapItems(source, (idea) =>
    isRecord(idea)
      ? parseFields<FactorLabExternalIdea>(idea, {
          idea_id: 'str',
          name_cn: 'str',
          plain_text: 'str',
          status: 'str',
          source_type: 'str',
          mapped_factor: 'str',
        })
      : null
  );
}

function normalizeUniverseSelection(source: unknown): FactorLabSummary['universe_selection'] {
  return parseFieldsOrNull<NonNullable<FactorLabSummary['universe_selection']>>(source, {
    requested_pool: 'str',
    selection_method: 'str',
    method_cn: 'str',
    local_universe_size: 'num?',
    prescreen_universe_size: 'num?',
    requested_max_symbols: 'num|null',
    selected_symbols: 'num?',
    deep_research_symbols: 'num?',
    is_budget_sample: 'bool',
    deep_scored_all_symbols: 'bool?',
    availability_cutoff: 'str|null',
    history_coverage_start: 'str|null',
    legacy_result: 'bool?',
    rerun_selection_method: 'str',
    sample_refresh_rule: 'str',
  }) ?? undefined;
}

function normalizeWalkForward(source: unknown): FactorLabWalkForwardSummary | undefined {
  return parseFieldsOrNull<FactorLabWalkForwardSummary>(source, {
    enabled: 'bool',
    score_source: 'str',
    first_prediction_date: 'str',
    last_prediction_date: 'str',
    retrain_windows: 'num?',
    retrain_interval_dates: 'num?',
    coverage_ratio: 'num?',
    message: 'str',
  }) ?? undefined;
}

function normalizeSummary(source: Record<string, unknown>, fallback: FactorLabRunConfig): FactorLabSummary {
  const nested = isRecord(source.config) ? source.config : {};
  const splitCounts = isRecord(source.split_counts) ? source.split_counts : {};
  const trainRaw = source.train_samples ?? splitCounts.train;
  const totalSymbolsRaw = source.total_symbols ?? source.symbols;
  return {
    run_id: toStr(source.run_id),
    enable_hist_gradient_boosting: source.enable_hist_gradient_boosting === true,
    start_date: toStr(source.start_date ?? nested.start_date ?? source.date_start, fallback.start_date),
    end_date: toStr(source.end_date ?? nested.end_date ?? source.date_end, fallback.end_date),
    pool: toStr(source.pool ?? nested.pool, fallback.pool),
    label: toStr(source.label ?? nested.label, fallback.label),
    top_n: toNum(source.top_n ?? nested.top_n, fallback.top_n),
    max_symbols: source.max_symbols !== undefined || nested.max_symbols !== undefined
      ? toNum(source.max_symbols ?? nested.max_symbols, fallback.max_symbols)
      : fallback.max_symbols,
    total_symbols: totalSymbolsRaw !== undefined ? toNum(totalSymbolsRaw) : undefined,
    train_samples: trainRaw !== undefined ? toNum(trainRaw) : undefined,
    ...parseFields<Pick<FactorLabSummary, 'rows_raw' | 'rows_sample' | 'feature_count' | 'best_factor' | 'best_model_test_rank_ic' | 'best_model_test_top20_ret' | 'universe' | 'sample_source_note' | 'research_note' | 'run_difference_note' | 'run_difference_reasons' | 'score_source' | 'price_mode'>>(source, {
      rows_raw: 'num?',
      rows_sample: 'num?',
      feature_count: 'num?',
      best_factor: 'str?',
      best_model_test_rank_ic: 'num?',
      best_model_test_top20_ret: 'num?',
      universe: 'str',
      sample_source_note: 'str',
      research_note: 'str',
      price_mode: 'str',
      run_difference_note: 'str',
      run_difference_reasons: 'str[]',
      score_source: 'str?',
    }),
    inference_date: toStr(source.inference_date ?? source.generated_at),
    universe_selection: normalizeUniverseSelection(source.universe_selection),
    model_recipe: normalizeModelRecipe(source.model_recipe),
    walk_forward: normalizeWalkForward(source.walk_forward),
  };
}

function isMissingResultPayload(source: Record<string, unknown>): boolean {
  const summary = isRecord(source.summary) ? source.summary : null;
  return Boolean(summary && toStr(summary.status) === 'missing');
}

export function normalizeFactorLabResult(
  source: unknown,
  config: Partial<FactorLabRunConfig> = DEFAULT_FACTOR_LAB_RUN_CONFIG
): FactorLabResult | null {
  if (!isRecord(source) || isMissingResultPayload(source)) return null;
  const summarySource = isRecord(source.summary) ? source.summary : {};
  const fallbackConfig = { ...DEFAULT_FACTOR_LAB_RUN_CONFIG, ...config };
  return {
    summary: normalizeSummary(summarySource, fallbackConfig),
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
          factors: toStrArray(source.backtest_compare.factors),
          best_total_return_factor: toStr(source.backtest_compare.best_total_return_factor),
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
