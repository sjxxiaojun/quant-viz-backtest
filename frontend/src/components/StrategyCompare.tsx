import { useCallback, useMemo, useState } from 'react';
import { GitCompare, Loader2, Play } from 'lucide-react';
import { EChart } from './EChart';
import { EmptyState, Panel, SectionTitle, Skeleton, Tag } from './ui';
import { TOOLTIP_STYLE, paletteColor } from '../theme/echartsTheme';
import { getAssetClassLabel } from '../config/strategies';
import { groupByCategory } from '../api/strategyCatalog';
import { useStrategyCatalog } from '../hooks/useStrategyCatalog';
import { useCompare } from '../hooks/useCompare';
import { cn, escapeHtml, formatNumber, formatPercent } from '../utils';
import type { BacktestConfig } from '../types';

interface StrategyCompareProps {
  config: BacktestConfig;
}

interface CompareChartPoint {
  marker?: string;
  name: string;
  seriesName: string;
  value: number;
}

interface LineSeries {
  name: string;
  type: 'line';
  data: number[];
  showSymbol: boolean;
  sampling?: string;
  lineStyle: {
    color: string;
    width: number;
    type?: 'dashed';
  };
  itemStyle: { color: string };
}

type MetricSummaryKey =
  | 'annual_return'
  | 'max_drawdown'
  | 'sharpe_ratio'
  | 'calmar_ratio'
  | 'win_rate'
  | 'profit_loss_ratio'
  | 'total_trades';

const MAX_SELECTION = 4;
/** 基准线固定用色板中性灰 (最后一位) */
const BENCHMARK_COLOR = paletteColor(7);

export function StrategyCompare({ config }: StrategyCompareProps) {
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([]);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const { catalog, byId, loading: catalogLoading, fallbackReason } = useStrategyCatalog();
  const { loading, error, results, runCompare } = useCompare();

  const selectedAssetClass = selectedStrategies.length > 0
    ? byId.get(selectedStrategies[0])?.assetClass ?? 'a_share'
    : null;

  const strategyName = useCallback((key: string) => byId.get(key)?.name || key, [byId]);

  const toggleStrategy = (key: string) => {
    const nextAssetClass = byId.get(key)?.assetClass ?? 'a_share';
    setSelectedStrategies(prev => {
      if (prev.includes(key)) {
        setSelectionError(null);
        return prev.filter(k => k !== key);
      }
      if (prev.length > 0 && selectedAssetClass && selectedAssetClass !== nextAssetClass) {
        setSelectionError('A股策略和 ETF 策略不能混合对比，请分开选择。');
        return prev;
      }
      if (prev.length >= MAX_SELECTION) {
        setSelectionError(`最多同时对比 ${MAX_SELECTION} 个策略。`);
        return prev;
      }
      setSelectionError(null);
      return [...prev, key];
    });
  };

  const handleRun = () => {
    if (selectedStrategies.length < 2) {
      setSelectionError('请至少选择 2 个策略进行对比');
      return;
    }
    runCompare({ ...config, pool: 'auto' }, selectedStrategies);
  };

  const equityChartOption = useMemo(() => {
    if (!results) return {};

    const keys = Object.keys(results);
    if (keys.length === 0) return {};

    const dates = results[keys[0]].history.map(h => h.date);
    const series: LineSeries[] = keys.map((key, idx) => ({
      name: strategyName(key),
      type: 'line',
      data: results[key].history.map(h => h.total_value),
      sampling: 'lttb',
      showSymbol: false,
      lineStyle: { color: paletteColor(idx), width: 1.5 },
      itemStyle: { color: paletteColor(idx) },
    }));

    const firstRes = results[keys[0]];
    if (firstRes.benchmark_history && firstRes.benchmark_history.length > 0) {
      series.push({
        name: '基准(沪深300)',
        type: 'line',
        data: firstRes.benchmark_history.map(h => h.value * firstRes.summary.initial_capital),
        sampling: 'lttb',
        showSymbol: false,
        lineStyle: { color: BENCHMARK_COLOR, width: 1, type: 'dashed' },
        itemStyle: { color: BENCHMARK_COLOR },
      });
    }

    return {
      tooltip: {
        ...TOOLTIP_STYLE,
        trigger: 'axis',
        formatter: (params: CompareChartPoint[]) => {
          if (!params.length) return '';
          let content = `${escapeHtml(params[0].name)}<br/>`;
          params.forEach((point) => {
            content += `${point.marker || ''} ${escapeHtml(point.seriesName)}: ${formatNumber(Number(point.value || 0), 0)}<br/>`;
          });
          return content;
        },
      },
      legend: { top: 0 },
      grid: { left: 8, right: 12, top: 32, bottom: 8, containLabel: true },
      xAxis: { type: 'category', data: dates },
      yAxis: { type: 'value', scale: true },
      series,
    };
  }, [results, strategyName]);

  const drawdownChartOption = useMemo(() => {
    if (!results) return {};

    const keys = Object.keys(results);
    if (keys.length === 0) return {};

    const dates = results[keys[0]].history.map(h => h.date);
    const series: LineSeries[] = keys.map((key, idx) => ({
      name: strategyName(key),
      type: 'line',
      data: results[key].history.map(h => h.drawdown || 0),
      sampling: 'lttb',
      showSymbol: false,
      lineStyle: { color: paletteColor(idx), width: 1.5 },
      itemStyle: { color: paletteColor(idx) },
    }));

    return {
      tooltip: {
        ...TOOLTIP_STYLE,
        trigger: 'axis',
        formatter: (params: CompareChartPoint[]) => {
          let str = `${escapeHtml(params[0].name)}<br/>`;
          params.forEach(p => {
            str += `${p.marker || ''} ${escapeHtml(p.seriesName)}: ${formatPercent(p.value)}<br/>`;
          });
          return str;
        },
      },
      legend: { top: 0 },
      grid: { left: 8, right: 12, top: 32, bottom: 8, containLabel: true },
      xAxis: { type: 'category', data: dates },
      yAxis: {
        type: 'value',
        axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
      },
      series,
    };
  }, [results, strategyName]);

  return (
    <div className="space-y-3">
      <Panel>
        <div className="mb-3 flex flex-col justify-between gap-3 md:flex-row md:items-center">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-slate-100">
              <GitCompare className="h-4 w-4 text-accent" />
              策略对比
            </h2>
            <p className="mt-1 text-[11px] text-slate-500">
              选择 2-{MAX_SELECTION} 个策略并发回测同场对比，统一走自动数据池路由。
              {selectedAssetClass
                ? ` 已锁定 ${getAssetClassLabel(selectedAssetClass)} 数据池。`
                : ' 选择首个策略后会锁定为 A股或 ETF 数据池。'}
            </p>
          </div>
          <button
            type="button"
            onClick={handleRun}
            disabled={loading || selectedStrategies.length < 2}
            className="flex items-center gap-2 whitespace-nowrap rounded-ctl bg-accent px-4 py-2 text-xs font-semibold text-white transition-colors hover:bg-accent/85 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            {loading ? '对比回测运行中...' : '开始对比'}
          </button>
        </div>

        {error && (
          <div className="mb-3 rounded-ctl border border-up/30 bg-up/10 px-3 py-2 text-xs text-up-soft">
            {error}
          </div>
        )}

        {selectionError && (
          <div className="mb-3 rounded-ctl border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
            {selectionError}
          </div>
        )}

        {fallbackReason && (
          <div className="mb-3 rounded-ctl border border-warn/30 bg-warn/10 px-3 py-2 text-[11px] text-warn">
            策略目录接口不可用，仅展示本地内置策略（{fallbackReason}）。
          </div>
        )}

        {catalogLoading ? (
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {Array.from({ length: 8 }, (_, i) => (
              <Skeleton key={i} className="h-8" />
            ))}
          </div>
        ) : (
          <div className="space-y-2.5">
            {groupByCategory(catalog).map(([category, entries]) => (
              <div key={category}>
                <div className="label-caps mb-1.5">{category}</div>
                <div className="flex flex-wrap gap-1.5">
                  {entries.map((entry) => {
                    const isSelected = selectedStrategies.includes(entry.id);
                    const disabledByAsset =
                      selectedAssetClass !== null && !isSelected && entry.assetClass !== selectedAssetClass;
                    return (
                      <button
                        key={entry.id}
                        type="button"
                        onClick={() => toggleStrategy(entry.id)}
                        disabled={disabledByAsset}
                        className={cn(
                          'rounded-ctl border px-2.5 py-1.5 text-[11px] font-medium transition-colors',
                          isSelected
                            ? 'border-accent/50 bg-accent/15 text-accent'
                            : disabledByAsset
                              ? 'cursor-not-allowed border-line text-slate-700'
                              : 'border-line bg-bg2 text-slate-400 hover:bg-bg3 hover:text-slate-200',
                        )}
                      >
                        {entry.name}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      {loading && !results && (
        <Panel>
          <SectionTitle>对比结果</SectionTitle>
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Skeleton className="h-64" />
            <Skeleton className="h-64" />
          </div>
        </Panel>
      )}

      {!loading && !results && !error && (
        <EmptyState
          title="尚未运行对比"
          description="选择至少 2 个同资产类别的策略后点击「开始对比」。"
        />
      )}

      {results && Object.keys(results).length > 0 && (
        <div className="space-y-3">
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            <Panel>
              <SectionTitle>净值曲线对比</SectionTitle>
              <div className="h-64">
                <EChart option={equityChartOption} style={{ height: '100%', width: '100%' }} />
              </div>
            </Panel>
            <Panel>
              <SectionTitle>回撤对比</SectionTitle>
              <div className="h-64">
                <EChart option={drawdownChartOption} style={{ height: '100%', width: '100%' }} />
              </div>
            </Panel>
          </div>

          <Panel className="overflow-x-auto">
            <SectionTitle right={<Tag tone="accent">高亮 = 该指标最优</Tag>}>指标对比</SectionTitle>
            <table className="w-full min-w-[600px] border-collapse text-left">
              <thead>
                <tr className="border-b border-line-strong">
                  <th className="label-caps py-2 pr-3 font-semibold">指标</th>
                  {Object.keys(results).map(key => (
                    <th key={key} className="py-2 pr-3 text-xs font-semibold text-slate-200">
                      {strategyName(key)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="text-xs">
                {[
                  { label: '累计收益', key: 'total_return' as const, fmt: (v: number) => formatPercent(v), higherIsBetter: true },
                  { label: '年化收益', key: 'annual_return' as const, fmt: (v: number) => formatPercent(v), higherIsBetter: true },
                  { label: '最大回撤', key: 'max_drawdown' as const, fmt: (v: number) => formatPercent(v), higherIsBetter: false },
                  { label: '夏普比率', key: 'sharpe_ratio' as const, fmt: (v: number) => formatNumber(v), higherIsBetter: true },
                  { label: '卡尔马比率', key: 'calmar_ratio' as const, fmt: (v: number) => formatNumber(v), higherIsBetter: true },
                  { label: '胜率', key: 'win_rate' as const, fmt: (v: number) => formatPercent(v), higherIsBetter: true },
                  { label: '盈亏比', key: 'profit_loss_ratio' as const, fmt: (v: number) => formatNumber(v), higherIsBetter: true },
                  { label: '交易次数', key: 'total_trades' as const, fmt: (v: number) => formatNumber(v, 0), higherIsBetter: null },
                ].map((metric, i) => (
                  <tr key={i} className="h-8 border-b border-line transition-colors last:border-0 hover:bg-bg2">
                    <td className="py-1.5 pr-3 font-medium text-slate-400">{metric.label}</td>
                    {Object.keys(results).map(key => {
                      const val = metric.key === 'total_return'
                        ? results[key].total_return
                        : results[key].summary[metric.key as MetricSummaryKey];

                      const allVals = Object.keys(results)
                        .map((strategyKey) => (
                          metric.key === 'total_return'
                            ? results[strategyKey].total_return
                            : results[strategyKey].summary[metric.key as MetricSummaryKey]
                        ))
                        .filter((value): value is number => value !== undefined);
                      const isBest = metric.higherIsBetter !== null && (
                        allVals.length > 0 && val !== undefined &&
                        (metric.higherIsBetter ? val === Math.max(...allVals) : val === Math.min(...allVals))
                      );

                      return (
                        <td
                          key={key}
                          className={cn(
                            'num py-1.5 pr-3',
                            // 最优值统一用 accent 高亮, 避免与红涨绿跌语义混淆
                            isBest ? 'font-semibold text-accent' : 'text-slate-300',
                          )}
                        >
                          {val !== undefined ? metric.fmt(val) : '--'}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </div>
      )}
    </div>
  );
}
