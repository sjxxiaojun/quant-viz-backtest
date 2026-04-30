import React, { useEffect, useMemo, useState } from 'react';
import { EChart } from './EChart';
import {
  Activity,
  AlertTriangle,
  BarChart3,
  BrainCircuit,
  Calendar,
  ChevronDown,
  ChevronUp,
  Database,
  Loader2,
  Play,
  ShieldCheck,
  Target,
  TrendingUp,
} from 'lucide-react';
import { cn, escapeHtml } from '../utils';
import { colorMap, factorLabPoolOptions, factorLabStrategyMeta } from '../config/strategies';
import { useFactorLab } from '../hooks/useFactorLab';
import type {
  FactorLabFailureState,
  FactorLabMetricItem,
  FactorLabResult,
  FactorLabRunConfig,
  FactorLabRunReadiness,
  FactorLabSelfIteration,
  FactorLabStrategyLifecycle,
  FactorLabStrategyBacktest,
  FactorLabStressScenario,
  StrategyVersionIteration,
  StrategyVersionRecord,
} from '../types';

const DEFAULT_START_DATE = '2022-01-01';
const DEFAULT_END_DATE = new Date().toISOString().slice(0, 10);
const TOP_N_OPTIONS = [3, 5, 10, 20] as const;
const SAMPLE_SIZE_OPTIONS = [180, 300, 500] as const;
const DEFAULT_EXPANDED: Record<string, boolean> = {
  ml_factor_ranker: true,
  ml_factor_filter: false,
};

type StrategyDetailCard = {
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

type UserVerdict = {
  level: 'strong' | 'watch' | 'weak';
  title: string;
  score: number;
  summary: string;
  reasons: string[];
  risks: string[];
  nextSteps: string[];
  leadingStrategy?: StrategyDetailCard;
};

type ReliabilityStatus = 'good' | 'warn' | 'bad' | 'neutral';

type ReliabilityCheck = {
  label: string;
  value: string;
  detail: string;
  status: ReliabilityStatus;
};

type PlainFeatureRow = {
  feature: string;
  name: string;
  explanation: string;
  importance: number;
  directionText: string;
  source?: string;
  rankIc?: number;
};

type StressCard = {
  scenario: FactorLabStressScenario;
  medianReturn?: number;
  downsideReturn?: number;
  upsideReturn?: number;
  positiveChance?: number;
  p95Drawdown?: number;
  survivalRate?: number;
};

const STRATEGY_COPY: Record<string, { name: string; shortDesc: string; suitableFor: string }> = {
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

function formatValue(
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

function formatPercent(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return '--';
  return `${(value * 100).toFixed(2)}%`;
}

function formatAbsPercent(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return '--';
  return `${(Math.abs(value) * 100).toFixed(2)}%`;
}

function formatCompactNumber(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return '--';
  return new Intl.NumberFormat('zh-CN', {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(value);
}

function formatStrategyLabel(factor: string | undefined): string {
  if (!factor) return '--';
  return STRATEGY_COPY[factor]?.name ?? factor;
}

function formatScoreSource(source: string | undefined): string {
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

function formatModelBlend(result: FactorLabResult | null): string {
  const recipe = result?.summary.model_recipe ?? result?.research_iteration?.model_recipe;
  if (!recipe) return '融合比例后端未返回';
  return `线性 ${formatPercent(recipe.baseline_weight)} / 非线性 ${formatPercent(recipe.nonlinear_weight)}`;
}

function formatOosState(value: boolean | undefined): string {
  if (value === true) return '是';
  if (value === false) return '否';
  return '未返回';
}

function signalState(value: number | undefined): { label: string; active: boolean } {
  if (value === 1) return { label: '触发', active: true };
  if (value === 0 || value === undefined) return { label: '观察', active: false };
  return { label: '未知', active: false };
}

function getFailureMessage(lastFailure: FactorLabFailureState | null | undefined): string {
  if (!lastFailure) return '';
  return lastFailure.detail || '';
}

function getFailureCode(lastFailure: FactorLabFailureState | null | undefined): string {
  if (!lastFailure?.error_code) return '';
  return lastFailure.error_code;
}

function getFailureConfig(lastFailure: FactorLabFailureState | null | undefined): Partial<FactorLabRunConfig> | null {
  if (!lastFailure) return null;
  return lastFailure.config ?? null;
}

function formatConfigSummary(config: Partial<FactorLabRunConfig> | null | undefined): string {
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

function explainFocusPoint(point: string): string {
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

function getReadinessMessages(readiness: FactorLabRunReadiness | null, checkingReadiness: boolean): string[] {
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

function buildStrategyCards(displayedResult: FactorLabResult | null): StrategyDetailCard[] {
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

function clampScore(value: number): number {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function pickLeadingStrategy(cards: StrategyDetailCard[], preferredKey?: string): StrategyDetailCard | undefined {
  const preferred = preferredKey ? cards.find((card) => card.key === preferredKey) : undefined;
  if (preferred) return preferred;
  return [...cards].sort((left, right) => (right.totalReturn ?? -Infinity) - (left.totalReturn ?? -Infinity))[0];
}

function buildUserVerdict(
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

function buildReliabilityChecks(
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

function formatFactorPlainName(feature: string): string {
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

function explainFeature(feature: string): string {
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

function buildPlainFeatureRows(result: FactorLabResult | null): PlainFeatureRow[] {
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

function getReliabilityTone(status: ReliabilityStatus): string {
  const tones: Record<ReliabilityStatus, string> = {
    good: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100',
    warn: 'border-amber-500/20 bg-amber-500/10 text-amber-100',
    bad: 'border-rose-500/20 bg-rose-500/10 text-rose-100',
    neutral: 'border-slate-700/40 bg-slate-950/20 text-slate-200',
  };
  return tones[status];
}

function getVerdictTone(level: UserVerdict['level']): string {
  const tones: Record<UserVerdict['level'], string> = {
    strong: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100',
    watch: 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100',
    weak: 'border-amber-500/20 bg-amber-500/10 text-amber-100',
  };
  return tones[level];
}

function getCandidateStatusLabel(status: string | undefined): string {
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

function getPromotionTone(status: string | undefined): string {
  if (status === 'active' || status === 'approved') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100';
  if (status === 'shadow') return 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100';
  if (status === 'research_pass') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100';
  if (status === 'no_promotion') return 'border-amber-500/20 bg-amber-500/10 text-amber-100';
  if (status === 'retired' || status === 'rejected') return 'border-slate-700/40 bg-slate-950/20 text-slate-300';
  return 'border-slate-700/40 bg-slate-950/20 text-slate-200';
}

function getScenarioTone(scenario: string): string {
  if (scenario === 'bull') return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100';
  if (scenario === 'bear') return 'border-rose-500/20 bg-rose-500/10 text-rose-100';
  return 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100';
}

function getScenarioPlainText(scenario: string): string {
  if (scenario === 'bull') return '假设市场整体偏强，重点看策略能否跟上机会。';
  if (scenario === 'bear') return '假设市场整体走弱，重点看回撤和生存率。';
  return '假设市场来回震荡，重点看是否被成本和换手磨损。';
}

function buildStressCards(result: FactorLabResult | null, leadingFactor?: string): StressCard[] {
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

function getSelfIterationSummary(iteration: FactorLabSelfIteration | null | undefined): string {
  if (!iteration) return '还没有生成自我复盘结果。';
  const decision = iteration.promotion_decision?.decision || '当前规则继续保留。';
  const evidence = iteration.evidence?.score !== undefined ? `证据完整度 ${Math.round(iteration.evidence.score)}/100。` : '';
  return `${decision}${evidence ? ` ${evidence}` : ''}`;
}

function formatVersionShort(versionId: string | undefined | null): string {
  if (!versionId) return '--';
  if (versionId.length <= 28) return versionId;
  return `${versionId.slice(0, 18)}…${versionId.slice(-8)}`;
}

function getLifecycleTitle(lifecycle: FactorLabStrategyLifecycle | null | undefined): string {
  const status = lifecycle?.status;
  if (!status) return '策略版本状态待同步';
  if (status === 'active') return '已有 Factor Lab 版本纳入原策略';
  if (status === 'approved') return '候选版本已审批，等待切换';
  if (status === 'shadow') return '候选版本正在影子观察';
  if (status === 'research_pass') return '研究层通过，建议进入影子观察';
  if (status === 'ready_to_promote') return '本轮实验可提升为候选版本';
  return '当前仍是研究结果，未影响原策略';
}

function getVersionActionLabel(version: StrategyVersionRecord): string {
  if (version.status === 'research_pass') return '启动影子观察';
  if (version.status === 'shadow') return '申请审批';
  if (version.status === 'approved') return '切换活动版本';
  if (version.status === 'active') return '当前已纳入';
  return '等待验证';
}

function getLifecycleStatusLabel(lifecycle: FactorLabStrategyLifecycle | null | undefined): string {
  if (!lifecycle?.status) return '待同步';
  return getCandidateStatusLabel(lifecycle.status);
}

function getGateRows(version: StrategyVersionRecord | null): { label: string; passed: boolean | undefined; value: string }[] {
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

function getIterationStatusLabel(iteration: StrategyVersionIteration | null | undefined): string {
  if (!iteration) return '未生成';
  if (iteration.status === 'planned') return '已生成计划';
  if (iteration.status === 'running') return '执行中';
  if (iteration.status === 'completed') return '已完成';
  return iteration.status || '待处理';
}

function getIterationActionText(action: StrategyVersionIteration['actions'][number]): string {
  return action.label || action.type || '继续验证';
}

export function FactorLab() {
  const [config, setConfig] = useState<FactorLabRunConfig>({
    start_date: DEFAULT_START_DATE,
    end_date: DEFAULT_END_DATE,
    pool: 'core',
    label: 'next_5d_ret',
    top_n: 5,
    max_symbols: 300,
  });
  const factorLabState = useFactorLab(config);

  const {
    result,
    latestRealResult,
    loading,
    loadingAction,
    error,
    notice,
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
    readiness,
    checkingReadiness,
    lastFailure,
    versionActionLoading,
  } = factorLabState;
  const [expertMode, setExpertMode] = useState(false);
  const [expandedCards, setExpandedCards] = useState<Record<string, boolean>>(DEFAULT_EXPANDED);

  const displayedResult = result ?? latestRealResult;
  const displayedRunConfig = useMemo<FactorLabRunConfig>(() => {
    const summary = displayedResult?.summary;
    if (!summary) return config;
    const pool = factorLabPoolOptions.some((option) => option.value === summary.pool)
      ? summary.pool as FactorLabRunConfig['pool']
      : config.pool;
    return {
      ...config,
      start_date: summary.start_date || config.start_date,
      end_date: summary.end_date || config.end_date,
      pool,
      label: summary.label || config.label,
      top_n: summary.top_n || config.top_n,
      max_symbols: summary.max_symbols ?? config.max_symbols,
    };
  }, [config, displayedResult?.summary]);
  useEffect(() => {
    const summary = displayedResult?.summary;
    if (!summary) return;
    const timer = window.setTimeout(() => {
      setConfig((prev) => {
        const nextPool = factorLabPoolOptions.some((option) => option.value === summary.pool)
          ? summary.pool as FactorLabRunConfig['pool']
          : prev.pool;
        const nextConfig: FactorLabRunConfig = {
          ...prev,
          start_date: summary.start_date || prev.start_date,
          end_date: summary.end_date || prev.end_date,
          pool: nextPool,
          top_n: summary.top_n || prev.top_n,
          max_symbols: summary.max_symbols ?? prev.max_symbols,
          label: summary.label || prev.label,
        };
        if (
          nextConfig.start_date === prev.start_date &&
          nextConfig.end_date === prev.end_date &&
          nextConfig.pool === prev.pool &&
          nextConfig.top_n === prev.top_n &&
          nextConfig.max_symbols === prev.max_symbols &&
          nextConfig.label === prev.label
        ) {
          return prev;
        }
        return nextConfig;
      });
    }, 0);
    return () => window.clearTimeout(timer);
  }, [displayedResult?.summary]);
  const failureMessage = getFailureMessage(lastFailure) || error || '';
  const failureCode = getFailureCode(lastFailure);
  const failedConfig = getFailureConfig(lastFailure);
  const hasHistoricalResult = Boolean(displayedResult);
  const showFailureBanner = Boolean(failureMessage);
  const readinessMessages = getReadinessMessages(readiness, checkingReadiness);
  const needsBackfill = Boolean(readiness?.needs_backfill);
  const dateRangeInvalid = Boolean(config.start_date && config.end_date && config.start_date > config.end_date);
  const runningStatus = checkingReadiness
    ? '检查本地数据'
    : loadingAction === 'run'
      ? '完整研究运行中'
      : loadingAction === 'stress'
        ? '三行情景测评中'
        : null;

  const featureImportanceOption = useMemo(() => {
    if (!displayedResult) return {};
    const sorted = [...displayedResult.feature_importance]
      .sort((left, right) => right.importance - left.importance)
      .slice(0, 8)
      .reverse();

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
	        formatter: (params: Array<{ name?: string; value: number }>) => {
	          const point = params[0];
	          return `${escapeHtml(point.name)}<br/>重要性: ${(point.value * 100).toFixed(1)}%`;
	        },
      },
      grid: { left: '4%', right: '6%', bottom: '5%', top: '5%', containLabel: true },
      xAxis: {
        type: 'value',
        axisLine: { show: false },
        axisLabel: { color: '#94a3b8', formatter: (value: number) => `${(value * 100).toFixed(0)}%` },
        splitLine: { lineStyle: { color: '#0d2244', type: 'dashed' } },
      },
      yAxis: {
        type: 'category',
        data: sorted.map((item) => item.feature),
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#cbd5e1', fontSize: 11 },
      },
      series: [
        {
          type: 'bar',
          data: sorted.map((item) => ({
            value: item.importance,
            itemStyle: {
              color: item.direction === 'negative' ? '#22c55e' : '#38bdf8',
              borderRadius: [10, 10, 10, 10],
            },
          })),
          barWidth: 12,
        },
      ],
    };
  }, [displayedResult]);

  const bucketReturnOption = useMemo(() => {
    if (!displayedResult) return {};
    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
	        axisPointer: { type: 'shadow' },
	        formatter: (params: Array<{ marker?: string; seriesName?: string; value: number; name?: string }>) => {
	          const rows = params
	            .map((point) => `${point.marker || ''} ${escapeHtml(point.seriesName)}: ${(point.value * 100).toFixed(2)}%`)
	            .join('<br/>');
	          return `${escapeHtml(params[0]?.name || '')}<br/>${rows}`;
	        },
      },
      legend: { textStyle: { color: '#94a3b8' }, top: 0 },
      grid: { left: '4%', right: '4%', bottom: '5%', top: '15%', containLabel: true },
      xAxis: {
        type: 'category',
        data: displayedResult.bucket_returns.map((item) => item.bucket),
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8' },
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisLabel: { color: '#94a3b8', formatter: (value: number) => `${(value * 100).toFixed(0)}%` },
        splitLine: { lineStyle: { color: '#0d2244', type: 'dashed' } },
      },
      series: [
        {
          name: '分桶收益',
          type: 'bar',
          data: displayedResult.bucket_returns.map((item) => item.return),
          itemStyle: { color: '#38bdf8', borderRadius: [10, 10, 0, 0] },
          barWidth: 18,
        },
        {
          name: '超额收益',
          type: 'bar',
          data: displayedResult.bucket_returns.map((item) => item.excess_return ?? 0),
          itemStyle: { color: '#818cf8', borderRadius: [10, 10, 0, 0] },
          barWidth: 18,
        },
      ],
    };
  }, [displayedResult]);

  const selfIteration = displayedResult?.self_iteration ?? null;
  const lifecycle = displayedResult?.strategy_lifecycle ?? null;
  const currentRunId = lifecycle?.current_run_id || displayedResult?.summary.run_id || '';
  const currentRunVersions = lifecycle?.current_run_versions ?? [];
  const recentVersions = lifecycle?.recent_versions ?? [];
  const primaryVersion = currentRunVersions[0] ?? null;
  const activeVersion = recentVersions.find((version) => version.active || version.status === 'active') ?? null;
  const latestIteration = lifecycle?.latest_iteration ?? primaryVersion?.latest_iteration ?? null;
  const gateRows = useMemo(() => getGateRows(primaryVersion), [primaryVersion]);
  const stressCards = useMemo(
    () => buildStressCards(displayedResult, displayedResult?.backtest_compare?.best_total_return_factor),
    [displayedResult]
  );
  const stressPathOption = useMemo(() => {
    const stressTest = displayedResult?.stress_test;
    if (!stressTest?.scenarios?.length) return {};
    const series = stressTest.scenarios.flatMap((scenario) =>
      (scenario.sample_paths ?? [])
        .filter((path) => path.factor === (displayedResult?.backtest_compare?.best_total_return_factor || 'ml_factor_ranker'))
        .slice(0, 1)
        .map((path) => ({
          name: scenario.name_cn,
          type: 'line',
          smooth: true,
          showSymbol: false,
          data: path.history.map((point) => [point.date, point.total_value]),
        }))
    );
    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        formatter: (params: Array<{ marker?: string; seriesName?: string; value?: [string, number] | number; name?: string }>) => {
          if (!params.length) return '';
          const firstValue = params[0]?.value;
          const label = params[0]?.name || (Array.isArray(firstValue) ? firstValue[0] : '');
          const rows = params
            .map((point) => {
              const rawValue = Array.isArray(point.value) ? point.value[1] : point.value;
              return `${point.marker || ''} ${escapeHtml(point.seriesName || '')}: ${Number(rawValue || 0).toLocaleString('zh-CN')}`;
            })
            .join('<br/>');
          return `${escapeHtml(label)}<br/>${rows}`;
        },
      },
      legend: { textStyle: { color: '#94a3b8' }, top: 0 },
      grid: { left: '4%', right: '4%', bottom: '8%', top: '15%', containLabel: true },
      xAxis: {
        type: 'time',
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8' },
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisLabel: { color: '#94a3b8' },
        splitLine: { lineStyle: { color: '#0d2244', type: 'dashed' } },
      },
      series,
    };
  }, [displayedResult]);

  const displayedMetrics = displayedResult?.model_metrics.slice(0, 6) ?? [];
  const walkForward = displayedResult?.summary.walk_forward;
  const backtest = displayedResult?.backtest;
  const leadingStrategy = displayedResult?.backtest_compare?.best_total_return_factor;
  const strategyCards = useMemo(() => buildStrategyCards(displayedResult), [displayedResult]);
  const userVerdict = useMemo(
    () => buildUserVerdict(displayedResult, strategyCards, readiness),
    [displayedResult, strategyCards, readiness]
  );
  const reliabilityChecks = useMemo(
    () => buildReliabilityChecks(displayedResult, readiness),
    [displayedResult, readiness]
  );
  const plainFeatures = useMemo(() => buildPlainFeatureRows(displayedResult), [displayedResult]);
  const artifactStatus = displayedResult?.artifact_status ?? null;
  const artifactStatusReady = Boolean(artifactStatus?.ready);
  const artifactStatusLabel = artifactStatus?.status || (displayedResult ? '待同步' : 'unknown');
  const artifactStatusMessage = artifactStatus?.message || (
    displayedResult
      ? '后端暂未返回 ML 策略产物状态；刷新报告后会重新读取 latest_manifest/latest_scores。'
      : '尚未读取到 Factor Lab scoring artifact 状态。'
  );
  const previewSignals = useMemo(() => {
    const preview = displayedResult?.scores_preview ?? [];
    return [...preview]
      .sort((left, right) => {
        const signalDiff = (right.signal === 1 ? 1 : 0) - (left.signal === 1 ? 1 : 0);
        if (signalDiff !== 0) return signalDiff;
        return (left.daily_rank ?? Number.MAX_SAFE_INTEGER) - (right.daily_rank ?? Number.MAX_SAFE_INTEGER);
      })
      .slice(0, 6);
  }, [displayedResult]);

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <section
        className="rounded-[2.5rem] p-8 backdrop-blur-xl shadow-2xl space-y-6"
        style={{ background: 'rgba(13, 27, 50, 0.55)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
      >
        <div className="flex flex-col xl:flex-row gap-8 xl:items-start xl:justify-between">
          <div className="max-w-3xl space-y-5">
            <div className="flex items-center gap-4">
              <div className={cn('p-4 rounded-3xl', colorMap[factorLabStrategyMeta.color]?.textBg, colorMap[factorLabStrategyMeta.color]?.text)}>
                <BrainCircuit className="w-8 h-8" />
              </div>
              <div>
                <h2 className="text-2xl font-black tracking-tight text-slate-100">
                  {expertMode ? 'Factor Lab / 因子实验室' : '策略体检报告'}
                </h2>
                <p className="text-sm text-slate-400 mt-1">
                  {expertMode
                    ? '保留完整研究拆解视角，适合继续看因子排行、滚动验证和详细回测。'
                    : '看这套 ML 选股策略最近是否值得观察、风险在哪里、信号来自哪些股票。'}
                </p>
              </div>
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                onClick={() => runResearch(config)}
                disabled={loading || dateRangeInvalid}
                className="bg-cyan-600 hover:bg-cyan-500 disabled:bg-slate-700 disabled:text-slate-500 text-white px-6 py-3 rounded-2xl font-bold transition-all flex items-center gap-2"
              >
                {loadingAction === 'run' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                开新实验
              </button>
              <button
                onClick={() => loadLatest()}
                disabled={loading}
                className="px-6 py-3 rounded-2xl font-bold transition-all flex items-center gap-2 border text-slate-300 hover:text-white disabled:opacity-40"
                style={{ borderColor: 'rgba(59, 130, 246, 0.18)', background: 'rgba(8, 18, 36, 0.6)' }}
              >
                {loadingAction === 'load' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Activity className="w-4 h-4" />}
                查看上次报告
              </button>
              <button
                onClick={() => runStressTest(displayedRunConfig)}
                disabled={loading || dateRangeInvalid}
                className="px-6 py-3 rounded-2xl font-bold transition-all flex items-center gap-2 border text-emerald-100 hover:text-white disabled:opacity-40"
                style={{ borderColor: 'rgba(16, 185, 129, 0.22)', background: 'rgba(16, 185, 129, 0.12)' }}
              >
                {loadingAction === 'stress' ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
                快速情景测评
              </button>
              <button
                onClick={() => setExpertMode((prev) => !prev)}
                className="px-6 py-3 rounded-2xl font-bold transition-all flex items-center gap-2 border text-cyan-200 hover:text-white"
                style={{ borderColor: 'rgba(34, 211, 238, 0.25)', background: 'rgba(34, 211, 238, 0.12)' }}
              >
                {expertMode ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                {expertMode ? '返回客户视图' : '查看研究细节'}
              </button>
            </div>

            <div className="rounded-3xl border border-amber-400/20 bg-amber-400/10 p-4 space-y-3">
              <div className="flex flex-wrap items-center gap-3">
                <div className="inline-flex items-center gap-2 text-sm font-semibold text-amber-100">
                  <ShieldCheck className="w-4 h-4" />
                  数据准备情况
                </div>
                {runningStatus && (
                  <span className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs font-semibold text-cyan-100">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    {runningStatus}
                  </span>
                )}
                {needsBackfill && (
                  <span className="inline-flex rounded-full border border-amber-300/20 bg-amber-300/10 px-3 py-1 text-xs font-semibold text-amber-100">
                    包含历史补数，可能较慢
                  </span>
                )}
              </div>
              <div className="space-y-2 text-sm text-amber-50/90">
                {readinessMessages.map((message) => (
                  <p key={message}>{message}</p>
                ))}
              </div>
            </div>
            <div
              className={cn(
                'rounded-3xl border p-4 space-y-2',
                artifactStatusReady
                  ? 'border-emerald-400/20 bg-emerald-400/10 text-emerald-50'
                  : 'border-amber-400/20 bg-amber-400/10 text-amber-50'
              )}
            >
              <div className="flex flex-wrap items-center gap-3">
                <div className="inline-flex items-center gap-2 text-sm font-semibold">
                  {artifactStatusReady ? <ShieldCheck className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
                  ML 策略产物
                </div>
                <span className="rounded-full border border-white/10 bg-white/10 px-3 py-1 text-xs font-semibold">
                  {artifactStatusLabel}
                </span>
              </div>
              <p className="text-sm opacity-90">
                {artifactStatusMessage}
              </p>
              {(artifactStatus?.oos_start_date || artifactStatus?.oos_end_date) && (
                <p className="text-xs opacity-75">
                  样本外覆盖：{artifactStatus?.oos_start_date || '--'} 至 {artifactStatus?.oos_end_date || '--'}；
                  OOS 分数 {formatCompactNumber(artifactStatus?.oos_score_rows)}
                </p>
              )}
            </div>
            {dateRangeInvalid && (
              <div className="rounded-2xl border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-100">
                开始日期不能晚于结束日期。
              </div>
            )}
            {notice && !showFailureBanner && (
              <div className="rounded-2xl border border-cyan-500/20 bg-cyan-500/10 p-4 text-sm text-cyan-100">
                {notice}
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 xl:max-w-3xl w-full">
            <div className="rounded-3xl p-5 space-y-4" style={{ background: 'rgba(8, 18, 36, 0.72)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.12)' }}>
              <div className="flex items-center gap-2 text-blue-300">
                <Calendar className="w-4 h-4" />
                <span className="text-[11px] font-bold tracking-[0.16em]">回看时间</span>
              </div>
              <div className="space-y-3">
                <div>
                  <label className="text-[10px] font-bold tracking-wider text-slate-400">开始日期</label>
                  <input
                    type="date"
                    value={config.start_date}
                    min={DEFAULT_START_DATE}
                    max={DEFAULT_END_DATE}
                    onChange={(event) => setConfig((prev) => ({ ...prev, start_date: event.target.value }))}
                    className="w-full mt-1 rounded-xl px-3 py-2.5 text-xs focus:ring-1 focus:ring-blue-500 outline-none text-slate-200 font-mono"
                    style={{ background: 'rgba(13, 27, 50, 0.72)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.12)' }}
                  />
                </div>
                <div>
                  <label className="text-[10px] font-bold tracking-wider text-slate-400">结束日期</label>
                  <input
                    type="date"
                    value={config.end_date}
                    min={DEFAULT_START_DATE}
                    max={DEFAULT_END_DATE}
                    onChange={(event) => setConfig((prev) => ({ ...prev, end_date: event.target.value }))}
                    className="w-full mt-1 rounded-xl px-3 py-2.5 text-xs focus:ring-1 focus:ring-blue-500 outline-none text-slate-200 font-mono"
                    style={{ background: 'rgba(13, 27, 50, 0.72)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.12)' }}
                  />
                </div>
                <p className="text-[11px] leading-relaxed text-slate-500">
                  时间拉得更长，能看到策略在不同市场阶段里的表现；运行前会自动检查是否需要补数。
                </p>
              </div>
            </div>

            <div className="rounded-3xl p-5 space-y-3" style={{ background: 'rgba(8, 18, 36, 0.72)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.12)' }}>
              <div className="flex items-center gap-2 text-cyan-300">
                <Database className="w-4 h-4" />
                <span className="text-[11px] font-bold tracking-[0.16em]">股票池范围</span>
              </div>
              <div className="space-y-2">
                {factorLabPoolOptions.map((option) => {
                  const accent = colorMap[option.accent];
                  const selected = config.pool === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setConfig((prev) => ({ ...prev, pool: option.value as FactorLabRunConfig['pool'] }))}
                      className={cn(
                        'w-full rounded-2xl px-4 py-3 text-left border transition-all',
                        selected ? `${accent?.textBg} ${accent?.text} ${accent?.border}` : 'border-slate-700/40 text-slate-400 hover:text-slate-200 hover:bg-white/5'
                      )}
                    >
                      <div className="text-xs font-bold">{option.label}</div>
                      <div className="text-[10px] mt-1 opacity-80">{option.description}</div>
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="rounded-3xl p-5 space-y-4" style={{ background: 'rgba(8, 18, 36, 0.72)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.12)' }}>
              <div className="flex items-center gap-2 text-violet-300">
                <BarChart3 className="w-4 h-4" />
                <span className="text-[11px] font-bold tracking-[0.16em]">持仓数量</span>
              </div>
              <div>
                <label className="text-[10px] font-bold tracking-wider text-slate-400">每次保留前几只股票</label>
                <div className="grid grid-cols-4 gap-2 mt-2">
                  {TOP_N_OPTIONS.map((option) => (
                    <button
                      key={option}
                      type="button"
                      onClick={() => setConfig((prev) => ({ ...prev, top_n: option }))}
                      className={cn(
                        'rounded-xl py-2 text-[10px] font-bold transition-all border',
                        config.top_n === option ? 'bg-cyan-500/20 text-cyan-200 border-cyan-500/40' : 'border-slate-700/40 text-slate-400 hover:text-slate-200 hover:bg-white/5'
                      )}
                    >
                      Top {option}
                    </button>
                  ))}
                </div>
                <p className="text-[11px] leading-relaxed text-slate-500 mt-3">
                  数量越少，组合更集中；数量越多，波动通常会更平滑。
                </p>
              </div>
              <div>
                <label className="text-[10px] font-bold tracking-wider text-slate-400">研究样本预算</label>
                <div className="grid grid-cols-3 gap-2 mt-2">
                  {SAMPLE_SIZE_OPTIONS.map((option) => (
                    <button
                      key={option}
                      type="button"
                      onClick={() => setConfig((prev) => ({ ...prev, max_symbols: option }))}
                      className={cn(
                        'rounded-xl py-2 text-[10px] font-bold transition-all border',
                        config.max_symbols === option ? 'bg-violet-500/20 text-violet-200 border-violet-500/40' : 'border-slate-700/40 text-slate-400 hover:text-slate-200 hover:bg-white/5'
                      )}
                    >
                      {option} 只
                    </button>
                  ))}
                </div>
                <p className="text-[11px] leading-relaxed text-slate-500 mt-3">
                  全市场会先从本地数据湖做轻量预筛，再把预算内样本送进深度因子实验。
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {showFailureBanner && hasHistoricalResult && (
        <section className="rounded-[2rem] border border-rose-500/20 bg-rose-500/10 p-6 text-sm text-rose-100 space-y-3">
          <div className="flex items-center gap-2 font-semibold">
            <AlertTriangle className="w-4 h-4" />
            本次体检失败，当前展示的是上次真实报告
          </div>
          {failureCode && <div>错误码：{failureCode}</div>}
          <div>失败原因：{failureMessage}</div>
          <div>本次尝试配置：{formatConfigSummary(failedConfig ?? config)}</div>
          <div>系统不会生成伪结果；修复失败原因后再开新实验。</div>
        </section>
      )}

      {!hasHistoricalResult && showFailureBanner && (
        <section className="rounded-[2.5rem] p-10 backdrop-blur-xl shadow-2xl text-center space-y-4" style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(239, 68, 68, 0.16)' }}>
          <AlertTriangle className="w-10 h-10 mx-auto text-rose-300" />
          <div className="text-xl font-bold text-slate-100">当前没有可展示的真实结果</div>
          {failureCode && <div className="text-sm text-rose-200">错误码：{failureCode}</div>}
          <div className="text-sm text-slate-300">失败原因：{failureMessage}</div>
          <div className="text-sm text-slate-400">本次尝试配置：{formatConfigSummary(failedConfig ?? config)}</div>
          <div className="text-sm text-slate-400">系统不会用模拟结果冒充真实报告。</div>
        </section>
      )}

      {!hasHistoricalResult && !showFailureBanner && !loading && (
        <section className="rounded-[2.5rem] p-10 backdrop-blur-xl shadow-2xl text-center space-y-4" style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}>
          <BrainCircuit className="w-10 h-10 mx-auto text-slate-400" />
          <div className="text-xl font-bold text-slate-100">当前还没有真实体检报告</div>
          <div className="text-sm text-slate-400">点击“开新实验”后，系统会检查数据、给股票打分、分组验证，再输出是否值得观察。</div>
        </section>
      )}

      {hasHistoricalResult && (
        <section
          className="rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl space-y-5"
          style={{ background: 'rgba(13, 27, 50, 0.5)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
        >
          <div className="flex flex-col xl:flex-row xl:items-start xl:justify-between gap-5">
            <div className="space-y-3">
              <div className="text-[11px] font-bold tracking-[0.18em] text-emerald-300">策略研发飞轮</div>
              <h3 className="text-2xl font-black text-slate-100">{getLifecycleTitle(lifecycle)}</h3>
              <p className="text-sm text-slate-300 leading-relaxed max-w-4xl">
                {lifecycle?.next_action || '后端策略版本状态尚未同步；Factor Lab 的研究结果不会自动覆盖原策略，刷新报告后会显示候选版本、影子观察和审批状态。'}
              </p>
              <div className="flex flex-wrap gap-2 text-xs">
                {['因子发现', '样本外验证', '候选版本', '影子观察', '审批纳入', '可回滚'].map((label, index) => (
                  <span
                    key={label}
                    className={cn(
                      'rounded-full border px-3 py-1 font-semibold',
                      index <= (lifecycle?.status === 'active' ? 5 : lifecycle?.status === 'approved' ? 4 : lifecycle?.status === 'shadow' ? 3 : lifecycle?.status === 'research_pass' ? 2 : 1)
                        ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100'
                        : 'border-slate-700/40 bg-slate-950/30 text-slate-400'
                    )}
                  >
                    {label}
                  </span>
                ))}
              </div>
            </div>

            <div className="flex flex-wrap gap-3 xl:justify-end">
              {lifecycle?.status === 'ready_to_promote' && currentRunId && (
                <button
                  type="button"
                  onClick={() => promoteCurrentRun(currentRunId)}
                  disabled={loading || Boolean(versionActionLoading)}
                  className="inline-flex items-center gap-2 rounded-2xl border border-emerald-500/25 bg-emerald-500/10 px-4 py-2.5 text-sm font-semibold text-emerald-100 transition-all hover:text-white disabled:opacity-40"
                >
                  {versionActionLoading?.startsWith('promote') ? <Loader2 className="w-4 h-4 animate-spin" /> : <Target className="w-4 h-4" />}
                  提升为候选版本
                </button>
              )}
              {primaryVersion && primaryVersion.status !== 'active' && (
                <button
                  type="button"
                  onClick={() => {
                    if (primaryVersion.status === 'research_pass') void startShadow(primaryVersion.version_id);
                    if (primaryVersion.status === 'shadow') void approveVersion(primaryVersion.version_id);
                    if (primaryVersion.status === 'approved') void activateVersion(primaryVersion.version_id, primaryVersion.strategy_id);
                  }}
                  disabled={loading || Boolean(versionActionLoading) || !['research_pass', 'shadow', 'approved'].includes(String(primaryVersion.status))}
                  className="inline-flex items-center gap-2 rounded-2xl border border-cyan-500/25 bg-cyan-500/10 px-4 py-2.5 text-sm font-semibold text-cyan-100 transition-all hover:text-white disabled:opacity-40"
                >
                  {versionActionLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                  {getVersionActionLabel(primaryVersion)}
                </button>
              )}
              {primaryVersion && !['retired', 'rejected'].includes(String(primaryVersion.status)) && (
                <button
                  type="button"
                  onClick={() => iterateVersion(primaryVersion.version_id)}
                  disabled={loading || Boolean(versionActionLoading)}
                  className="inline-flex items-center gap-2 rounded-2xl border border-violet-400/25 bg-violet-500/10 px-4 py-2.5 text-sm font-semibold text-violet-100 transition-all hover:text-white disabled:opacity-40"
                >
                  {versionActionLoading?.startsWith('iterate') ? <Loader2 className="w-4 h-4 animate-spin" /> : <BrainCircuit className="w-4 h-4" />}
                  基于候选继续迭代
                </button>
              )}
              {lifecycle?.active_version_id && (
                <button
                  type="button"
                  onClick={() => rollbackVersion(lifecycle.parent_strategy_id || 'ai_ml')}
                  disabled={loading || Boolean(versionActionLoading)}
                  className="inline-flex items-center gap-2 rounded-2xl border border-amber-500/25 bg-amber-500/10 px-4 py-2.5 text-sm font-semibold text-amber-100 transition-all hover:text-white disabled:opacity-40"
                >
                  {versionActionLoading?.startsWith('rollback') ? <Loader2 className="w-4 h-4 animate-spin" /> : <Activity className="w-4 h-4" />}
                  回滚到上一版本
                </button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div className={cn('rounded-2xl border p-4', getPromotionTone(lifecycle?.status))}>
              <div className="text-[10px] font-bold tracking-[0.18em] opacity-75">总决策</div>
              <div className="mt-2 text-lg font-black">{getLifecycleStatusLabel(lifecycle)}</div>
              <div className="mt-2 text-xs opacity-80">
                父策略：{lifecycle?.parent_strategy_name || lifecycle?.parent_strategy_id || 'ai_ml'}
              </div>
            </div>
            <div className="rounded-2xl border border-slate-700/40 bg-slate-950/20 p-4">
              <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">当前版本</div>
              <div className="mt-2 text-sm font-black text-slate-100 break-all">
                {primaryVersion?.version_id || lifecycle?.active_version_id
                  ? formatVersionShort(primaryVersion?.version_id || lifecycle?.active_version_id)
                  : '未生成候选版本'}
              </div>
              <div className="mt-2 text-xs text-slate-500">
                运行 ID：{formatVersionShort(currentRunId)}
              </div>
            </div>
            <div className="rounded-2xl border border-slate-700/40 bg-slate-950/20 p-4">
              <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">影子观察</div>
              <div className="mt-2 text-lg font-black text-slate-100">
                {formatValue(primaryVersion?.shadow?.observation_days ?? primaryVersion?.gates.shadow_observation_days ?? 0, 'integer')} 天
              </div>
              <div className="mt-2 text-xs text-slate-500">
                最近观察：{primaryVersion?.shadow?.latest_observation_date || '--'}
              </div>
            </div>
          </div>

          {(primaryVersion?.gates.failures ?? []).length > 0 && (
            <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 p-4 text-sm text-amber-50/90">
              <div className="font-semibold text-amber-100">未通过门禁</div>
              <div className="mt-2">{primaryVersion?.gates.failures?.join('；')}</div>
            </div>
          )}

          {latestIteration && (
            <div className="rounded-2xl border border-violet-400/20 bg-violet-500/10 p-4">
              <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-[10px] font-bold tracking-[0.18em] text-violet-200">定向迭代计划</div>
                  <div className="mt-2 text-base font-black text-slate-100">
                    {getIterationStatusLabel(latestIteration)} / {formatVersionShort(latestIteration.parent_version_id)}
                  </div>
                  <p className="mt-2 text-xs leading-relaxed text-violet-100/80">
                    {latestIteration.objective.summary || '围绕当前候选版本继续验证，不覆盖父策略，也不把 latest_* 当作生产真相源。'}
                  </p>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs lg:min-w-[20rem]">
                  <div className="rounded-xl border border-violet-400/15 bg-slate-950/25 p-3">
                    <div className="text-slate-500">模式</div>
                    <div className="mt-1 font-bold text-slate-100">候选定向打磨</div>
                  </div>
                  <div className="rounded-xl border border-violet-400/15 bg-slate-950/25 p-3">
                    <div className="text-slate-500">Artifact</div>
                    <div className="mt-1 break-all font-mono text-[11px] font-bold text-slate-100">
                      {formatVersionShort(latestIteration.artifact_hash || latestIteration.next_run_config.locked_artifact_hash)}
                    </div>
                  </div>
                </div>
              </div>
              <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-3">
                <div className="rounded-xl border border-violet-400/15 bg-slate-950/20 p-3">
                  <div className="text-[10px] font-bold tracking-[0.16em] text-slate-500">下一步动作</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {latestIteration.actions.slice(0, 4).map((action, index) => (
                      <span key={`${action.type || action.label || 'action'}-${index}`} className="rounded-full border border-violet-400/20 bg-violet-400/10 px-3 py-1 text-xs font-semibold text-violet-50">
                        {getIterationActionText(action)}
                      </span>
                    ))}
                  </div>
                </div>
                <div className="rounded-xl border border-violet-400/15 bg-slate-950/20 p-3">
                  <div className="text-[10px] font-bold tracking-[0.16em] text-slate-500">锁定约束</div>
                  <div className="mt-2 space-y-1 text-xs text-slate-300">
                    {(latestIteration.next_run_config.constraints ?? []).slice(0, 3).map((constraint) => (
                      <div key={constraint}>• {constraint}</div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
            <div className="xl:col-span-4 rounded-2xl border border-cyan-500/15 bg-cyan-500/5 p-4 space-y-3">
              <div>
                <div className="text-[10px] font-bold tracking-[0.18em] text-cyan-200">当前实验</div>
                <div className="mt-2 text-sm font-black text-slate-100">Run {formatVersionShort(currentRunId)}</div>
              </div>
              <p className="text-xs leading-relaxed text-cyan-100/80">
                “开新实验”会重新取数、重训和验证；“基于候选继续迭代”会锁定当前候选 artifact，按门禁阻塞项继续打磨。
              </p>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="rounded-xl border border-cyan-500/15 bg-slate-950/20 p-3">
                  <div className="text-slate-500">RankIC</div>
                  <div className="mt-1 font-bold text-slate-100">{formatValue(displayedResult?.summary.best_model_test_rank_ic, 'ratio')}</div>
                </div>
                <div className="rounded-xl border border-cyan-500/15 bg-slate-950/20 p-3">
                  <div className="text-slate-500">OOS 覆盖</div>
                  <div className="mt-1 font-bold text-slate-100">{formatPercent(displayedResult?.summary.walk_forward?.coverage_ratio)}</div>
                </div>
              </div>
            </div>

            <div className="xl:col-span-5 rounded-2xl border border-slate-700/40 bg-slate-950/20 p-4 space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">候选版本库</div>
                  <div className="mt-1 text-sm text-slate-300">已纳入候选的版本都在这里。</div>
                </div>
                <span className="rounded-full border border-slate-700/40 px-3 py-1 text-xs font-bold text-slate-300">
                  {recentVersions.length} 个
                </span>
              </div>
              {recentVersions.length > 0 ? (
                <div className="space-y-3">
                  {recentVersions.slice(0, 4).map((version) => (
                    <div key={version.version_id} className="rounded-xl border border-slate-700/40 bg-slate-900/40 p-3">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="truncate font-mono text-xs font-bold text-slate-100">{version.version_id}</div>
                          <div className="mt-1 text-[11px] text-slate-500">
                            来源 {formatVersionShort(version.source_run_id)} / {version.metrics.candidate_factor || 'ml_factor_ranker'}
                          </div>
                        </div>
                        <span className={cn('shrink-0 rounded-full border px-2.5 py-1 text-[10px] font-bold', getPromotionTone(version.status))}>
                          {getCandidateStatusLabel(version.status)}
                        </span>
                      </div>
                      <div className="mt-3 grid grid-cols-3 gap-2 text-[11px]">
                        <div>
                          <div className="text-slate-500">收益</div>
                          <div className="mt-1 font-semibold text-slate-200">{formatPercent(version.metrics.with_cost_total_return)}</div>
                        </div>
                        <div>
                          <div className="text-slate-500">回撤</div>
                          <div className="mt-1 font-semibold text-slate-200">{formatAbsPercent(version.metrics.max_drawdown_abs)}</div>
                        </div>
                        <div>
                          <div className="text-slate-500">Shadow</div>
                          <div className="mt-1 font-semibold text-slate-200">{version.shadow?.observation_days ?? version.gates.shadow_observation_days ?? 0} 天</div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-slate-700/60 p-4 text-sm leading-relaxed text-slate-400">
                  还没有候选版本。当前实验通过后，点击“提升为候选版本”，这里会出现可 shadow、审批、纳入和回滚的版本卡。
                </div>
              )}
            </div>

            <div className="xl:col-span-3 rounded-2xl border border-emerald-500/15 bg-emerald-500/5 p-4 space-y-3">
              <div>
                <div className="text-[10px] font-bold tracking-[0.18em] text-emerald-200">活动版本</div>
                <div className="mt-2 text-sm font-black text-slate-100">
                  {activeVersion ? formatVersionShort(activeVersion.version_id) : '基线 ai_ml'}
                </div>
              </div>
              <p className="text-xs leading-relaxed text-emerald-100/80">
                {activeVersion
                  ? '这个版本正在接管父策略；如果表现偏离预期，可以回滚。'
                  : '当前仍使用代码内置 ai_ml，Factor Lab 候选还没有真正接管原策略。'}
              </p>
              {gateRows.length > 0 && (
                <div className="space-y-2">
                  {gateRows.slice(0, 4).map((gate) => (
                    <div key={gate.label} className="flex items-center justify-between gap-2 text-[11px]">
                      <span className="text-slate-400">{gate.label}</span>
                      <span className={cn('font-bold', gate.passed ? 'text-emerald-200' : 'text-amber-200')}>{gate.value}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </section>
      )}

      {hasHistoricalResult && !expertMode && (
        <section className="space-y-6">
          <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
            <article
              className="xl:col-span-7 rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl space-y-5"
              style={{ background: 'rgba(13, 27, 50, 0.5)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
            >
              <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-5">
                <div className="space-y-3">
                  <div className="text-[11px] font-bold tracking-[0.18em] text-cyan-300">本次研究结论</div>
                  <h3 className="text-3xl font-black text-slate-100">
                    {userVerdict?.title ?? '等待真实研究结果'}
                  </h3>
                  <p className="text-sm text-slate-300 leading-relaxed max-w-3xl">
                    {userVerdict?.summary ?? '系统会先检查数据，再用历史行情验证这套选股打分规则是否真的有区分度。'}
                  </p>
                  {displayedResult?.summary.sample_source_note && (
                    <p className="text-xs text-slate-500 leading-relaxed max-w-3xl">
                      {displayedResult.summary.sample_source_note}
                    </p>
                  )}
                </div>
                {userVerdict && (
                  <div className={cn('rounded-3xl border px-5 py-4 min-w-[160px]', getVerdictTone(userVerdict.level))}>
                    <div className="text-[10px] font-bold tracking-[0.18em] opacity-80">可信度</div>
                    <div className="mt-2 text-3xl font-black">{userVerdict.score}</div>
                    <div className="text-xs opacity-80">满分 100</div>
                  </div>
                )}
              </div>

              {userVerdict && (
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                  <div className="rounded-2xl border border-slate-700/40 bg-slate-950/20 p-4 lg:col-span-2">
                    <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">为什么这么判断</div>
                    <div className="mt-3 space-y-2 text-sm leading-relaxed text-slate-200">
                      {userVerdict.reasons.map((reason) => (
                        <p key={reason}>{reason}</p>
                      ))}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 p-4">
                    <div className="text-[10px] font-bold tracking-[0.18em] text-amber-200">主要风险</div>
                    <div className="mt-3 space-y-2 text-sm leading-relaxed text-amber-50/90">
                      {userVerdict.risks.map((risk) => (
                        <p key={risk}>{risk}</p>
                      ))}
                    </div>
                  </div>
                </div>
              )}
              {(displayedResult?.summary.run_difference_note || (displayedResult?.summary.run_difference_reasons ?? []).length > 0) && (
                <div className="rounded-2xl border border-cyan-500/15 bg-cyan-500/5 p-4 text-sm leading-relaxed text-cyan-50/90">
                  <div className="font-semibold text-cyan-100">
                    {displayedResult?.summary.run_difference_note || '本轮结果已重新训练和重新调权。'}
                  </div>
                  {(displayedResult?.summary.run_difference_reasons ?? []).slice(0, 3).map((reason) => (
                    <p key={reason} className="mt-2 text-xs text-cyan-100/75">{reason}</p>
                  ))}
                </div>
              )}
            </article>

            <article
              className="xl:col-span-5 rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl space-y-5"
              style={{ background: 'rgba(13, 27, 50, 0.5)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
            >
              <div className="flex items-center gap-3">
                <div className="p-3 rounded-2xl bg-cyan-500/10 text-cyan-300">
                  <BrainCircuit className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="text-lg font-black text-slate-100">因子到底是什么意思</h3>
                  <p className="text-xs text-slate-500 mt-1">给非专业用户看的解释</p>
                </div>
              </div>
              <div className="space-y-3 text-sm leading-relaxed text-slate-300">
                <p>因子就是一条给股票打分的规则。比如“最近涨得强不强”“成交是否活跃”“波动是不是太大”“估值是否便宜”。</p>
                <p>因子实验室做的事不是直接喊买卖，而是检查：高分股票后面是否真的比低分股票表现更好。</p>
                <p>如果高分组跑不赢、成本吃掉收益、回撤太深，这个因子就算名字好听，也不该直接拿去交易。</p>
              </div>
            </article>
	          </div>

	          <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
	            <article
	              className="xl:col-span-5 rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl space-y-5"
	              style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
	            >
	              <div className="flex items-start justify-between gap-4">
	                <div>
	                  <h3 className="text-lg font-black text-slate-100">模型如何自我复盘</h3>
	                  <p className="text-sm text-slate-400 mt-1">系统不会自动迷信上次结果，只会把通过验证的新规则放进观察队列。</p>
	                </div>
	                <BrainCircuit className="w-6 h-6 text-cyan-300" />
	              </div>
	              <div className={cn('rounded-2xl border p-4 text-sm leading-relaxed', getPromotionTone(selfIteration?.promotion_decision?.status))}>
	                {getSelfIterationSummary(selfIteration)}
	              </div>
	              <div className="grid grid-cols-2 gap-4">
	                {[
	                  ['候选规则', formatValue(selfIteration?.candidate_pipeline?.generated ?? null, 'integer')],
	                  ['研究层通过', formatValue(selfIteration?.candidate_pipeline?.research_pass ?? null, 'integer')],
	                  ['候选因子测试', formatValue(displayedResult?.research_iteration?.tested_candidate_factors ?? null, 'integer')],
	                  ['本轮入模因子', formatValue(displayedResult?.research_iteration?.promoted_candidate_factors ?? null, 'integer')],
	                  ['影子观察', formatValue(selfIteration?.candidate_pipeline?.shadow ?? null, 'integer')],
	                  ['证据完整度', selfIteration?.evidence?.score !== undefined ? `${Math.round(selfIteration.evidence.score)}/100` : '--'],
	                ].map(([label, value]) => (
	                  <div key={label} className="rounded-2xl border border-slate-700/40 bg-slate-950/20 p-4">
	                    <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">{label}</div>
	                    <div className="mt-2 text-lg font-black text-slate-100">{value}</div>
	                  </div>
	                ))}
	              </div>
	              {(displayedResult?.research_iteration?.actions ?? []).length > 0 && (
	                <div className="rounded-2xl border border-cyan-500/15 bg-cyan-500/5 p-4 text-xs leading-relaxed text-cyan-100/80 space-y-2">
	                  {displayedResult?.research_iteration?.actions?.map((action) => (
	                    <p key={action}>{action}</p>
	                  ))}
	                </div>
	              )}
	              {displayedResult?.research_iteration?.external_research_status && (
	                <div className="rounded-2xl border border-violet-500/15 bg-violet-500/5 p-4 text-xs leading-relaxed text-violet-100/80">
	                  {displayedResult.research_iteration.external_research_status}
	                </div>
	              )}
	              {(displayedResult?.external_factor_ideas ?? []).length > 0 && (
	                <div className="grid grid-cols-1 gap-3">
	                  {displayedResult?.external_factor_ideas?.slice(0, 3).map((idea) => (
	                    <div key={idea.idea_id || idea.name_cn} className="rounded-2xl border border-slate-700/40 bg-slate-950/20 p-4">
	                      <div className="flex items-start justify-between gap-3">
	                        <div>
	                          <div className="text-sm font-bold text-slate-100">{idea.name_cn || idea.idea_id}</div>
	                          <div className="text-xs text-slate-500 mt-1">{idea.plain_text || idea.source_type}</div>
	                        </div>
	                        <span className="rounded-full border border-violet-500/20 bg-violet-500/10 px-2.5 py-1 text-[10px] font-bold text-violet-100">
	                          {getCandidateStatusLabel(idea.status)}
	                        </span>
	                      </div>
	                    </div>
	                  ))}
	                </div>
	              )}
	              <div className="space-y-3">
	                {(selfIteration?.candidates ?? []).slice(0, 3).map((candidate) => (
	                  <div key={candidate.candidate_id} className="rounded-2xl border border-slate-700/40 bg-slate-950/20 p-4">
	                    <div className="flex items-start justify-between gap-3">
	                      <div>
	                        <div className="text-sm font-bold text-slate-100">{candidate.name_cn}</div>
	                        <div className="text-xs text-slate-500 mt-1">{candidate.rationale || candidate.formula || '--'}</div>
	                      </div>
	                      <span className="rounded-full border border-cyan-500/20 bg-cyan-500/10 px-2.5 py-1 text-[10px] font-bold text-cyan-100">
	                        {getCandidateStatusLabel(candidate.status)}
	                      </span>
	                    </div>
	                  </div>
	                ))}
	              </div>
	            </article>

	            <article
	              className="xl:col-span-7 rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl space-y-5"
	              style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
	            >
	              <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-4">
	                <div>
	                  <h3 className="text-lg font-black text-slate-100">未来一年三行情景测评</h3>
	                  <p className="text-sm text-slate-400 mt-1">随机模拟牛市、熊市、震荡年，检查这套规则在好年景和坏年景里怎么受考验。</p>
	                </div>
	                <button
                  type="button"
                  onClick={() => runStressTest(displayedRunConfig)}
                  disabled={loading || dateRangeInvalid}
                  className="inline-flex items-center gap-2 rounded-2xl border border-emerald-500/20 bg-emerald-500/10 px-4 py-2.5 text-sm font-semibold text-emerald-100 transition-all hover:text-white disabled:opacity-40"
	                >
	                  {loadingAction === 'stress' ? <Loader2 className="w-4 h-4 animate-spin" /> : <ShieldCheck className="w-4 h-4" />}
	                  快速测评
	                </button>
	              </div>

	              {stressCards.length > 0 ? (
	                <>
	                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
	                    {stressCards.map((card) => (
	                      <div key={card.scenario.scenario} className={cn('rounded-2xl border p-4 space-y-3', getScenarioTone(card.scenario.scenario))}>
	                        <div>
	                          <div className="text-sm font-black">{card.scenario.name_cn}</div>
	                          <div className="text-xs opacity-80 mt-1 leading-relaxed">{getScenarioPlainText(card.scenario.scenario)}</div>
	                        </div>
	                        <div className="grid grid-cols-2 gap-3 text-xs">
	                          <div>
	                            <div className="opacity-70">中位收益</div>
	                            <div className="mt-1 text-lg font-black">{formatPercent(card.medianReturn)}</div>
	                          </div>
	                          <div>
	                            <div className="opacity-70">压力亏损</div>
	                            <div className="mt-1 text-lg font-black">{formatPercent(card.downsideReturn)}</div>
	                          </div>
	                          <div>
	                            <div className="opacity-70">盈利路径</div>
	                            <div className="mt-1 font-bold">{formatPercent(card.positiveChance)}</div>
	                          </div>
	                          <div>
	                            <div className="opacity-70">极端回撤</div>
	                            <div className="mt-1 font-bold">{formatAbsPercent(card.p95Drawdown)}</div>
	                          </div>
	                        </div>
	                      </div>
	                    ))}
	                  </div>
	                  <div className="h-[260px] rounded-2xl border border-slate-700/40 bg-slate-950/20 p-3">
	                    <EChart option={stressPathOption} style={{ height: '100%', width: '100%' }} />
	                  </div>
	                  <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 p-4 text-xs leading-relaxed text-amber-50/90">
	                    情景测评是压力测试，不是对未来行情或收益的承诺。它的价值是提前暴露回撤、成本和极端年份的生存问题。
	                  </div>
	                </>
	              ) : (
	                <div className="rounded-2xl border border-slate-700/40 bg-slate-950/20 p-5 text-sm text-slate-400 leading-relaxed">
	                  还没有三行情景测评结果。点击“运行测评”后，系统会用真实历史行情作为起点，生成未来一年牛市、熊市、震荡年随机路径。
	                </div>
	              )}
	            </article>
	          </div>

	          <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
	            <article
              className="xl:col-span-5 rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl space-y-5"
              style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
            >
              <div>
                <h3 className="text-lg font-black text-slate-100">这次体检怎么跑</h3>
                <p className="text-sm text-slate-400 mt-1">从股票池到结论的完整路径。</p>
              </div>
              <div className="space-y-3">
                {[
                  ['1', '选股票范围', displayedResult?.summary.universe || `${factorLabPoolOptions.find((option) => option.value === displayedResult?.summary.pool)?.label ?? displayedResult?.summary.pool ?? '--'}，共 ${formatCompactNumber(displayedResult?.summary.total_symbols)} 只。`],
                  ['2', '给每只股票打分', `使用 ${formatCompactNumber(displayedResult?.summary.feature_count)} 个因子，${formatModelBlend(displayedResult)}，分数来源 ${displayedResult?.summary.score_source ?? '--'}。`],
                  ['3', '分组验证', '把股票按分数分层，看高分组是否真的更强。'],
                  ['4', '策略回测', `每次保留 Top ${displayedResult?.summary.top_n ?? config.top_n}，同时扣除交易成本。`],
                  ['5', '给出行动建议', '先判断能不能观察，再提示风险和下一步。'],
                ].map(([step, title, detail]) => (
                  <div key={step} className="flex gap-4 rounded-2xl border border-slate-700/40 bg-slate-950/20 p-4">
                    <div className="w-8 h-8 rounded-full bg-cyan-500/10 text-cyan-200 flex items-center justify-center text-xs font-black shrink-0">
                      {step}
                    </div>
                    <div>
                      <div className="text-sm font-bold text-slate-100">{title}</div>
                      <div className="text-xs text-slate-400 mt-1 leading-relaxed">{detail}</div>
                    </div>
                  </div>
                ))}
              </div>
            </article>

            <article
              className="xl:col-span-7 rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl space-y-5"
              style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
            >
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h3 className="text-lg font-black text-slate-100">这次结果靠不靠谱</h3>
                  <p className="text-sm text-slate-400 mt-1">不用先懂 IC、RankIC，先看这些检查项。</p>
                </div>
                <ShieldCheck className="w-6 h-6 text-emerald-300" />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {reliabilityChecks.map((check) => (
                  <div key={check.label} className={cn('rounded-2xl border p-4', getReliabilityTone(check.status))}>
                    <div className="flex items-start justify-between gap-3">
                      <div className="text-sm font-bold">{check.label}</div>
                      <div className="text-sm font-black text-right">{check.value}</div>
                    </div>
                    <p className="mt-2 text-xs leading-relaxed opacity-80">{check.detail}</p>
                  </div>
                ))}
              </div>
            </article>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">
            <article
              className="xl:col-span-7 rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl space-y-5"
              style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
            >
              <div className="flex items-center justify-between gap-4">
                <div>
                  <h3 className="text-lg font-black text-slate-100">模型主要看了什么</h3>
                  <p className="text-sm text-slate-400 mt-1">当前因子配方和解释权重，每次运行都会随验证结果更新。</p>
                </div>
                <TrendingUp className="w-6 h-6 text-cyan-300" />
              </div>
              <div className="space-y-3">
                {plainFeatures.length > 0 ? (
                  plainFeatures.map((feature) => (
                    <div key={feature.feature} className="rounded-2xl border border-slate-700/40 bg-slate-950/20 p-4">
                      <div className="flex flex-col md:flex-row md:items-start md:justify-between gap-3">
                        <div>
                          <div className="text-sm font-bold text-slate-100">{feature.name}</div>
                          <div className="text-xs text-slate-500 mt-1 font-mono">{feature.feature}</div>
                        </div>
                        <div className="text-right">
                          <div className="text-sm font-black text-cyan-200">{formatPercent(feature.importance)}</div>
                          <div className="text-[10px] text-slate-500 mt-1">解释权重</div>
                        </div>
                      </div>
                      <p className="mt-3 text-sm text-slate-300 leading-relaxed">{feature.explanation}</p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        <span className="inline-flex rounded-full border border-cyan-500/20 bg-cyan-500/10 px-3 py-1 text-[11px] font-semibold text-cyan-100">
                          {feature.directionText}
                        </span>
                        {feature.rankIc !== undefined && (
                          <span className="inline-flex rounded-full border border-slate-700/40 bg-slate-900/60 px-3 py-1 text-[11px] font-semibold text-slate-300">
                            RankIC {formatValue(feature.rankIc, 'ratio')}
                          </span>
                        )}
                        {feature.source && (
                          <span className="inline-flex rounded-full border border-slate-700/40 bg-slate-900/60 px-3 py-1 text-[11px] font-semibold text-slate-400">
                            {feature.source}
                          </span>
                        )}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-2xl border border-slate-700/40 bg-slate-950/20 p-5 text-sm text-slate-400">
                    当前报告没有返回特征解释。
                  </div>
                )}
              </div>
            </article>

            <article
              className="xl:col-span-5 rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl space-y-5"
              style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
            >
              <div>
                <h3 className="text-lg font-black text-slate-100">下一步怎么用</h3>
                <p className="text-sm text-slate-400 mt-1">把报告转成可执行动作。</p>
              </div>
              <div className="space-y-3">
                {(userVerdict?.nextSteps ?? ['先运行一次体检，生成真实结果后再决定是否观察。']).map((step, index) => (
                  <div key={step} className="flex gap-3 rounded-2xl border border-slate-700/40 bg-slate-950/20 p-4">
                    <div className="w-7 h-7 rounded-full bg-emerald-500/10 text-emerald-200 flex items-center justify-center text-xs font-black shrink-0">
                      {index + 1}
                    </div>
                    <div className="text-sm text-slate-200 leading-relaxed">{step}</div>
                  </div>
                ))}
              </div>
              <div className="rounded-2xl border border-slate-700/40 bg-slate-950/20 p-4 text-xs leading-relaxed text-slate-400">
                胜率只说明交易里有多少次赚钱，不代表最终能赚钱。客户更应该同时看累计收益、最大回撤、成本拖累和高分组是否跑赢。
              </div>
            </article>
          </div>

          {previewSignals.length > 0 && (
            <article
              className="rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl space-y-5"
              style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
            >
              <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
	                <div>
	                  <h3 className="text-lg font-black text-slate-100">最近评分样例</h3>
	                  <p className="text-sm text-slate-400 mt-1">
	                    这些不是买入指令，只是模型在最近可评分日期给出的高分或触发样本。
	                  </p>
                    {displayedResult?.summary.sample_source_note && (
                      <p className="text-xs text-slate-500 mt-2 max-w-3xl">
                        {displayedResult.summary.sample_source_note}
                      </p>
                    )}
                    {displayedResult?.summary.universe_selection?.sample_refresh_rule && (
                      <p className="text-xs text-slate-500 mt-1 max-w-3xl">
                        样本规则：{displayedResult.summary.universe_selection.sample_refresh_rule}
                      </p>
                    )}
	                </div>
	                <div className="text-xs text-slate-500">
	                  推理日期：<span className="font-mono text-slate-300">{displayedResult?.summary.inference_date ?? '--'}</span>
                    <div className="mt-1">
                      分数来源：<span className="text-slate-300">{formatScoreSource(displayedResult?.summary.score_source)}</span>
                    </div>
	                </div>
	              </div>
	              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
	                {previewSignals.map((item) => {
                    const state = signalState(item.signal);
                    return (
	                  <div key={`${item.date}-${item.stock_code}-${item.daily_rank}`} className="rounded-2xl border border-slate-700/40 bg-slate-950/20 p-4">
	                    <div className="flex items-start justify-between gap-3">
	                      <div>
	                        <div className="text-sm font-black text-slate-100">{item.stock_name || item.stock_code}</div>
	                        <div className="text-xs font-mono text-slate-500 mt-1">{item.stock_code}</div>
	                      </div>
	                      <span className={cn(
	                        'rounded-full border px-2.5 py-1 text-[10px] font-bold',
	                        state.active ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200' : 'border-slate-700/40 bg-slate-900/60 text-slate-400'
	                      )}>
	                        {state.label}
	                      </span>
	                    </div>
	                    <div className="mt-4 grid grid-cols-2 gap-3 text-xs md:grid-cols-3">
	                      <div>
	                        <div className="text-slate-500">排名</div>
	                        <div className="mt-1 font-bold text-slate-100">{item.daily_rank ?? '--'}</div>
                      </div>
                      <div>
                        <div className="text-slate-500">分数</div>
                        <div className="mt-1 font-bold text-cyan-200">{item.score !== undefined ? item.score.toFixed(3) : '--'}</div>
                      </div>
	                      <div>
	                        <div className="text-slate-500">样本外</div>
	                        <div className="mt-1 font-bold text-slate-100">{formatOosState(item.is_oos_score)}</div>
	                      </div>
                        <div>
                          <div className="text-slate-500">评分日期</div>
                          <div className="mt-1 font-mono font-bold text-slate-100">{item.date || '--'}</div>
                        </div>
                        <div className="md:col-span-2">
                          <div className="text-slate-500">分数含义</div>
                          <div className="mt-1 font-bold text-slate-100">{formatScoreSource(item.score_source || displayedResult?.summary.score_source)}</div>
                        </div>
	                    </div>
	                  </div>
	                );
                  })}
	              </div>
	            </article>
	          )}

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            {strategyCards.map((card) => {
              const expanded = expandedCards[card.key];
              return (
                <article
                  key={card.key}
                  className="rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl space-y-5"
                  style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="space-y-2">
                      <div className="text-[11px] font-bold tracking-[0.18em] text-cyan-300">策略卡</div>
                      <h3 className="text-2xl font-black text-slate-100">{card.name}</h3>
                      <p className="text-sm text-slate-400 leading-relaxed">{card.shortDesc}</p>
                    </div>
                    <button
                      type="button"
                      onClick={() => setExpandedCards((prev) => ({ ...prev, [card.key]: !prev[card.key] }))}
                      className="inline-flex items-center gap-2 rounded-full border border-slate-700/50 px-3 py-1.5 text-xs font-semibold text-slate-300 hover:text-white"
                    >
                      {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                      {expanded ? '收起' : '展开'}
                    </button>
                  </div>

                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                    {[
                      ['赚钱吗', formatPercent(card.totalReturn)],
                      ['赢的次数多吗', formatPercent(card.winRate)],
                      ['经常出手吗', card.triggerText],
                      ['最近何时触发', card.lastTriggerDate],
                      ['最难受时亏多少', formatAbsPercent(card.maxDrawdown)],
                    ].map(([label, value]) => (
                      <div
                        key={label}
                        className={cn(
                          'rounded-2xl p-4 border border-slate-700/40 bg-slate-950/20',
                          label === '经常出手吗' && 'col-span-2 md:col-span-1'
                        )}
                      >
                        <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">{label}</div>
                        <div className="mt-2 text-sm font-semibold text-slate-100 leading-relaxed">{value || '--'}</div>
                      </div>
                    ))}
                  </div>

                  {expanded && (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                      <div className="rounded-2xl p-4 border border-slate-700/40 bg-slate-950/20">
                        <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">年化收益</div>
                        <div className="mt-2 text-lg font-black text-slate-100">{formatPercent(card.annualReturn)}</div>
                      </div>
                      <div className="rounded-2xl p-4 border border-slate-700/40 bg-slate-950/20">
                        <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">成本吃掉多少</div>
                        <div className="mt-2 text-lg font-black text-amber-300">{formatPercent(card.costDrag)}</div>
                      </div>
                      <div className="rounded-2xl p-4 border border-slate-700/40 bg-slate-950/20">
                        <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">最近看中了谁</div>
                        <div className="mt-2 text-slate-100 leading-relaxed">
                          {card.recentHits.length > 0 ? card.recentHits.join('、') : '--'}
                        </div>
                      </div>
                      <div className="rounded-2xl p-4 border border-slate-700/40 bg-slate-950/20">
                        <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">适合什么样的人</div>
                        <div className="mt-2 text-slate-100 leading-relaxed">
                          {card.suitableFor.length > 0 ? card.suitableFor.join(' ') : '--'}
                        </div>
                      </div>
                      <div className="rounded-2xl p-4 border border-slate-700/40 bg-slate-950/20">
                        <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">回测区间</div>
                        <div className="mt-2 text-slate-100 leading-relaxed">{card.backtestRange}</div>
                      </div>
                      <div className="rounded-2xl p-4 border border-slate-700/40 bg-slate-950/20">
                        <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">本次运行说明</div>
                        <div className="mt-2 text-slate-100 leading-relaxed">{card.runNote || '--'}</div>
                      </div>
                      <div className="rounded-2xl p-4 border border-slate-700/40 bg-slate-950/20 md:col-span-2">
                        <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">关注点解释</div>
                        <div className="mt-2 space-y-2 text-slate-100 leading-relaxed">
                          {card.focusPoints.length > 0 ? (
                            card.focusPoints.map((point) => <p key={point}>{point}</p>)
                          ) : (
                            <p>--</p>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      )}

      {hasHistoricalResult && expertMode && (
        <>
          <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-6 gap-6">
            {displayedMetrics.map((metric) => (
              <div
                key={metric.key}
                className="rounded-3xl p-6 shadow-xl"
                style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
              >
                <p className="text-[10px] font-bold text-slate-500 tracking-[0.18em]">{metric.label}</p>
                <p className="text-2xl font-black text-slate-100 mt-3">{formatValue(metric.value, metric.format)}</p>
                {metric.note && <p className="text-[11px] text-slate-400 mt-2 leading-relaxed">{metric.note}</p>}
              </div>
            ))}
          </section>

          {walkForward && (
            <section className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-6">
              <div
                className="rounded-3xl p-6 shadow-xl"
                style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
              >
                <p className="text-[10px] font-bold text-slate-500 tracking-[0.18em]">滚动训练</p>
                <p className="text-2xl font-black text-slate-100 mt-3">{walkForward.enabled ? '已启用' : '未启用'}</p>
                <p className="text-[11px] text-slate-400 mt-2 leading-relaxed">{walkForward.message || '研究结果不再只依赖单次静态切分。'}</p>
              </div>
              <div
                className="rounded-3xl p-6 shadow-xl"
                style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
              >
                <p className="text-[10px] font-bold text-slate-500 tracking-[0.18em]">评分来源</p>
                <p className="text-lg font-black text-cyan-300 mt-3 font-mono break-all">
                  {displayedResult?.summary.score_source ?? walkForward.score_source ?? '--'}
                </p>
                <p className="text-[11px] text-slate-400 mt-2 leading-relaxed">前端回测与预览分数优先跟随这个评分列。</p>
              </div>
              <div
                className="rounded-3xl p-6 shadow-xl"
                style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
              >
                <p className="text-[10px] font-bold text-slate-500 tracking-[0.18em]">预测覆盖率</p>
                <p className="text-2xl font-black text-slate-100 mt-3">{formatPercent(walkForward.coverage_ratio)}</p>
                <p className="text-[11px] text-slate-400 mt-2 leading-relaxed">滚动窗口里真正写回分数的样本占比。</p>
              </div>
              <div
                className="rounded-3xl p-6 shadow-xl"
                style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
              >
                <p className="text-[10px] font-bold text-slate-500 tracking-[0.18em]">重训窗口</p>
                <p className="text-2xl font-black text-slate-100 mt-3">{formatValue(walkForward.retrain_windows ?? null, 'integer')}</p>
                <p className="text-[11px] text-slate-400 mt-2 leading-relaxed">
                  每 {formatValue(walkForward.retrain_interval_dates ?? null, 'integer')} 个交易日滚动一次。
                </p>
              </div>
              <div
                className="rounded-3xl p-6 shadow-xl"
                style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
              >
                <p className="text-[10px] font-bold text-slate-500 tracking-[0.18em]">预测区间</p>
                <p className="text-lg font-black text-slate-100 mt-3">
                  {walkForward.first_prediction_date && walkForward.last_prediction_date
                    ? `${walkForward.first_prediction_date} ~ ${walkForward.last_prediction_date}`
                    : '--'}
                </p>
                <p className="text-[11px] text-slate-400 mt-2 leading-relaxed">这里显示滚动推理真正覆盖到的首尾日期。</p>
              </div>
            </section>
          )}

          <section className="grid grid-cols-1 xl:grid-cols-12 gap-8">
            <div
              className="xl:col-span-7 rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl overflow-x-auto"
              style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
            >
              <div className="flex items-center justify-between gap-4 mb-5">
                <div>
                  <h3 className="text-sm font-bold text-slate-300 tracking-[0.24em]">因子排行</h3>
                  <p className="text-xs text-slate-500 mt-1">按综合得分排序，优先看和截面收益最相关的候选因子。</p>
                </div>
                <div className="text-right text-xs text-slate-500">
                  <div>股票池：<span className="text-slate-300 font-semibold">{displayedResult?.summary.universe ?? '--'}</span></div>
                  <div>标签：<span className="text-slate-300 font-mono">{displayedResult?.summary.label ?? '--'}</span></div>
                </div>
              </div>

              <table className="w-full min-w-[680px] text-left border-collapse">
                <thead>
                  <tr>
                    {['因子', '得分', 'IC', 'Rank IC', '覆盖率', '稳定性', '方向'].map((column) => (
                      <th
                        key={column}
                        className="py-3 px-4 text-[10px] font-bold tracking-[0.22em] text-slate-500 border-b border-slate-700/50"
                      >
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="text-sm">
                  {displayedResult?.factor_ranking.map((item, index) => (
                    <tr key={item.factor} className="border-b border-blue-500/5 last:border-0 hover:bg-blue-500/5 transition-colors">
                      <td className="py-4 px-4">
                        <div className="flex items-center gap-3">
                          <span className={cn(
                            'w-7 h-7 rounded-full inline-flex items-center justify-center text-[11px] font-black',
                            index < 3 ? 'bg-cyan-500/15 text-cyan-300' : 'bg-slate-700/50 text-slate-400'
                          )}>
                            {index + 1}
                          </span>
                          <span className="font-mono text-slate-200">{item.factor}</span>
                        </div>
                      </td>
                      <td className="py-4 px-4 font-mono text-cyan-300">{item.score.toFixed(3)}</td>
                      <td className="py-4 px-4 font-mono text-slate-300">{formatValue(item.ic ?? null, 'ratio')}</td>
                      <td className="py-4 px-4 font-mono text-slate-300">{formatValue(item.rank_ic ?? null, 'ratio')}</td>
                      <td className="py-4 px-4 font-mono text-slate-300">{formatPercent(item.coverage)}</td>
                      <td className="py-4 px-4 font-mono text-slate-300">{formatPercent(item.stability)}</td>
                      <td className="py-4 px-4">
                        <span className="inline-flex rounded-full px-3 py-1 text-[10px] font-bold border border-emerald-500/20 bg-emerald-500/10 text-emerald-300">
                          {item.direction || 'long'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div
              className="xl:col-span-5 rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl"
              style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
            >
              <div className="flex items-center gap-3 mb-4">
                <TrendingUp className="w-5 h-5 text-cyan-300" />
                <div>
                  <h3 className="text-sm font-bold text-slate-300 tracking-[0.24em]">特征重要性</h3>
                  <p className="text-xs text-slate-500 mt-1">保留最核心的解释变量，正负方向用颜色区分。</p>
                </div>
              </div>
              <div className="h-[420px]">
                <EChart option={featureImportanceOption} style={{ height: '100%', width: '100%' }} />
              </div>
            </div>
          </section>

          <section className="grid grid-cols-1 xl:grid-cols-12 gap-8">
            <div
              className="xl:col-span-7 rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl"
              style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
            >
              <div className="flex items-center gap-3 mb-4">
                <BarChart3 className="w-5 h-5 text-indigo-300" />
                <div>
                  <h3 className="text-sm font-bold text-slate-300 tracking-[0.24em]">分桶结果</h3>
                  <p className="text-xs text-slate-500 mt-1">看排序模型是否真正拉开了高分组和低分组的回报差。</p>
                </div>
              </div>
              <div className="h-[360px]">
                <EChart option={bucketReturnOption} style={{ height: '100%', width: '100%' }} />
              </div>
            </div>

            <div className="xl:col-span-5 space-y-6">
              <div
                className="rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl"
                style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
              >
                <div className="flex items-center gap-3 mb-5">
                  <ShieldCheck className="w-5 h-5 text-emerald-300" />
                  <div>
                    <h3 className="text-sm font-bold text-slate-300 tracking-[0.24em]">稳定性摘要</h3>
                    <p className="text-xs text-slate-500 mt-1">把时间稳定性、样本覆盖率和换手一致性放在一起看。</p>
                  </div>
                </div>

                <div className="space-y-4">
                  {displayedResult?.stability.map((metric) => (
                    <div
                      key={metric.key}
                      className="rounded-2xl p-4 border border-slate-700/40 bg-slate-950/20 flex items-start justify-between gap-4"
                    >
                      <div>
                        <div className="text-sm font-bold text-slate-200">{metric.label}</div>
                        {metric.note && <div className="text-[11px] text-slate-500 mt-1 leading-relaxed">{metric.note}</div>}
                      </div>
                      <div className="text-right">
                        <div className="text-lg font-black text-emerald-300">{formatValue(metric.value, metric.format)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div
                className="rounded-[2rem] p-6 backdrop-blur-xl shadow-2xl"
                style={{ background: 'rgba(13, 27, 50, 0.45)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
              >
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div>
                    <div className="text-[10px] tracking-[0.18em] text-slate-500 font-bold">研究区间</div>
                    <div className="text-slate-200 mt-2 font-mono">{displayedResult?.summary.start_date ?? '--'} ~ {displayedResult?.summary.end_date ?? '--'}</div>
                  </div>
                  <div>
                    <div className="text-[10px] tracking-[0.18em] text-slate-500 font-bold">推理日期</div>
                    <div className="text-slate-200 mt-2 font-mono">{displayedResult?.summary.inference_date ?? '--'}</div>
                  </div>
                  <div>
                    <div className="text-[10px] tracking-[0.18em] text-slate-500 font-bold">有效标的</div>
                    <div className="text-slate-200 mt-2 font-semibold">{formatCompactNumber(displayedResult?.summary.total_symbols)}</div>
                  </div>
                  <div>
                    <div className="text-[10px] tracking-[0.18em] text-slate-500 font-bold">训练样本</div>
                    <div className="text-slate-200 mt-2 font-semibold">{formatCompactNumber(displayedResult?.summary.train_samples)}</div>
                  </div>
                </div>
                {displayedResult?.summary.research_note && (
                  <div className="mt-5 rounded-2xl border border-cyan-500/10 bg-cyan-500/5 p-4 text-xs text-cyan-100/80 leading-relaxed">
                    {displayedResult.summary.research_note}
                  </div>
                )}
              </div>
            </div>
          </section>

          <section
            className="rounded-[2.5rem] p-8 backdrop-blur-xl shadow-2xl space-y-6"
            style={{ background: 'rgba(13, 27, 50, 0.55)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}
          >
            <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
              <div className="space-y-2">
                <div className="flex items-center gap-3">
                  <div className={cn('p-3 rounded-2xl', colorMap[factorLabStrategyMeta.color]?.textBg, colorMap[factorLabStrategyMeta.color]?.text)}>
                    <Target className="w-5 h-5" />
                  </div>
                  <div>
                    <h3 className="text-xl font-bold text-slate-100">详细回测摘要</h3>
                    <p className="text-sm text-slate-400 mt-1">对两种 ML 策略的收益、成本和环境适应性做并排拆解。</p>
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => runBacktest(config)}
                disabled={loading || dateRangeInvalid}
                className="inline-flex items-center gap-2 rounded-2xl border border-slate-700/40 bg-slate-950/20 px-4 py-2.5 text-sm font-semibold text-slate-200 transition-all hover:text-white disabled:opacity-40"
              >
                {loadingAction === 'backtest' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Activity className="w-4 h-4" />}
                刷新详细回测
              </button>
            </div>

            {backtest ? (
              <div className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-5">
                  {[
                    { label: '累计收益', value: formatPercent(backtest.total_return), icon: TrendingUp, color: 'rose' },
                    { label: '年化收益', value: formatPercent(backtest.summary.annual_return), icon: Activity, color: 'blue' },
                    { label: '最大回撤', value: formatPercent(backtest.summary.max_drawdown), icon: ShieldCheck, color: 'emerald' },
                    { label: '夏普比率', value: formatValue(backtest.summary.sharpe_ratio, 'ratio'), icon: BrainCircuit, color: 'violet' },
                    { label: '交易次数', value: formatValue(backtest.summary.total_trades ?? null, 'integer'), icon: Target, color: 'cyan' },
                  ].map((item) => (
                    <div
                      key={item.label}
                      className="rounded-3xl p-5 flex items-center gap-4"
                      style={{ background: 'rgba(8, 18, 36, 0.72)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.12)' }}
                    >
                      <div className={cn('p-3 rounded-2xl', colorMap[item.color]?.textBg, colorMap[item.color]?.text)}>
                        <item.icon className="w-5 h-5" />
                      </div>
                      <div>
                        <div className="text-[10px] tracking-[0.18em] font-bold text-slate-500">{item.label}</div>
                        <div className="text-xl font-black text-slate-100 mt-1">{item.value}</div>
                      </div>
                    </div>
                  ))}
                </div>

                {strategyCards.length > 0 && (
                  <div className="space-y-4">
                    {leadingStrategy && (
                      <div className="rounded-2xl border border-emerald-500/15 bg-emerald-500/5 px-4 py-3 text-sm text-emerald-100">
                        当前含成本累计收益领先策略：<span className="font-semibold">{formatStrategyLabel(leadingStrategy)}</span>
                      </div>
                    )}
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                      {strategyCards.map((card) => {
                        const raw = ((displayedResult?.strategy_backtests ?? {}) as Record<string, FactorLabStrategyBacktest>)[card.key];
                        const withCost = raw?.with_cost ?? {};
                        const withoutCost = raw?.without_cost ?? {};
                        return (
                          <div
                            key={card.key}
                            className="rounded-3xl p-5 border border-slate-700/40 bg-slate-950/20 space-y-4"
                          >
                            <div className="flex items-center justify-between gap-3">
                              <div>
                                <div className="text-[10px] tracking-[0.18em] font-bold text-slate-500">策略对比</div>
                                <div className="text-lg font-bold text-slate-100 mt-1">{card.name}</div>
                              </div>
                              <div className="text-right">
                                <div className="text-[10px] tracking-[0.18em] font-bold text-slate-500">成本拖累</div>
                                <div className="text-lg font-bold text-amber-300 mt-1">{formatPercent(raw.cost_drag?.total_return_diff)}</div>
                              </div>
                            </div>
                            <div className="grid grid-cols-2 gap-4 text-sm">
                              <div className="rounded-2xl p-4 border border-cyan-500/15 bg-cyan-500/5">
                                <div className="text-[10px] tracking-[0.18em] font-bold text-slate-500">含成本</div>
                                <div className="text-slate-100 text-xl font-black mt-2">{formatPercent(withCost.total_return)}</div>
                                <div className="text-xs text-slate-500 mt-2">
                                  年化 {formatPercent(withCost.summary?.annual_return)} / 回撤 {formatPercent(withCost.summary?.max_drawdown)}
                                </div>
                              </div>
                              <div className="rounded-2xl p-4 border border-emerald-500/15 bg-emerald-500/5">
                                <div className="text-[10px] tracking-[0.18em] font-bold text-slate-500">去成本</div>
                                <div className="text-slate-100 text-xl font-black mt-2">{formatPercent(withoutCost.total_return)}</div>
                                <div className="text-xs text-slate-500 mt-2">
                                  年化 {formatPercent(withoutCost.summary?.annual_return)} / 费用 {formatPercent(raw.cost_drag?.cost_pct_initial)}
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 text-sm">
                  <div className="rounded-3xl p-5 border border-slate-700/40 bg-slate-950/20">
                    <div className="text-[10px] tracking-[0.18em] font-bold text-slate-500">最终净值</div>
                    <div className="text-slate-100 text-2xl font-black mt-2">
                      {new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 0 }).format(backtest.summary.final_value)}
                    </div>
                    <div className="text-xs text-slate-500 mt-2">初始资金 {new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 0 }).format(backtest.summary.initial_capital)}</div>
                  </div>

                  <div className="rounded-3xl p-5 border border-slate-700/40 bg-slate-950/20">
                    <div className="text-[10px] tracking-[0.18em] font-bold text-slate-500">组合风格</div>
                    <div className="text-slate-100 text-lg font-bold mt-2">
                      {backtest.metadata?.latest_regime ? `市场环境 ${backtest.metadata.latest_regime}` : '--'}
                    </div>
                    <div className="text-xs text-slate-500 mt-2">回测按因子分数排序执行，持仓数取 Top {config.top_n}。</div>
                  </div>

                  <div className="rounded-3xl p-5 border border-slate-700/40 bg-slate-950/20">
                    <div className="text-[10px] tracking-[0.18em] font-bold text-slate-500">数据路由</div>
                    <div className="text-slate-100 text-lg font-bold mt-2">{backtest.resolved_pool?.effective_pool ?? config.pool}</div>
                    <div className="text-xs text-slate-500 mt-2">
                      {backtest.resolved_pool?.symbols_count !== undefined
                        ? `本次命中 ${backtest.resolved_pool.symbols_count} 只标的`
                        : '--'}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="rounded-3xl p-8 border border-slate-700/40 bg-slate-950/20 text-slate-400 text-sm">
                当前还没有详细回测摘要。
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
