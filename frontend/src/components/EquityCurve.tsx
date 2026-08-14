import { useMemo } from 'react';
import { BarChart3 } from 'lucide-react';
import { EChart } from './EChart';
import { EmptyState, Panel, SectionTitle, Tag } from './ui';
import { DOWN_COLOR, TOOLTIP_STYLE, UP_COLOR, paletteColor } from '../theme/echartsTheme';
import { escapeHtml, formatNumber, formatPercent } from '../utils';
import type { BacktestResult, Trade } from '../types';

interface EquityCurveProps {
  result: BacktestResult | null;
}

interface AxisTooltipPoint {
  axisValue?: string;
  seriesName?: string;
  value: number;
}

const EQUITY_COLOR = paletteColor(0);
const BENCHMARK_COLOR = paletteColor(7);

export function EquityCurve({ result }: EquityCurveProps) {
  const chartOption = useMemo(() => {
    if (!result) return {};

    const dates = result.history.map(h => h.date);
    const values = result.history.map(h => h.total_value);
    const drawdowns = result.history.map(h => h.drawdown ?? 0);
    const valueByDate = new Map(result.history.map(h => [h.date, h.total_value]));
    const drawdownByDate = new Map(result.history.map(h => [h.date, h.drawdown ?? 0]));
    const tradeMarkers = result.trades
      .filter((trade) => valueByDate.has(trade.date))
      .slice(-200);
    const tradesByDate = new Map<string, Trade[]>();
    for (const day of result.history) {
      if (day.daily_trades?.length) {
        tradesByDate.set(day.date, day.daily_trades);
      }
    }

    const axisPointerLabelStyle = {
      axisPointer: { label: { show: false } },
    };

    return {
      tooltip: {
        ...TOOLTIP_STYLE,
        trigger: 'axis',
        formatter: (params: AxisTooltipPoint[]) => {
          if (!params.length) return '';
          const date = params[0].axisValue ?? '';
          const equity = valueByDate.get(date);
          const drawdown = drawdownByDate.get(date);
          const benchmarkPoint = params.find((p) => p.seriesName === '基准(沪深300)');
          const dailyTrades = tradesByDate.get(date) || [];
          const row = (label: string, value: string, color = '#e2e8f0') =>
            `<div style="display:flex;justify-content:space-between;gap:16px;">
              <span style="color:#64748b;">${label}</span>
              <span style="color:${color};font-family:ui-monospace,Menlo,monospace;">${value}</span>
            </div>`;
          let html = `<div style="min-width:180px;font-size:11px;line-height:1.7;">
            <div style="color:#64748b;font-family:ui-monospace,Menlo,monospace;margin-bottom:2px;">${escapeHtml(date)}</div>
            ${equity != null ? row('组合净值', `¥${formatNumber(equity, 0)}`) : ''}
            ${benchmarkPoint ? row('基准净值', `¥${formatNumber(Number(benchmarkPoint.value), 0)}`) : ''}
            ${drawdown != null ? row('回撤', formatPercent(drawdown), drawdown < 0 ? DOWN_COLOR : '#e2e8f0') : ''}`;
          if (dailyTrades.length > 0) {
            html += `<div style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(148,163,184,0.18);">
              <div style="color:#64748b;margin-bottom:2px;">今日交易</div>
              ${dailyTrades.map((t) => {
                const isBuy = t.side === 'buy';
                return row(
                  `${isBuy ? '买入' : '卖出'} ${escapeHtml(t.stock_name)}`,
                  `${escapeHtml(t.qty)}股`,
                  isBuy ? UP_COLOR : DOWN_COLOR,
                );
              }).join('')}
            </div>`;
          }
          return `${html}</div>`;
        },
      },
      axisPointer: { link: [{ xAxisIndex: 'all' }] },
      grid: [
        { left: 8, right: 12, top: 12, height: '58%', containLabel: true },
        { left: 8, right: 12, top: '76%', bottom: 4, containLabel: true },
      ],
      xAxis: [
        { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false }, ...axisPointerLabelStyle },
        { type: 'category', data: dates, gridIndex: 1 },
      ],
      yAxis: [
        { type: 'value', scale: true, gridIndex: 0 },
        {
          type: 'value',
          gridIndex: 1,
          axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
        },
      ],
      series: [
        {
          name: '组合净值',
          type: 'line',
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: values,
          sampling: 'lttb',
          progressive: 1000,
          showSymbol: false,
          lineStyle: { color: EQUITY_COLOR, width: 1.5 },
          itemStyle: { color: EQUITY_COLOR },
          areaStyle: {
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(91, 141, 239, 0.18)' },
                { offset: 1, color: 'rgba(91, 141, 239, 0)' },
              ],
            },
          },
          markPoint: {
            data: tradeMarkers.map(t => ({
              coord: [t.date, valueByDate.get(t.date) || 0],
              // A股动作色: 买入红 / 卖出绿
              itemStyle: { color: t.side === 'buy' ? UP_COLOR : DOWN_COLOR },
              symbol: 'triangle',
              symbolRotate: t.side === 'buy' ? 0 : 180,
              symbolSize: 8,
              label: { show: false },
            })),
          },
        },
        ...(result.benchmark_history && result.benchmark_history.length > 0
          ? [{
              name: '基准(沪深300)',
              type: 'line',
              xAxisIndex: 0,
              yAxisIndex: 0,
              data: result.benchmark_history.map(h => h.value * result.summary.initial_capital),
              sampling: 'lttb',
              progressive: 1000,
              showSymbol: false,
              lineStyle: { color: BENCHMARK_COLOR, width: 1, type: 'dashed' },
              itemStyle: { color: BENCHMARK_COLOR },
            }]
          : []),
        {
          name: '回撤',
          type: 'line',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: drawdowns,
          sampling: 'lttb',
          showSymbol: false,
          // A股语义: 回撤为亏损状态, 用绿色 (down)
          lineStyle: { color: DOWN_COLOR, width: 1 },
          itemStyle: { color: DOWN_COLOR },
          areaStyle: {
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(22, 163, 74, 0.05)' },
                { offset: 1, color: 'rgba(22, 163, 74, 0.35)' },
              ],
            },
          },
        },
      ],
    };
  }, [result]);

  return (
    <Panel className="h-[480px]">
      {result ? (
        <div className="flex h-full flex-col">
          <SectionTitle
            right={
              <div className="flex items-center gap-1.5">
                <Tag tone="accent">净值</Tag>
                <Tag tone="down">回撤</Tag>
                {result.benchmark_history && result.benchmark_history.length > 0 && <Tag>基准: 沪深300</Tag>}
              </div>
            }
          >
            权益曲线
          </SectionTitle>
          <EChart option={chartOption} style={{ flex: 1, minHeight: 0, width: '100%' }} />
        </div>
      ) : (
        <EmptyState
          className="h-full border-0"
          icon={<BarChart3 className="h-8 w-8" />}
          title="尚未运行回测"
          description="在左侧配置参数并启动仿真回测后，这里会展示组合净值、基准对比与回撤副图。"
        />
      )}
    </Panel>
  );
}
