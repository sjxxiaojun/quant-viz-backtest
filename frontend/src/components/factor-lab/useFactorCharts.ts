import { useMemo } from 'react';
import { escapeHtml } from '../../utils';
import type { FactorLabResult } from '../../types';
export function useFactorCharts(displayedResult: FactorLabResult | null) {
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
      grid: {
        left: '4%',
        right: '6%',
        bottom: '5%',
        top: '5%',
        containLabel: true,
      },
      xAxis: {
        type: 'value',
        axisLine: { show: false },
        axisLabel: {
          color: '#94a3b8',
          formatter: (value: number) => `${(value * 100).toFixed(0)}%`,
        },
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
        formatter: (
          params: Array<{
            marker?: string;
            seriesName?: string;
            value: number;
            name?: string;
          }>,
        ) => {
          const rows = params
            .map(
              (point) =>
                `${point.marker || ''} ${escapeHtml(point.seriesName)}: ${(point.value * 100).toFixed(2)}%`,
            )
            .join('<br/>');
          return `${escapeHtml(params[0]?.name || '')}<br/>${rows}`;
        },
      },
      legend: { textStyle: { color: '#94a3b8' }, top: 0 },
      grid: {
        left: '4%',
        right: '4%',
        bottom: '5%',
        top: '15%',
        containLabel: true,
      },
      xAxis: {
        type: 'category',
        data: displayedResult.bucket_returns.map((item) => item.bucket),
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8' },
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisLabel: {
          color: '#94a3b8',
          formatter: (value: number) => `${(value * 100).toFixed(0)}%`,
        },
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
          data: displayedResult.bucket_returns.map(
            (item) => item.excess_return ?? 0,
          ),
          itemStyle: { color: '#818cf8', borderRadius: [10, 10, 0, 0] },
          barWidth: 18,
        },
      ],
    };
  }, [displayedResult]);
  const stressPathOption = useMemo(() => {
    const stressTest = displayedResult?.stress_test;
    if (!stressTest?.scenarios?.length) return {};
    const series = stressTest.scenarios.flatMap((scenario) =>
      (scenario.sample_paths ?? [])
        .filter(
          (path) =>
            path.factor ===
            (displayedResult?.backtest_compare?.best_total_return_factor ||
              'ml_factor_ranker'),
        )
        .slice(0, 1)
        .map((path) => ({
          name: scenario.name_cn,
          type: 'line',
          smooth: true,
          showSymbol: false,
          data: path.history.map((point) => [point.date, point.total_value]),
        })),
    );
    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        formatter: (
          params: Array<{
            marker?: string;
            seriesName?: string;
            value?: [string, number] | number;
            name?: string;
          }>,
        ) => {
          if (!params.length) return '';
          const firstValue = params[0]?.value;
          const label =
            params[0]?.name || (Array.isArray(firstValue) ? firstValue[0] : '');
          const rows = params
            .map((point) => {
              const rawValue = Array.isArray(point.value)
                ? point.value[1]
                : point.value;
              return `${point.marker || ''} ${escapeHtml(point.seriesName || '')}: ${Number(rawValue || 0).toLocaleString('zh-CN')}`;
            })
            .join('<br/>');
          return `${escapeHtml(label)}<br/>${rows}`;
        },
      },
      legend: { textStyle: { color: '#94a3b8' }, top: 0 },
      grid: {
        left: '4%',
        right: '4%',
        bottom: '8%',
        top: '15%',
        containLabel: true,
      },
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
  return { featureImportanceOption, bucketReturnOption, stressPathOption };
}
