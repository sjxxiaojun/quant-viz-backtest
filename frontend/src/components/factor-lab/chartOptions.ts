/**
 * Factor Lab 图表 option 构造（只提供数据与结构，样式由统一 ECharts 终端主题兜底）。
 * 颜色一律取自 theme/echartsTheme 的统一色板与 A股涨跌语义。
 */
import type { EChartsCoreOption } from 'echarts/core';
import { escapeHtml, changeColorHex } from '../../utils';
import { TOOLTIP_STYLE, paletteColor } from '../../theme/echartsTheme';
import type { FactorLabResult } from '../../types';

/** 特征重要性横向条形图 (top 8) */
export function buildFeatureImportanceOption(result: FactorLabResult | null): EChartsCoreOption {
  if (!result) return {};
  const sorted = [...result.feature_importance]
    .sort((left, right) => right.importance - left.importance)
    .slice(0, 8)
    .reverse();

  return {
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: Array<{ name?: string; value: number }>) => {
        const point = params[0];
        return `${escapeHtml(point.name)}<br/>重要性: ${(point.value * 100).toFixed(1)}%`;
      },
    },
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: {
      type: 'value',
      axisLabel: { formatter: (value: number) => `${(value * 100).toFixed(0)}%` },
    },
    yAxis: {
      type: 'category',
      data: sorted.map((item) => item.feature),
    },
    series: [
      {
        type: 'bar',
        data: sorted.map((item) => ({
          value: item.importance,
          // 方向色: 正向因子=主色, 反向因子=次色 (与涨跌语义无关, 避免误读)
          itemStyle: { color: item.direction === 'negative' ? paletteColor(2) : paletteColor(1) },
        })),
        barWidth: 10,
      },
    ],
  };
}

/** 分桶收益柱状图: 分桶收益按 A股红涨绿跌着色, 超额收益取统一色板 */
export function buildBucketReturnOption(result: FactorLabResult | null): EChartsCoreOption {
  if (!result) return {};
  return {
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: Array<{ marker?: string; seriesName?: string; value: number; name?: string }>) => {
        const rows = params
          .map((point) => `${point.marker || ''} ${escapeHtml(point.seriesName)}: ${(point.value * 100).toFixed(2)}%`)
          .join('<br/>');
        return `${escapeHtml(params[0]?.name || '')}<br/>${rows}`;
      },
    },
    legend: { top: 0 },
    grid: { left: 8, right: 8, top: 32, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: result.bucket_returns.map((item) => item.bucket),
    },
    yAxis: {
      type: 'value',
      axisLabel: { formatter: (value: number) => `${(value * 100).toFixed(0)}%` },
    },
    series: [
      {
        name: '分桶收益',
        type: 'bar',
        data: result.bucket_returns.map((item) => ({
          value: item.return,
          itemStyle: { color: changeColorHex(item.return) },
        })),
        barWidth: 14,
      },
      {
        name: '超额收益',
        type: 'bar',
        data: result.bucket_returns.map((item) => item.excess_return ?? 0),
        itemStyle: { color: paletteColor(0) },
        barWidth: 14,
      },
    ],
  };
}

/** 三情景压测样例净值路径 */
export function buildStressPathOption(result: FactorLabResult | null): EChartsCoreOption {
  const stressTest = result?.stress_test;
  if (!stressTest?.scenarios?.length) return {};
  const preferredFactor = result?.backtest_compare?.best_total_return_factor || 'ml_factor_ranker';
  const series = stressTest.scenarios.flatMap((scenario, index) =>
    (scenario.sample_paths ?? [])
      .filter((path) => path.factor === preferredFactor)
      .slice(0, 1)
      .map((path) => ({
        name: scenario.name_cn,
        type: 'line' as const,
        smooth: true,
        showSymbol: false,
        lineStyle: { color: paletteColor(index) },
        itemStyle: { color: paletteColor(index) },
        data: path.history.map((point) => [point.date, point.total_value]),
      }))
  );
  return {
    tooltip: {
      ...TOOLTIP_STYLE,
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
    legend: { top: 0 },
    grid: { left: 8, right: 8, top: 32, bottom: 8, containLabel: true },
    xAxis: { type: 'time' },
    yAxis: { type: 'value' },
    series,
  };
}
