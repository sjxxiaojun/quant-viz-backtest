import type { FactorLabFailureState, FactorLabMetricItem, FactorLabResult, FactorLabRunConfig, FactorLabRunReadiness, FactorLabSelfIteration, FactorLabStrategyLifecycle, FactorLabStrategyBacktest, FactorLabStressScenario, StrategyVersionIteration, StrategyVersionRecord } from '../../types';
import { factorLabPoolOptions } from '../../config/strategies';

export type StrategyDetailCard = {
  key: string;
  name: string;
  shortDesc: string;
  totalReturn?: number;
  winRate?: number;
  triggerText: string;
  lastTriggerDate: string;
  maxDrawdown?: number;
  annualReturn?: number;
  costDrag?: number;
  recentHits: string[];
  suitableFor: string[];
  backtestRange: string;
  runNote: string;
  focusPoints: string[];
};

export type UserVerdict = {
  level: 'strong' | 'watch' | 'weak';
  title: string;
  score: number;
  summary: string;
  reasons: string[];
  risks: string[];
  nextSteps: string[];
  leadingStrategy?: StrategyDetailCard;
};

export type ReliabilityStatus = 'good' | 'warn' | 'bad' | 'neutral';

export type ReliabilityCheck = {
  label: string;
  value: string;
  detail: string;
  status: ReliabilityStatus;
};

export type PlainFeatureRow = {
  feature: string;
  name: string;
  explanation: string;
  importance: number;
  directionText: string;
  source?: string;
  rankIc?: number;
};

export type StressCard = {
  scenario: FactorLabStressScenario;
  medianReturn?: number;
  downsideReturn?: number;
  upsideReturn?: number;
  positiveChance?: number;
  p95Drawdown?: number;
  survivalRate?: number;
};

export const STRATEGY_COPY: Record<string, { name: string; shortDesc: string; suitableFor: string }> = {
  ml_factor_ranker: {
    name: '排序策略',
    shortDesc: '把候选股票按综合得分排队，优先拿最强的一组。',
    suitableFor: '适合想先追求收益弹性、能接受一定波动的人。',
  },
  ml_factor_filter: {
    name: '筛选策略',
    shortDesc: '先排除质量不稳的标的，再从剩余股票里挑更稳的一组。',
    suitableFor: '适合更在意回撤控制、希望组合更平滑的人。',
  },
};

export function formatValue(
  value: number | string | null | undefined,
  format: FactorLabMetricItem['format'] = 'number'
): string {
  if (value === null || value === undefined) return '--';
  if (typeof value === 'string') return value;

  if (format === 'percent') return `${(value * 100).toFixed(2)}%`;
  if (format === 'integer') return Math.round(value).toString();
  if (format === 'ratio') return value.toFixed(Math.abs(value) < 1 ? 3 : 2);
  return value.toFixed(2);
}

export function formatPercent(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return '--';
  return `${(value * 100).toFixed(2)}%`;
}

export function formatAbsPercent(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return '--';
  return `${(Math.abs(value) * 100).toFixed(2)}%`;
}

export function formatCompactNumber(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return '--';
  return new Intl.NumberFormat('zh-CN', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatStrategyLabel(factor: string | undefined): string {
  if (!factor) return '--';
  return STRATEGY_COPY[factor]?.name ?? factor;
}

export function formatScoreSource(source: string | undefined): string {
  const map: Record<string, string> = {
    walk_forward_composite_score: '滚动样本外综合分',
    walk_forward_score: '滚动样本外模型分',
    composite_score: '综合因子分',
    ml_score: '机器学习分',
    baseline_score: '基线模型分',
    score: '模型分数',
  };
  return source ? (map[source] ?? source) : '后端未返回';
}

export function formatModelBlend(result: FactorLabResult | null): string {
  const recipe = result?.summary.model_recipe ?? result?.research_iteration?.model_recipe;
  if (!recipe) return '融合比例后端未返回';
  return `线性 ${formatPercent(recipe.baseline_weight)} / 非线性 ${formatPercent(recipe.nonlinear_weight)}`;
}

export function formatOosState(value: boolean | undefined): string {
  if (value === true) return '是';
  if (value === false) return '否';
  return '未返回';
}

export function signalState(value: number | undefined): { label: string; active: boolean } {
  if (value === 1) return { label: '触发', active: true };
  if (value === 0 || value === undefined) return { label: '观察', active: false };
  return { label: '未知', active: false };
}

export function getFailureMessage(lastFailure: FactorLabFailureState | null | undefined): string {
  if (!lastFailure) return '';
  return lastFailure.detail || '';
}

export function getFailureCode(lastFailure: FactorLabFailureState | null | undefined): string {
  if (!lastFailure?.error_code) return '';
  return lastFailure.error_code;
}

export function getFailureConfig(lastFailure: FactorLabFailureState | null | undefined): Partial<FactorLabRunConfig> | null {
  if (!lastFailure) return null;
  return lastFailure.config ?? null;
}

export function formatConfigSummary(config: Partial<FactorLabRunConfig> | null | undefined): string {
  if (!config) return '--';
  const poolLabel = config.pool
    ? (factorLabPoolOptions.find((option) => option.value === config.pool)?.label ?? config.pool)
    : null;
  const parts = [
    config.start_date ? `开始 ${config.start_date}` : null,
    config.end_date ? `结束 ${config.end_date}` : null,
    poolLabel ? `股票池 ${poolLabel}` : null,
    config.top_n ? `Top ${config.top_n}` : null,
    config.max_symbols ? `样本上限 ${config.max_symbols} 只` : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join('，') : '--';
}

export function explainFocusPoint(point: string): string {
  const raw = point.trim();
  const key = raw.toLowerCase();
  const mapped: Record<string, string> = {
    turnover: '更看重换手节奏是否稳定，避免组合频繁大换仓。',
    turnover_stability: '更看重换手节奏是否稳定，避免组合频繁大换仓。',
    drawdown: '重点盯回撤控制，防止收益不错但过程过于难熬。',
    max_drawdown: '重点盯回撤控制，防止收益不错但过程过于难熬。',
    cost: '重点看交易成本是否侵蚀收益。',
    cost_drag: '重点看交易成本是否侵蚀收益。',
    coverage: '重点看有效样本覆盖是否足够，避免结果只靠少量股票。',
    win_rate: '重点看胜率是否稳定，不只看少数大赚样本。',
    quality: '重点看信号质量是否稳定，避免一段时间失真。',
    regime: '重点看不同市场环境下表现是否分化明显。',
    liquidity: '重点看流动性约束，避免选到难成交的股票。',
  };
  return mapped[key] || raw;
}

export function getReadinessMessages(readiness: FactorLabRunReadiness | null, checkingReadiness: boolean): string[] {
  if (checkingReadiness) {
    return ['正在检查本地数据完整性与可运行性。'];
  }
  if (!readiness) {
    return ['暂未拿到本地数据检查结果，运行前会先做检查。'];
  }
  if (readiness.warning_message) {
    return [readiness.warning_message];
  }
  if (readiness.needs_backfill) {
    return ['本地数据仍有缺口，运行时会优先补齐缺失部分。'];
  }
  if (readiness.cache_window_start && readiness.cache_window_end) {
    return [`本地缓存公共覆盖区间为 ${readiness.cache_window_start} 至 ${readiness.cache_window_end}，可以直接运行。`];
  }
  return ['运行前会先检查本地数据，确认是否需要补数。'];
}

export function buildStrategyCards(displayedResult: FactorLabResult | null): StrategyDetailCard[] {
  const strategyBacktests = (displayedResult?.strategy_backtests ?? {}) as Record<string, FactorLabStrategyBacktest>;
  const range =
    displayedResult?.summary.start_date && displayedResult?.summary.end_date
      ? `${displayedResult.summary.start_date} ~ ${displayedResult.summary.end_date}`
      : '--';
  const sharedRunNote = displayedResult?.summary.research_note || '--';

  return ['ml_factor_ranker', 'ml_factor_filter'].map((key) => {
    const detail = strategyBacktests[key] ?? {};
    const withCost = detail.with_cost ?? {};
    const summary = withCost.summary ?? {};
    const userView = detail.user_view;
    const triggerText = userView
      ? `${userView.trigger_days} 个交易日 / ${userView.total_trades} 笔交易`
      : summary.total_trades !== undefined
        ? `累计触发 ${summary.total_trades} 笔交易`
        : '--';
    const lastTriggerDate = userView?.last_signal_date || '--';
    const recentHits = userView?.recent_signal_symbols ?? [];
    const focusPoints = (userView?.focus_points ?? []).map(explainFocusPoint);

    return {
      key,
      name: userView?.name_cn || STRATEGY_COPY[key].name,
      shortDesc: userView?.description_cn || STRATEGY_COPY[key].shortDesc,
      totalReturn: userView?.total_return ?? withCost.total_return,
      winRate: userView?.win_rate ?? summary.win_rate,
      triggerText,
      lastTriggerDate,
      maxDrawdown: userView?.max_drawdown ?? summary.max_drawdown,
      annualReturn: userView?.annual_return ?? summary.annual_return,
      costDrag: userView?.cost_drag?.total_return_diff ?? detail.cost_drag?.total_return_diff,
      recentHits,
      suitableFor: userView?.suitable_for ?? [STRATEGY_COPY[key].suitableFor],
      backtestRange: range,
      runNote: sharedRunNote,
      focusPoints,
    };
  });
}

export function clampScore(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value)));
}

export function pickLeadingStrategy(cards: StrategyDetailCard[], preferredKey?: string): StrategyDetailCard | undefined {
  const preferred = preferredKey ? cards.find((card) => card.key === preferredKey) : undefined;
  if (preferred) return preferred;
  return [...cards].sort((left, right) => (right.totalReturn ?? -Infinity) - (left.totalReturn ?? -Infinity))[0];
}

export function buildUserVerdict(
  result: FactorLabResult | null,
  cards: StrategyDetailCard[],
  currentReadiness: FactorLabRunReadiness | null
): UserVerdict | null {
  if (!result || cards.length === 0) return null;

  const leadingStrategy = pickLeadingStrategy(cards, result.backtest_compare?.best_total_return_factor);
  const totalReturn = leadingStrategy?.totalReturn ?? 0;
  const winRate = leadingStrategy?.winRate ?? 0;
  const drawdownAbs = Math.abs(leadingStrategy?.maxDrawdown ?? 0);
  const costDrag = leadingStrategy?.costDrag ?? 0;
  const coverage = result.summary.walk_forward?.coverage_ratio;
  const trainSamples = result.summary.train_samples ?? result.summary.rows_sample;
  const totalSymbols = result.summary.total_symbols;
  const readiness = result.run_readiness ?? currentReadiness;

  let score = 50;
  score += totalReturn >= 0.08 ? 18 : totalReturn > 0 ? 8 : totalReturn <= -0.03 ? -18 : -8;
  score += drawdownAbs <= 0.1 ? 12 : drawdownAbs <= 0.18 ? 4 : -12;
  score += winRate >= 0.55 ? 8 : winRate >= 0.5 ? 3 : -6;
  score += coverage === undefined ? 0 : coverage >= 0.85 ? 10 : coverage >= 0.65 ? 3 : -8;
  score += trainSamples !== undefined && totalSymbols !== undefined && trainSamples >= 30000 && totalSymbols >= 100 ? 8 : 0;
  score += costDrag > 0.025 ? -7 : costDrag > 0.012 ? -3 : 3;
  if (readiness?.needs_backfill || readiness?.warning_message) score -= 6;

  const normalizedScore = clampScore(score);
  const level: UserVerdict['level'] =
    totalReturn <= 0 || normalizedScore < 55 ? 'weak' : normalizedScore >= 72 && drawdownAbs <= 0.15 ? 'strong' : 'watch';
  const title =
    level === 'strong'
      ? '可以进入小仓观察'
      : level === 'watch'
        ? '有观察价值，但先别放大仓位'
        : '暂不建议直接使用';

  const reasons = [
    `含成本回测领先的是${leadingStrategy?.name ?? '当前策略'}，累计收益 ${formatPercent(totalReturn)}，年化 ${formatPercent(leadingStrategy?.annualReturn)}。`,
    `样本覆盖 ${formatCompactNumber(totalSymbols)} 只股票、${formatCompactNumber(trainSamples)} 条训练样本，不是只看少数个案。`,
    coverage !== undefined
      ? `滚动验证覆盖率 ${formatPercent(coverage)}，用于判断模型在后续时间段是否还能工作。`
      : '当前没有滚动验证覆盖率，结论需要再看专家模式里的时间稳定性。',
  ];

  const risks = [
    totalReturn <= 0 ? '含成本收益还没有转正，不能只看胜率。' : '',
    drawdownAbs >= 0.15 ? `过程中最大浮亏约 ${formatAbsPercent(leadingStrategy?.maxDrawdown)}，持有体验偏难受。` : '',
    costDrag >= 0.02 ? `交易成本吃掉约 ${formatPercent(costDrag)}，频繁换仓会明显影响结果。` : '',
    winRate < 0.5 ? `胜率 ${formatPercent(winRate)} 未过半，命中稳定性仍需复核。` : '',
    readiness?.needs_backfill ? '本地数据存在补数动作，建议补齐后再复跑。' : '',
  ].filter(Boolean);

  const nextSteps =
    level === 'weak'
      ? ['先把它当作观察信号，不要直接接入自动交易。', '优先看分层收益和特征解释，确认高分股票是否真的更好。', '用核心池和全市场各复跑一次，排除样本选择带来的误判。']
      : level === 'watch'
        ? ['可先放进实盘模拟的小仓观察组。', '连续复跑几次，确认最近信号和成本拖累没有恶化。', '重点跟踪最大回撤，一旦扩大就暂停。']
        : ['可以进入小仓实盘模拟验证。', '保留个股止损，必要时启用个股止盈，不要因为回测好就放松风控。', '每次数据更新后复查结论是否降级。'];

  return {
    level,
    title,
    score: normalizedScore,
    summary: `这不是在预测某只股票一定上涨，而是在检查一套“给股票打分再排序”的规则是否有用。本次结论：${title}。`,
    reasons,
    risks: risks.length > 0 ? risks : ['暂未看到特别突出的单项风险，但仍需要继续观察真实信号。'],
    nextSteps,
    leadingStrategy,
  };
}

export function buildReliabilityChecks(
  result: FactorLabResult | null,
  currentReadiness: FactorLabRunReadiness | null
): ReliabilityCheck[] {
  if (!result) return [];
  const readiness = result.run_readiness ?? currentReadiness;
  const coverage = result.summary.walk_forward?.coverage_ratio;
  const trainSamples = result.summary.train_samples ?? result.summary.rows_sample;
  const totalSymbols = result.summary.total_symbols;
  const sourceValues = Object.values(result.data_sources_used ?? {});
  const sourceCounts = sourceValues.reduce<Record<string, number>>((acc, source) => {
    acc[source] = (acc[source] ?? 0) + 1;
    return acc;
  }, {});
  const sourceSummary = Object.entries(sourceCounts)
    .map(([source, count]) => `${source} ${count}只`)
    .join(' / ');
  const bucketSpread =
    result.bucket_returns.length >= 2
      ? result.bucket_returns[result.bucket_returns.length - 1].return - result.bucket_returns[0].return
      : undefined;
  const leading = pickLeadingStrategy(buildStrategyCards(result), result.backtest_compare?.best_total_return_factor);
  const drawdownAbs = Math.abs(leading?.maxDrawdown ?? 0);
  const costDrag = leading?.costDrag;

  return [
    {
      label: '样本是否够多',
      value: `${formatCompactNumber(totalSymbols)} 只 / ${formatCompactNumber(trainSamples)} 条`,
      detail: '样本越多，越不容易被一两只股票的偶然表现带偏。',
      status: trainSamples !== undefined && trainSamples >= 30000 && (totalSymbols ?? 0) >= 100 ? 'good' : 'warn',
    },
    {
      label: '是否做过滚动验证',
      value: coverage !== undefined ? formatPercent(coverage) : '--',
      detail: '滚动验证是在后面的时间段继续打分，能减少“只会解释历史”的问题。',
      status: coverage === undefined ? 'neutral' : coverage >= 0.8 ? 'good' : coverage >= 0.6 ? 'warn' : 'bad',
    },
    {
      label: '高分组是否更强',
      value: bucketSpread !== undefined ? formatPercent(bucketSpread) : '--',
      detail: '如果高分组没有明显跑赢低分组，说明打分规则的区分度还不够。',
      status: bucketSpread === undefined ? 'neutral' : bucketSpread > 0.01 ? 'good' : bucketSpread > 0 ? 'warn' : 'bad',
    },
    {
      label: '回撤是否可承受',
      value: leading ? formatAbsPercent(leading.maxDrawdown) : '--',
      detail: '最大回撤表示过程中最难受的浮亏幅度，比单看收益更接近真实体验。',
      status: drawdownAbs <= 0.1 ? 'good' : drawdownAbs <= 0.18 ? 'warn' : 'bad',
    },
    {
      label: '交易成本是否敏感',
      value: costDrag !== undefined ? formatPercent(costDrag) : '--',
      detail: '成本越高，越说明策略依赖频繁交易，真实执行时要更谨慎。',
      status: costDrag === undefined ? 'neutral' : costDrag <= 0.012 ? 'good' : costDrag <= 0.025 ? 'warn' : 'bad',
    },
    {
      label: '数据来源是否清楚',
      value: sourceSummary || (readiness?.cache_window_start && readiness.cache_window_end ? '本地缓存' : '--'),
      detail: readiness?.needs_backfill
        ? '这次运行需要补齐数据，补齐前结论要降一档看。'
        : '展示数据来源可以避免把模拟或缺失数据当成真实结果。',
      status: readiness?.needs_backfill || readiness?.warning_message ? 'warn' : sourceSummary ? 'good' : 'neutral',
    },
  ];
}

export function formatFactorPlainName(feature: string): string {
  const normalized = feature.toLowerCase();
  const exact: Record<string, string> = {
    open_gap: '开盘跳空',
    intraday_ret: '日内涨跌',
    ma_gap_20d: '20日均线距离',
    drawdown_20d: '20日回撤',
    amplitude: '振幅',
    turnover_rate: '换手率',
    turnover_z20: '换手异常度',
    amount_ratio_20d: '成交额变化',
    relative_strength_20d: '相对强弱',
    market_breadth_20d: '市场广度',
    market_ret_1d: '大盘当日表现',
    value_pe: '市盈率估值',
    value_pb: '市净率估值',
    value_ps: '市销率估值',
    value_pcf: '现金流估值',
  };
  if (exact[normalized]) return exact[normalized];
  if (/^mom_\d+d/.test(normalized)) return `${normalized.match(/\d+/)?.[0] ?? ''}日价格动量`;
  if (/^reversal_\d+d/.test(normalized)) return `${normalized.match(/\d+/)?.[0] ?? ''}日反转`;
  if (/^volatility_\d+d/.test(normalized)) return `${normalized.match(/\d+/)?.[0] ?? ''}日波动率`;
  if (/^volume_ratio_\d+d/.test(normalized)) return `${normalized.match(/\d+/)?.[0] ?? ''}日成交量变化`;
  if (normalized.endsWith('_rank')) return `${formatFactorPlainName(normalized.replace(/_rank$/, ''))}排名`;
  return feature.replace(/_/g, ' ');
}

export function explainFeature(feature: string): string {
  const normalized = feature.toLowerCase();
  if (normalized.includes('mom') || normalized.includes('relative_strength')) return '看股票最近是不是比其他股票更强。';
  if (normalized.includes('reversal')) return '看短期下跌后是否有反弹特征。';
  if (normalized.includes('volatility') || normalized.includes('amplitude')) return '看价格波动是否过大或过小。';
  if (normalized.includes('turnover') || normalized.includes('volume') || normalized.includes('amount')) return '看成交是否活跃，避免信号只停留在纸面上。';
  if (normalized.includes('value') || normalized.includes('pe') || normalized.includes('pb')) return '看价格相对基本面是否便宜或昂贵。';
  if (normalized.includes('gap') || normalized.includes('intraday')) return '看当天开盘和盘中价格行为是否透露短期情绪。';
  if (normalized.includes('market')) return '看整体市场环境是否支持这个信号。';
  return '模型认为这个指标对股票排序有解释力。';
}

export function buildPlainFeatureRows(result: FactorLabResult | null): PlainFeatureRow[] {
  if (!result) return [];
  if (result.factor_weights?.length) {
    return [...result.factor_weights]
      .sort((left, right) => right.weight - left.weight)
      .slice(0, 6)
      .map((item) => ({
        feature: item.feature,
        name: item.name_cn || formatFactorPlainName(item.feature),
        explanation: item.explanation || explainFeature(item.feature),
        importance: item.weight,
        directionText: item.direction_text || (item.direction === 'short' ? '数值偏低时更有利' : '数值偏高时更有利'),
        source: item.source,
        rankIc: item.rank_ic,
      }));
  }
  return [...result.feature_importance]
    .sort((left, right) => right.importance - left.importance)
    .slice(0, 5)
    .map((item) => ({
      feature: item.feature,
      name: formatFactorPlainName(item.feature),
      explanation: explainFeature(item.feature),
      importance: item.importance,
      directionText: item.direction === 'negative' ? '数值偏低时更有利' : '数值偏高时更有利',
      source: '模型特征重要性',
      rankIc: undefined,
    }));
}

export function getReliabilityTone(status: ReliabilityStatus): string {
  const tones: Record<ReliabilityStatus, string> = {
    good: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100',
    warn: 'border-amber-500/20 bg-amber-500/10 text-amber-100',
    bad: 'border-rose-500/20 bg-rose-500/10 text-rose-100',
    neutral: 'border-slate-700/40 bg-slate-950/20 text-slate-200',
  };
  return tones[status];
}

export function getVerdictTone(level: UserVerdict['level']): string {
  const tones: Record<UserVerdict['level'], string> = {
    strong: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100',
    watch: 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100',
    weak: 'border-amber-500/20 bg-amber-500/10 text-amber-100',
  };
  return tones[level];
}

export function getCandidateStatusLabel(status: string | undefined): string {
  const labels: Record<string, string> = {
    production: '当前生产规则',
    draft: '待验证候选',
    research_pass: '研究层通过',
    shadow: '影子观察',
    approved: '已审批',
    active: '已纳入',
    retired: '已回滚',
    rejected: '已拒绝',
    ready_to_promote: '可提升候选',
    research_only: '研究观察',
    no_promotion: '暂不晋级',
    promoted: '本轮入模',
    watch: '观察候选',
    skipped: '样本不足',
    tested_this_run: '本轮已测',
    included_this_run: '本轮入模',
  };
  return labels[status ?? ''] ?? (status || '--');
}

export function getPromotionTone(status: string | undefined): string {
  if (status === 'active' || status === 'approved') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100';
  if (status === 'shadow') return 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100';
  if (status === 'research_pass') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100';
  if (status === 'no_promotion') return 'border-amber-500/20 bg-amber-500/10 text-amber-100';
  if (status === 'retired' || status === 'rejected') return 'border-slate-700/40 bg-slate-950/20 text-slate-300';
  return 'border-slate-700/40 bg-slate-950/20 text-slate-200';
}

export function getScenarioTone(scenario: string): string {
  if (scenario === 'bull') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100';
  if (scenario === 'bear') return 'border-rose-500/20 bg-rose-500/10 text-rose-100';
  return 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100';
}

export function getScenarioPlainText(scenario: string): string {
  if (scenario === 'bull') return '假设市场整体偏强，重点看策略能否跟上机会。';
  if (scenario === 'bear') return '假设市场整体走弱，重点看回撤和生存率。';
  return '假设市场来回震荡，重点看是否被成本和换手磨损。';
}

export function buildStressCards(result: FactorLabResult | null, leadingFactor?: string): StressCard[] {
  const stressTest = result?.stress_test;
  if (!stressTest?.scenarios?.length) return [];
  const preferredFactor = leadingFactor || result?.backtest_compare?.best_total_return_factor || 'ml_factor_ranker';
  return stressTest.scenarios.map((scenario) => {
    const stats = scenario.factors[preferredFactor] ?? scenario.factors.ml_factor_ranker ?? Object.values(scenario.factors)[0] ?? {};
    return {
      scenario,
      medianReturn: stats.median_total_return,
      downsideReturn: stats.p05_total_return,
      upsideReturn: stats.p95_total_return,
      positiveChance: stats.prob_positive,
      p95Drawdown: stats.p95_max_drawdown_abs,
      survivalRate: stats.survival_rate,
    };
  });
}

export function getSelfIterationSummary(iteration: FactorLabSelfIteration | null | undefined): string {
  if (!iteration) return '还没有生成自我复盘结果。';
  const decision = iteration.promotion_decision?.decision || '当前规则继续保留。';
  const evidence = iteration.evidence?.score !== undefined ? `证据完整度 ${Math.round(iteration.evidence.score)}/100。` : '';
  return `${decision}${evidence ? ` ${evidence}` : ''}`;
}

export function formatVersionShort(versionId: string | undefined | null): string {
  if (!versionId) return '--';
  if (versionId.length <= 28) return versionId;
  return `${versionId.slice(0, 18)}…${versionId.slice(-8)}`;
}

export function getLifecycleTitle(lifecycle: FactorLabStrategyLifecycle | null | undefined): string {
  const status = lifecycle?.status;
  if (!status) return '策略版本状态待同步';
  if (status === 'active') return '已有 Factor Lab 版本纳入原策略';
  if (status === 'approved') return '候选版本已审批，等待切换';
  if (status === 'shadow') return '候选版本正在影子观察';
  if (status === 'research_pass') return '研究层通过，建议进入影子观察';
  if (status === 'ready_to_promote') return '本轮实验可提升为候选版本';
  return '当前仍是研究结果，未影响原策略';
}

export function getVersionActionLabel(version: StrategyVersionRecord): string {
  if (version.status === 'research_pass') return '启动影子观察';
  if (version.status === 'shadow') return '申请审批';
  if (version.status === 'approved') return '切换活动版本';
  if (version.status === 'active') return '当前已纳入';
  return '等待验证';
}

export function getLifecycleStatusLabel(lifecycle: FactorLabStrategyLifecycle | null | undefined): string {
  if (!lifecycle?.status) return '待同步';
  return getCandidateStatusLabel(lifecycle.status);
}

export function getGateRows(version: StrategyVersionRecord | null): { label: string; passed: boolean | undefined; value: string }[] {
  if (!version) return [];
  return [
    { label: '样本外 RankIC', passed: version.gates.oos_rank_ic_positive, value: formatValue(version.metrics.test_rank_ic, 'ratio') },
    { label: '含成本收益', passed: version.gates.with_cost_return_positive, value: formatPercent(version.metrics.with_cost_total_return) },
    { label: '最大回撤', passed: version.gates.max_drawdown_ok, value: formatAbsPercent(version.metrics.max_drawdown_abs) },
    { label: '成本拖累', passed: version.gates.cost_drag_ok, value: formatPercent(version.metrics.cost_drag) },
    { label: '压力测评', passed: version.gates.stress_test_passed, value: version.metrics.stress_gate_passed ? '通过' : '未通过' },
    { label: '影子观察', passed: version.gates.shadow_min_observation_passed, value: `${version.shadow?.observation_days ?? version.gates.shadow_observation_days ?? 0} 天` },
  ];
}

export function getIterationStatusLabel(iteration: StrategyVersionIteration | null | undefined): string {
  if (!iteration) return '未生成';
  if (iteration.status === 'planned') return '已生成计划';
  if (iteration.status === 'running') return '执行中';
  if (iteration.status === 'completed') return '已完成';
  return iteration.status || '待处理';
}

export function getIterationActionText(action: StrategyVersionIteration['actions'][number]): string {
  return action.label || action.type || '继续验证';
}

