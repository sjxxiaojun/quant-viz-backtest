/**
 * momo quant pro — ECharts 统一终端主题
 *
 * 在 main.tsx 中通过 echarts.registerTheme(ECHARTS_THEME_NAME, echartsTerminalTheme)
 * 注册一次；EChart 组件默认以该主题初始化。
 * 各视图的 option 只需提供数据与结构，轴线/网格/tooltip/动画风格由主题兜底。
 */

export const ECHARTS_THEME_NAME = 'momo-terminal';

/** A股语义: 红涨绿跌 (与 index.css 的 --color-up / --color-down 对齐) */
export const UP_COLOR = '#f5483d';
export const DOWN_COLOR = '#16a34a';

/** 曲线系列色板 (6-8 色, 暗底可读) */
export const CHART_PALETTE = [
  '#5b8def', // 蓝 (主)
  '#38bdf8', // 青
  '#a78bfa', // 紫
  '#f5a97f', // 橙
  '#f472b6', // 粉
  '#facc15', // 黄
  '#4dd4ac', // 青绿
  '#94a3b8', // 中性灰
];

/** 按索引安全取系列色 (自动取模, 不会越界) */
export function paletteColor(index: number): string {
  return CHART_PALETTE[((index % CHART_PALETTE.length) + CHART_PALETTE.length) % CHART_PALETTE.length];
}

const AXIS_LINE_COLOR = 'rgba(148, 163, 184, 0.12)';
const AXIS_LABEL_COLOR = '#64748b';
const TEXT_COLOR = '#94a3b8';

const axisCommon = {
  axisLine: {
    lineStyle: { color: AXIS_LINE_COLOR },
  },
  axisTick: {
    show: false,
    lineStyle: { color: AXIS_LINE_COLOR },
  },
  axisLabel: {
    color: AXIS_LABEL_COLOR,
    fontSize: 10,
    fontFamily:
      'ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
  },
  splitLine: {
    show: true,
    lineStyle: {
      color: AXIS_LINE_COLOR,
      type: [3, 3] as number[],
      width: 1,
    },
  },
  splitArea: { show: false },
};

/** 暗色 tooltip 面板样式 (供组件内自定义 tooltip 时复用) */
export const TOOLTIP_STYLE = {
  backgroundColor: 'rgba(13, 17, 26, 0.94)',
  borderColor: 'rgba(148, 163, 184, 0.18)',
  borderWidth: 1,
  padding: [8, 10] as [number, number],
  textStyle: { color: '#e2e8f0', fontSize: 11 },
  extraCssText:
    'border-radius:6px;box-shadow:0 8px 24px rgba(0,0,0,0.45);backdrop-filter:blur(6px);',
};

export const echartsTerminalTheme: Record<string, unknown> = {
  color: CHART_PALETTE,
  backgroundColor: 'transparent',
  textStyle: {
    color: TEXT_COLOR,
    fontSize: 11,
  },

  animationDuration: 200,
  animationDurationUpdate: 200,
  animationEasing: 'cubicOut',
  animationEasingUpdate: 'cubicOut',

  categoryAxis: { ...axisCommon, splitLine: { ...axisCommon.splitLine, show: false } },
  valueAxis: axisCommon,
  timeAxis: { ...axisCommon, splitLine: { ...axisCommon.splitLine, show: false } },
  logAxis: axisCommon,

  grid: {
    left: 8,
    right: 12,
    top: 32,
    bottom: 8,
    containLabel: true,
  },

  legend: {
    textStyle: { color: TEXT_COLOR, fontSize: 11 },
    itemWidth: 12,
    itemHeight: 8,
    icon: 'roundRect',
  },

  tooltip: {
    ...TOOLTIP_STYLE,
    axisPointer: {
      lineStyle: { color: 'rgba(148, 163, 184, 0.3)', width: 1 },
      crossStyle: { color: 'rgba(148, 163, 184, 0.3)', width: 1 },
      shadowStyle: { color: 'rgba(148, 163, 184, 0.06)' },
    },
  },

  line: {
    lineStyle: { width: 1.5 },
    symbolSize: 4,
    smooth: false,
  },

  bar: {
    barMaxWidth: 24,
    itemStyle: { borderRadius: [2, 2, 0, 0] },
  },

  /* K线: 红涨绿跌 */
  candlestick: {
    itemStyle: {
      color: UP_COLOR,
      color0: DOWN_COLOR,
      borderColor: UP_COLOR,
      borderColor0: DOWN_COLOR,
    },
  },

  pie: {
    label: { color: TEXT_COLOR },
    labelLine: { lineStyle: { color: AXIS_LINE_COLOR } },
  },
};
