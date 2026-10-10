import { marketDate } from '../api/marketDate';
import { formatValue, formatPercent, formatAbsPercent, formatCompactNumber, formatStrategyLabel, formatScoreSource, formatModelBlend, formatOosState, signalState, getFailureMessage, getFailureCode, getFailureConfig, formatConfigSummary, getReadinessMessages, buildStrategyCards, buildUserVerdict, buildReliabilityChecks, buildPlainFeatureRows, getReliabilityTone, getVerdictTone, getCandidateStatusLabel, getPromotionTone, getScenarioTone, getScenarioPlainText, buildStressCards, getSelfIterationSummary, formatVersionShort, getLifecycleTitle, getVersionActionLabel, getLifecycleStatusLabel, getGateRows, getIterationStatusLabel, getIterationActionText } from './factor-lab/presenters';
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
import type { FactorLabRunConfig, FactorLabStrategyBacktest } from '../types';

const DEFAULT_START_DATE = '2022-01-01';
const DEFAULT_END_DATE = marketDate();
const TOP_N_OPTIONS = [3, 5, 10, 20] as const;
const SAMPLE_SIZE_OPTIONS = [180, 300, 500] as const;
const DEFAULT_EXPANDED: Record<string, boolean> = {
  ml_factor_ranker: true,
  ml_factor_filter: false,
};

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
      {displayedResult?.summary.price_mode === 'approximate_adjusted' && <div role="status" className="rounded-xl bg-amber-950/30 p-3 text-amber-200">当前结果使用近似复权价格；可用于研究比较，不可用于新版模拟账户。</div>}
      <label className="block text-xs text-amber-200"><input type="checkbox" checked={config.price_mode === 'approximate_adjusted'} onChange={e => setConfig(prev => ({...prev, price_mode: e.target.checked ? 'approximate_adjusted' : 'strict_raw'}))}/> 使用近似复权数据研究（产物不可用于新版模拟账户）</label>
      <div className="rounded-xl border border-amber-900/40 p-3 text-sm text-amber-200">因子成绩以滚动样本外窗口为准。旧评估产物需重新运行才能用于新版账户；窗口不足160个交易日时不会生成有效研究成绩。</div>
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
