export interface Trade {
  date: string;
  stock_code: string;
  stock_name: string;
  side: string;
  price: number;
  qty: number;
  requested_qty?: number;
  fill_status?: 'filled' | 'partial' | string;
}

/**
 * Portfolio history data
 * total_value and cash are in currency units (same as initial_capital)
 * drawdown is a negative ratio (e.g., -0.2 = 20% drawdown)
 * returns is a ratio (e.g., 0.1 = 10% return)
 */
export interface HistoryData {
  date: string;
  total_value: number;  // total portfolio value in currency units
  cash: number;         // cash portion in currency units
  drawdown?: number;    // drawdown ratio (negative, e.g., -0.2 = 20%)
  returns?: number;     // return ratio (e.g., 0.1 = 10% return)
  daily_trades?: Trade[];
}

/**
 * Benchmark history data
 * value is normalized ratio relative to initial price (1.0 = initial value)
 */
export interface BenchmarkHistoryData {
  date: string;
  value: number;  // normalized ratio (1.0 = initial investment value)
}

export interface BacktestResult {
  total_return: number;
  history: HistoryData[];
  benchmark_history?: BenchmarkHistoryData[];
  trades: Trade[];
  final_positions?: {
    stock_code: string;
    stock_name: string;
    quantity: number;
    avg_price: number;
    market_value: number;
    weight: number;
  }[];
  summary: {
    initial_capital: number;
    final_value: number;
    max_drawdown: number;
    sharpe_ratio: number;
    annual_return?: number;
    calmar_ratio?: number;
    win_rate?: number;
    profit_loss_ratio?: number;
    total_trades?: number;
    execution_stats?: Record<string, number>;
    execution_model?: {
      name?: string;
      enforce_tradability?: boolean;
      enforce_t1?: boolean;
      max_volume_participation?: number | null;
    };
  };
  metadata?: {
    latest_regime: string;
    regime_val: number;
  };
  data_sources_used?: Record<string, string>;
  resolved_pool?: {
    requested_pool: string;
    strategy_pool: string;
    asset_class: 'a_share' | 'etf';
    effective_pool: string;
    symbols_before_budget?: number;
    requested_max_symbols?: number | null;
    symbols_count?: number;
    budget_truncated?: boolean;
    selection_method?: string;
    method_cn?: string;
    local_universe_size?: number;
    prescreen_universe_size?: number;
    is_budget_sample?: boolean;
    deep_scored_all_symbols?: boolean;
    availability_cutoff?: string | null;
    history_coverage_start?: string | null;
    sample_source_note?: string;
  };
}

export interface BacktestConfig {
  start_date: string;
  end_date: string;
  initial_capital: number;
  factor: string;
  commission_rate: number;
  slippage_rate: number;
  pool: string;
  stocks?: string[];
  max_symbols?: number;
  max_positions: number;
  weight_mode: string;
  max_hold_days?: number;
  stop_loss: number;
  take_profit?: number;
}

export type FactorLabPool = 'core' | 'blackhorse' | 'all';

export interface FactorLabRunConfig {
  start_date: string;
  end_date: string;
  pool: FactorLabPool;
  label: string;
  top_n: number;
  max_symbols?: number;
}

export interface FactorLabFactorRankingItem {
  factor: string;
  score: number;
  ic?: number;
  rank_ic?: number;
  coverage?: number;
  stability?: number;
  direction?: string;
}

export interface FactorLabFeatureImportanceItem {
  feature: string;
  importance: number;
  group?: string;
  direction?: string;
}

export interface FactorLabFactorWeightItem {
  feature: string;
  name_cn?: string;
  group?: string;
  weight: number;
  importance?: number;
  direction?: string;
  direction_text?: string;
  explanation?: string;
  rank_ic?: number;
  recent_rank_ic?: number;
  source?: string;
}

export interface FactorLabMetricItem {
  key: string;
  label: string;
  value: number | string | null;
  format?: 'percent' | 'number' | 'ratio' | 'integer' | 'text';
  note?: string;
}

export interface FactorLabBucketReturnItem {
  bucket: string;
  return: number;
  excess_return?: number;
  win_rate?: number;
  samples?: number;
}

export interface FactorLabWalkForwardSummary {
  enabled: boolean;
  score_source?: string;
  first_prediction_date?: string;
  last_prediction_date?: string;
  retrain_windows?: number;
  retrain_interval_dates?: number;
  coverage_ratio?: number;
  message?: string;
}

export interface FactorLabModelRecipe {
  baseline_model?: string;
  nonlinear_model?: string;
  baseline_weight?: number;
  nonlinear_weight?: number;
  selection_metric?: string;
  selection_split?: string;
  valid_rank_ic?: number;
  valid_top20_ret?: number;
  reason?: string;
}

export interface FactorLabResearchIteration {
  mode?: string;
  actions?: string[];
  tested_candidate_factors?: number;
  promoted_candidate_factors?: number;
  promotion_cutoff?: number | null;
  candidates?: {
    factor?: string;
    name_cn?: string;
    status?: string;
    formula?: string;
    dependencies?: string[];
    score?: number;
    rank_ic?: number;
    recent_rank_ic?: number;
    test_rank_ic?: number;
    reason?: string;
  }[];
  model_recipe?: FactorLabModelRecipe;
  external_research_status?: string;
}

export interface FactorLabExternalIdea {
  idea_id?: string;
  name_cn?: string;
  plain_text?: string;
  status?: string;
  source_type?: string;
  mapped_factor?: string;
}

export interface FactorLabSummary {
  run_id?: string;
  start_date: string;
  end_date: string;
  pool: string;
  label: string;
  top_n: number;
  max_symbols?: number;
  total_symbols?: number;
  train_samples?: number;
  rows_raw?: number;
  rows_sample?: number;
  feature_count?: number;
  best_factor?: string;
  best_model_test_rank_ic?: number;
  best_model_test_top20_ret?: number;
  inference_date?: string;
  universe?: string;
  sample_source_note?: string;
  universe_selection?: {
    requested_pool?: string;
    selection_method?: string;
    method_cn?: string;
    local_universe_size?: number;
    prescreen_universe_size?: number;
    requested_max_symbols?: number | null;
    selected_symbols?: number;
    deep_research_symbols?: number;
    is_budget_sample?: boolean;
    deep_scored_all_symbols?: boolean;
    availability_cutoff?: string | null;
    history_coverage_start?: string | null;
    legacy_result?: boolean;
    rerun_selection_method?: string;
    sample_refresh_rule?: string;
  };
  research_note?: string;
  run_difference_note?: string;
  run_difference_reasons?: string[];
  score_source?: string;
  model_recipe?: FactorLabModelRecipe;
  walk_forward?: FactorLabWalkForwardSummary;
}

export interface FactorLabRunReadiness {
  requested_start_date?: string;
  requested_end_date?: string;
  effective_warmup_start?: string | null;
  cache_window_start?: string | null;
  cache_window_end?: string | null;
  missing_start?: string | null;
  missing_end?: string | null;
  needs_backfill: boolean;
  warning_message?: string | null;
  checked_symbols?: string[];
}

export interface FactorLabStrategyUserView {
  name_cn: string;
  description_cn: string;
  focus_points: string[];
  suitable_for: string[];
  total_return: number;
  annual_return: number;
  max_drawdown: number;
  win_rate: number;
  trigger_days: number;
  total_trades: number;
  last_signal_date?: string | null;
  recent_signal_symbols: string[];
  cost_drag?: {
    total_return_diff: number;
    annual_return_diff: number;
    cost_pct_initial: number;
  };
}

export interface FactorLabScorePreviewItem {
  date?: string;
  stock_code: string;
  stock_name?: string;
  score?: number;
  daily_rank?: number;
  signal?: number;
  is_oos_score?: boolean;
  score_source?: string;
  close?: number;
}

export interface FactorLabSelfIteration {
  run_id?: string;
  generated_at?: string;
  mode?: string;
  production_candidate?: {
    candidate_id?: string;
    score_source?: string;
    leading_factor?: string;
  };
  evidence?: {
    score: number;
    note?: string;
    metrics?: Record<string, number>;
  };
  candidate_pipeline?: {
    generated: number;
    research_pass: number;
    shadow: number;
    production_promoted: number;
  };
  candidates?: {
    candidate_id: string;
    name_cn: string;
    status: string;
    parent_id?: string | null;
    formula?: string;
    feature_dependencies?: string[];
    complexity_score?: number;
    rationale?: string;
  }[];
  stress_gate?: {
    available: boolean;
    passed: boolean;
    score?: number;
    failures?: string[];
    message?: string;
  };
  promotion_decision?: {
    status: string;
    decision: string;
    failures?: string[];
    next_action?: string;
  };
}

export interface FactorLabStressPathPoint {
  date: string;
  total_value: number;
  drawdown?: number;
}

export interface FactorLabStressScenario {
  scenario: 'bull' | 'bear' | 'sideways' | string;
  name_cn: string;
  assumptions?: {
    annual_drift?: number;
    annual_vol?: number;
    market_beta_bias?: number;
    mean_reversion?: number;
  };
  factors: Record<string, {
    median_total_return?: number;
    p05_total_return?: number;
    p95_total_return?: number;
    prob_positive?: number;
    median_max_drawdown?: number;
    p95_max_drawdown_abs?: number;
    median_sharpe?: number;
    median_final_value?: number;
    survival_rate?: number;
    median_total_trades?: number;
  }>;
  sample_paths?: {
    path_id: number;
    factor: string;
    history: FactorLabStressPathPoint[];
  }[];
}

export interface FactorLabStressTest {
  run_id?: string;
  generated_at?: string;
  config?: {
    pool?: string;
    max_symbols?: number;
    top_n?: number;
    horizon_days?: number;
    paths_per_scenario?: number;
    seed?: number;
    anchor_date?: string;
    symbols?: number;
  };
  scenarios: FactorLabStressScenario[];
  disclaimer?: string;
}

export interface FactorLabArtifactStatus {
  ready: boolean;
  status: string;
  message: string;
  run_id?: string;
  config_hash?: string;
  generated_at?: string;
  oos_start_date?: string;
  oos_end_date?: string;
  score_rows?: number;
  oos_score_rows?: number;
  model_available?: boolean;
}

export type StrategyVersionStatus =
  | 'draft'
  | 'research_pass'
  | 'shadow'
  | 'approved'
  | 'active'
  | 'retired'
  | 'rejected';

export interface StrategyVersionGates {
  oos_rank_ic_positive?: boolean;
  with_cost_return_positive?: boolean;
  max_drawdown_ok?: boolean;
  cost_drag_ok?: boolean;
  stress_test_passed?: boolean;
  shadow_min_observation_passed?: boolean;
  shadow_observation_days?: number;
  research_gate_passed?: boolean;
  approval_gate_passed?: boolean;
  failures?: string[];
  research_failures?: string[];
}

export interface StrategyVersionShadowLedger {
  version_id: string;
  strategy_id: string;
  shadow_strategy_id: string;
  started_at: string;
  status: string;
  observation_days: number;
  latest_observation_date?: string | null;
  baseline_strategy_id?: string | null;
  note?: string | null;
  metrics?: Record<string, unknown>;
}

export interface StrategyVersionIteration {
  iteration_id: string;
  parent_version_id: string;
  strategy_id: string;
  source_run_id: string;
  config_hash?: string;
  artifact_ref: string;
  artifact_hash?: string;
  mode: string;
  status: string;
  created_at: string;
  created_by?: string | null;
  objective: {
    summary?: string;
    primary_blockers?: string[];
    research_failures?: string[];
    target_metrics?: Record<string, unknown>;
    [key: string]: unknown;
  };
  next_run_config: {
    mode?: string;
    parent_version_id?: string;
    strategy_id?: string;
    source_run_id?: string;
    candidate_factor?: string;
    config_hash?: string;
    artifact_ref?: string;
    locked_artifact_hash?: string;
    constraints?: string[];
    suggested_actions?: Record<string, unknown>[];
    [key: string]: unknown;
  };
  actions: {
    type?: string;
    label?: string;
    rationale?: string;
    blocking?: boolean;
    [key: string]: unknown;
  }[];
  result_version_id?: string | null;
  note?: string | null;
}

export interface StrategyVersionRecord {
  version_id: string;
  strategy_id: string;
  parent_version_id?: string | null;
  source_run_id: string;
  config_hash: string;
  artifact_ref: string;
  status: StrategyVersionStatus | string;
  created_at: string;
  approved_at?: string | null;
  approved_by?: string | null;
  approval_note?: string | null;
  active?: boolean;
  metrics: {
    candidate_factor?: string;
    artifact_hash?: string;
    score_source?: string;
    test_rank_ic?: number;
    with_cost_total_return?: number;
    annual_return?: number;
    max_drawdown_abs?: number;
    cost_drag?: number;
    walk_forward_coverage?: number;
    stress_gate_available?: boolean;
    stress_gate_passed?: boolean;
    tested_candidate_factors?: number;
    promoted_candidate_factors?: number;
    parent_strategy_name?: string;
    [key: string]: unknown;
  };
  gates: StrategyVersionGates;
  shadow?: StrategyVersionShadowLedger;
  latest_iteration?: StrategyVersionIteration | null;
}

export interface FactorLabStrategyLifecycle {
  status: string;
  parent_strategy_id: string;
  parent_strategy_name?: string;
  active_version_id?: string | null;
  current_run_id?: string;
  current_run_versions: StrategyVersionRecord[];
  recent_versions: StrategyVersionRecord[];
  latest_iteration?: StrategyVersionIteration | null;
  next_action?: string;
  decision?: {
    status?: string;
    decision?: string;
    failures?: string[];
    next_action?: string;
  };
}

export interface FactorLabResult {
  summary: FactorLabSummary;
  factor_ranking: FactorLabFactorRankingItem[];
  feature_importance: FactorLabFeatureImportanceItem[];
  factor_weights?: FactorLabFactorWeightItem[];
  research_iteration?: FactorLabResearchIteration | null;
  external_factor_ideas?: FactorLabExternalIdea[];
  model_metrics: FactorLabMetricItem[];
  bucket_returns: FactorLabBucketReturnItem[];
  stability: FactorLabMetricItem[];
  backtest: BacktestResult | null;
  run_readiness?: FactorLabRunReadiness | null;
  strategy_backtests?: Record<string, FactorLabStrategyBacktest>;
  backtest_compare?: {
    factors: string[];
    best_total_return_factor?: string;
  };
  scores_preview?: FactorLabScorePreviewItem[];
  data_sources_used?: Record<string, string>;
  self_iteration?: FactorLabSelfIteration | null;
  stress_test?: FactorLabStressTest | null;
  artifact_status?: FactorLabArtifactStatus | null;
  strategy_lifecycle?: FactorLabStrategyLifecycle | null;
}

export type FactorLabFailureAction = 'loadLatest' | 'checkReadiness' | 'runResearch' | 'runBacktest' | 'runStressTest' | 'versionAction';

export interface FactorLabFailureState {
  action: FactorLabFailureAction;
  detail: string;
  error_code?: string | null;
  config?: FactorLabRunConfig;
  run_readiness?: FactorLabRunReadiness | null;
}

export interface FactorLabHookState {
  result: FactorLabResult | null;
  latestRealResult: FactorLabResult | null;
  readiness: FactorLabRunReadiness | null;
  checkingReadiness: boolean;
  loading: boolean;
  loadingAction: 'load' | 'run' | 'backtest' | 'stress' | null;
  error: string | null;
  notice: string | null;
  lastFailure: FactorLabFailureState | null;
  versionActionLoading?: string | null;
}

export interface FactorLabStrategyBacktest {
  factor: string;
  with_cost: {
    total_return: number;
    summary: BacktestResult['summary'];
    resolved_pool?: BacktestResult['resolved_pool'];
  };
  without_cost: {
    total_return: number;
    summary: BacktestResult['summary'];
    resolved_pool?: BacktestResult['resolved_pool'];
  };
  cost_drag: {
    total_return_diff: number;
    annual_return_diff: number;
    cost_pct_initial: number;
  };
  user_view?: FactorLabStrategyUserView;
}
