/**
 * Factor Lab 结论层纯函数：客户视角评分、可靠性检查、策略卡、压测卡。
 * 与 UI 解耦，阈值即业务规则，可独立单测。
 */
import type {
  FactorLabResult,
  FactorLabRunReadiness,
  FactorLabSelfIteration,
  FactorLabStrategyBacktest,
  FactorLabStrategyLifecycle,
  FactorLabStressScenario,
  StrategyVersionIteration,
  StrategyVersionRecord,
} from '../../types';
import {
  STRATEGY_COPY,
  explainFeature,
  explainFocusPoint,
  fmtAbsPct,
  fmtPct,
  formatCompactNumber,
  formatFactorPlainName,
  formatValue,
  getCandidateStatusLabel,
  type ReliabilityStatus,
} from './labels';

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

export function getReadinessMessages(readiness: FactorLabRunReadiness | null, checkingReadiness: boolean): string[] {
  if (checkingReadiness) return ['正在检查本地数据完整性与可运行性。'];
  if (!readiness) return ['暂未拿到本地数据检查结果，运行前会先做检查。'];
  if (readiness.warning_message) return [readiness.warning_message];
  if (readiness.needs_backfill) return ['本地数据仍有缺口，运行时会优先补齐缺失部分。'];
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
    const detail = strategyBacktests[key] ?? ({} as Partial<FactorLabStrategyBacktest>);
    const withCost = detail.with_cost ?? ({} as Partial<NonNullable<FactorLabStrategyBacktest['with_cost']>>);
    const summary = withCost.summary ?? ({} as Partial<NonNullable<typeof withCost.summary>>);
    const userView = detail.user_view;
    const triggerText = userView
      ? `${userView.trigger_days} 个交易日 / ${userView.total_trades} 笔交易`
      : summary.total_trades !== undefined
        ? `累计触发 ${summary.total_trades} 笔交易`
        : '--';

    return {
      key,
      name: userView?.name_cn || STRATEGY_COPY[key].name,
      shortDesc: userView?.description_cn || STRATEGY_COPY[key].shortDesc,
      totalReturn: userView?.total_return ?? withCost.total_return,
      winRate: userView?.win_rate ?? summary.win_rate,
      triggerText,
      lastTriggerDate: userView?.last_signal_date || '--',
      maxDrawdown: userView?.max_drawdown ?? summary.max_drawdown,
      annualReturn: userView?.annual_return ?? summary.annual_return,
      costDrag: userView?.cost_drag?.total_return_diff ?? detail.cost_drag?.total_return_diff,
      recentHits: userView?.recent_signal_symbols ?? [],
      suitableFor: userView?.suitable_for ?? [STRATEGY_COPY[key].suitableFor],
      backtestRange: range,
      runNote: sharedRunNote,
      focusPoints: (userView?.focus_points ?? []).map(explainFocusPoint),
    };
  });
}

function clampScore(value: number): number {
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

  // 评分启发式：50 分起步，各证据维度加减分（阈值即业务口径）
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
    level === 'strong' ? '可以进入小仓观察' : level === 'watch' ? '有观察价值，但先别放大仓位' : '暂不建议直接使用';

  const reasons = [
    `含成本回测领先的是${leadingStrategy?.name ?? '当前策略'}，累计收益 ${fmtPct(totalReturn)}，年化 ${fmtPct(leadingStrategy?.annualReturn)}。`,
    `样本覆盖 ${formatCompactNumber(totalSymbols)} 只股票、${formatCompactNumber(trainSamples)} 条训练样本，不是只看少数个案。`,
    coverage !== undefined
      ? `滚动验证覆盖率 ${fmtPct(coverage)}，用于判断模型在后续时间段是否还能工作。`
      : '当前没有滚动验证覆盖率，结论需要再看专家模式里的时间稳定性。',
  ];

  const risks = [
    totalReturn <= 0 ? '含成本收益还没有转正，不能只看胜率。' : '',
    drawdownAbs >= 0.15 ? `过程中最大浮亏约 ${fmtAbsPct(leadingStrategy?.maxDrawdown)}，持有体验偏难受。` : '',
    costDrag >= 0.02 ? `交易成本吃掉约 ${fmtPct(costDrag)}，频繁换仓会明显影响结果。` : '',
    winRate < 0.5 ? `胜率 ${fmtPct(winRate)} 未过半，命中稳定性仍需复核。` : '',
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
  const sourceCounts = Object.values(result.data_sources_used ?? {}).reduce<Record<string, number>>((acc, source) => {
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
      value: coverage !== undefined ? fmtPct(coverage) : '--',
      detail: '滚动验证是在后面的时间段继续打分，能减少“只会解释历史”的问题。',
      status: coverage === undefined ? 'neutral' : coverage >= 0.8 ? 'good' : coverage >= 0.6 ? 'warn' : 'bad',
    },
    {
      label: '高分组是否更强',
      value: bucketSpread !== undefined ? fmtPct(bucketSpread) : '--',
      detail: '如果高分组没有明显跑赢低分组，说明打分规则的区分度还不够。',
      status: bucketSpread === undefined ? 'neutral' : bucketSpread > 0.01 ? 'good' : bucketSpread > 0 ? 'warn' : 'bad',
    },
    {
      label: '回撤是否可承受',
      value: leading ? fmtAbsPct(leading.maxDrawdown) : '--',
      detail: '最大回撤表示过程中最难受的浮亏幅度，比单看收益更接近真实体验。',
      status: drawdownAbs <= 0.1 ? 'good' : drawdownAbs <= 0.18 ? 'warn' : 'bad',
    },
    {
      label: '交易成本是否敏感',
      value: costDrag !== undefined ? fmtPct(costDrag) : '--',
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
    { label: '含成本收益', passed: version.gates.with_cost_return_positive, value: fmtPct(version.metrics.with_cost_total_return) },
    { label: '最大回撤', passed: version.gates.max_drawdown_ok, value: fmtAbsPct(version.metrics.max_drawdown_abs) },
    { label: '成本拖累', passed: version.gates.cost_drag_ok, value: fmtPct(version.metrics.cost_drag) },
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
