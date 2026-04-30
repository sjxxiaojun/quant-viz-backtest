import React, { useState, useMemo } from 'react';
import { EChart } from './EChart';
import { Play, Loader2, GitCompare } from 'lucide-react';
import { strategyInfo, getAssetClassLabel, getStrategyAssetClass } from '../config/strategies';
import type { BacktestConfig } from '../types';
import { useCompare } from '../hooks/useCompare';
import { cn, escapeHtml } from '../utils';

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
  smooth: number | boolean;
  showSymbol: boolean;
  lineStyle: {
    color: string;
    width: number;
    type?: 'dashed';
  };
}

type MetricSummaryKey =
  | 'annual_return'
  | 'max_drawdown'
  | 'sharpe_ratio'
  | 'calmar_ratio'
  | 'win_rate'
  | 'profit_loss_ratio'
  | 'total_trades';

export function StrategyCompare({ config }: StrategyCompareProps) {
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([]);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const { loading, error, results, runCompare } = useCompare();
  const selectedAssetClass = selectedStrategies.length > 0 ? getStrategyAssetClass(selectedStrategies[0]) : null;

  const toggleStrategy = (key: string) => {
    const nextAssetClass = getStrategyAssetClass(key);
    setSelectedStrategies(prev => {
      if (prev.includes(key)) {
        setSelectionError(null);
        return prev.filter(k => k !== key);
      }
      if (prev.length > 0 && selectedAssetClass && selectedAssetClass !== nextAssetClass) {
        setSelectionError("A股策略和 ETF 策略不能混合对比，请分开选择。");
        return prev;
      }
      if (prev.length >= 4) return prev; // max 4
      setSelectionError(null);
      return [...prev, key];
    });
  };

  const handleRun = () => {
    if (selectedStrategies.length < 2) {
      setSelectionError("请至少选择 2 个策略进行对比");
      return;
    }
    runCompare({ ...config, pool: 'auto' }, selectedStrategies);
  };

  const equityChartOption = useMemo(() => {
    if (!results) return {};
    
    const series: LineSeries[] = [];
    const keys = Object.keys(results);
    if (keys.length === 0) return {};

    const dates = results[keys[0]].history.map(h => h.date);
    
    // Base colors for different lines
    const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ec4899'];

    keys.forEach((key, idx) => {
      series.push({
        name: strategyInfo[key]?.name || key,
        type: 'line',
        data: results[key].history.map(h => h.total_value),
        smooth: 0.4,
        showSymbol: false,
        lineStyle: { color: colors[idx], width: 2 },
      });
    });

    // Add benchmark if available from the first result
    const firstRes = results[keys[0]];
    if (firstRes.benchmark_history && firstRes.benchmark_history.length > 0) {
      series.push({
        name: '基准(沪深300)',
        type: 'line',
        data: firstRes.benchmark_history.map(h => h.value * firstRes.summary.initial_capital),
        smooth: 0.4,
        showSymbol: false,
        lineStyle: { color: '#94a3b8', width: 2, type: 'dashed' },
      });
    }

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        formatter: (params: CompareChartPoint[]) => {
          if (!params.length) return '';
          let content = `${escapeHtml(params[0].name)}<br/>`;
          params.forEach((point) => {
            content += `${point.marker || ''} ${escapeHtml(point.seriesName)}: ${Number(point.value || 0).toLocaleString('zh-CN')}<br/>`;
          });
          return content;
        },
      },
      legend: { textStyle: { color: '#94a3b8' }, top: 0 },
      grid: { left: '4%', right: '4%', bottom: '5%', top: '15%', containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8' }
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLine: { show: false },
        axisLabel: { color: '#94a3b8' },
        splitLine: { lineStyle: { color: '#0d2244', type: 'dashed' } }
      },
      series
    };
  }, [results]);

  const drawdownChartOption = useMemo(() => {
    if (!results) return {};
    
    const series: LineSeries[] = [];
    const keys = Object.keys(results);
    if (keys.length === 0) return {};

    const dates = results[keys[0]].history.map(h => h.date);
    const colors = ['#3b82f6', '#10b981', '#f59e0b', '#ec4899'];

    keys.forEach((key, idx) => {
      series.push({
        name: strategyInfo[key]?.name || key,
        type: 'line',
        data: results[key].history.map(h => h.drawdown || 0),
        smooth: true,
        showSymbol: false,
        lineStyle: { color: colors[idx], width: 2 },
      });
    });

    return {
      backgroundColor: 'transparent',
      tooltip: { 
	        trigger: 'axis',
	        formatter: (params: CompareChartPoint[]) => {
	          let str = `${escapeHtml(params[0].name)}<br/>`;
	          params.forEach(p => {
	            str += `${p.marker || ''} ${escapeHtml(p.seriesName)}: ${(p.value * 100).toFixed(2)}%<br/>`;
	          });
	          return str;
	        }
      },
      legend: { textStyle: { color: '#94a3b8' }, top: 0 },
      grid: { left: '4%', right: '4%', bottom: '5%', top: '15%', containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8' }
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisLabel: { color: '#94a3b8', formatter: (v: number) => (v * 100).toFixed(0) + '%' },
        splitLine: { lineStyle: { color: '#0d2244', type: 'dashed' } }
      },
      series
    };
  }, [results]);

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div className="rounded-3xl p-8 backdrop-blur-xl shadow-2xl" style={{ background: 'rgba(13, 27, 50, 0.5)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}>
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 mb-6">
          <div>
            <h2 className="text-xl font-bold flex items-center gap-2 text-slate-100">
              <GitCompare className="w-5 h-5 text-fuchsia-400" />
              策略 PK 大厅
            </h2>
            <p className="text-sm text-slate-400 mt-1">最多选择 4 个策略进行多维度同场竞技 (由于并发回测较慢，请耐心等待)</p>
            <p className="text-xs text-slate-500 mt-2">
              当前对比统一走自动路由。
              {selectedAssetClass ? ` 已锁定 ${getAssetClassLabel(selectedAssetClass)} 数据池。` : ' 选择首个策略后会自动锁定为 A股或 ETF 数据池。'}
            </p>
          </div>
          <button 
            onClick={handleRun}
            disabled={loading || selectedStrategies.length < 2}
            className="bg-fuchsia-600 hover:bg-fuchsia-500 disabled:bg-slate-700 disabled:text-slate-500 text-white px-6 py-2.5 rounded-xl font-bold transition-all flex items-center gap-2 whitespace-nowrap"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
            {loading ? "正在激战..." : "开始 PK"}
          </button>
        </div>

        {error && (
          <div className="bg-rose-500/10 border border-rose-500/20 text-rose-400 p-4 rounded-xl mb-6 text-sm">
            {error}
          </div>
        )}

        {selectionError && (
          <div className="bg-amber-500/10 border border-amber-500/20 text-amber-300 p-4 rounded-xl mb-6 text-sm">
            {selectionError}
          </div>
        )}

        <div className="flex flex-wrap gap-3">
          {Object.entries(strategyInfo).map(([key, info]) => {
            const isSelected = selectedStrategies.includes(key);
            const disabledByAsset =
              selectedAssetClass !== null &&
              !isSelected &&
              getStrategyAssetClass(key) !== selectedAssetClass;
            return (
              <button
                key={key}
                onClick={() => toggleStrategy(key)}
                disabled={disabledByAsset}
                className={cn(
                  "px-4 py-2 rounded-xl text-xs font-bold transition-all border",
                  isSelected 
                    ? "bg-fuchsia-500/20 border-fuchsia-500/50 text-fuchsia-300"
                    : disabledByAsset
                      ? "border-transparent text-slate-600 opacity-50 cursor-not-allowed"
                      : "border-transparent text-slate-400 hover:border-blue-500/30 hover:text-slate-200"
                )}
                style={{ background: isSelected ? undefined : 'rgba(10, 22, 40, 0.5)' }}
              >
                {info.name}
              </button>
            )
          })}
        </div>
      </div>

      {results && Object.keys(results).length > 0 && (
        <div className="space-y-8 animate-in slide-in-from-bottom-8 duration-700">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <div className="rounded-3xl p-6 backdrop-blur-xl shadow-2xl" style={{ background: 'rgba(13, 27, 50, 0.5)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}>
              <h3 className="text-sm font-bold text-slate-400 mb-4 tracking-widest uppercase">净值曲线大乱斗</h3>
              <div className="h-72">
                <EChart option={equityChartOption} style={{ height: '100%', width: '100%' }} />
              </div>
            </div>
            <div className="rounded-3xl p-6 backdrop-blur-xl shadow-2xl" style={{ background: 'rgba(13, 27, 50, 0.5)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}>
              <h3 className="text-sm font-bold text-slate-400 mb-4 tracking-widest uppercase">回撤抗压测试</h3>
              <div className="h-72">
                <EChart option={drawdownChartOption} style={{ height: '100%', width: '100%' }} />
              </div>
            </div>
          </div>

          <div className="rounded-3xl p-6 backdrop-blur-xl shadow-2xl overflow-x-auto" style={{ background: 'rgba(13, 27, 50, 0.5)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}>
            <h3 className="text-sm font-bold text-slate-400 mb-6 tracking-widest uppercase">雷达数据对比</h3>
            <table className="w-full text-left border-collapse min-w-[600px]">
              <thead>
                <tr>
                  <th className="py-4 px-4 text-xs font-bold text-slate-500 uppercase tracking-widest border-b border-slate-700/50">指标</th>
                  {Object.keys(results).map(key => (
                    <th key={key} className="py-4 px-4 text-xs font-bold text-slate-200 border-b border-slate-700/50">
                      {strategyInfo[key]?.name || key}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="text-sm">
                {[
                  { label: "累计收益", key: "total_return" as const, fmt: (v: number) => (v * 100).toFixed(2) + "%", higherIsBetter: true },
                  { label: "年化收益", key: "annual_return" as const, fmt: (v: number) => (v * 100).toFixed(2) + "%", higherIsBetter: true },
                  { label: "最大回撤", key: "max_drawdown" as const, fmt: (v: number) => (v * 100).toFixed(2) + "%", higherIsBetter: false },
                  { label: "夏普比率", key: "sharpe_ratio" as const, fmt: (v: number) => v.toFixed(2), higherIsBetter: true },
                  { label: "卡尔马比率", key: "calmar_ratio" as const, fmt: (v: number) => v.toFixed(2), higherIsBetter: true },
                  { label: "胜率", key: "win_rate" as const, fmt: (v: number) => (v * 100).toFixed(2) + "%", higherIsBetter: true },
                  { label: "盈亏比", key: "profit_loss_ratio" as const, fmt: (v: number) => v.toFixed(2), higherIsBetter: true },
                  { label: "交易次数", key: "total_trades" as const, fmt: (v: number) => v.toString(), higherIsBetter: null }
                ].map((metric, i) => (
                  <tr key={i} className="border-b border-blue-500/5 last:border-0 hover:bg-blue-500/5 transition-colors">
                    <td className="py-4 px-4 font-bold text-slate-400">{metric.label}</td>
                    {Object.keys(results).map(key => {
                      const val = metric.key === 'total_return'
                        ? results[key].total_return
                        : results[key].summary[metric.key as MetricSummaryKey];
                      
                      // Highlight the best value
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
                        <td key={key} className={cn(
                          "py-4 px-4 font-mono",
                          isBest ? "text-emerald-400 font-bold" : "text-slate-300"
                        )}>
                          {val !== undefined ? metric.fmt(val) : '--'}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
