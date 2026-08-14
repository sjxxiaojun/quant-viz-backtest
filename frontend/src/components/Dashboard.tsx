import { useMemo } from 'react';
import { LayoutDashboard } from 'lucide-react';
import { EChart } from './EChart';
import { EmptyState, Panel, SectionTitle, Tag } from './ui';
import { DOWN_COLOR, TOOLTIP_STYLE, UP_COLOR, paletteColor } from '../theme/echartsTheme';
import { escapeHtml, formatNumber, formatPercent } from '../utils';
import type { BacktestResult } from '../types';

interface DashboardProps {
  result: BacktestResult | null;
}

interface AxisTooltipPoint {
  marker?: string;
  name: string;
  seriesName?: string;
  value: number;
}

interface ItemTooltipPoint {
  name: string;
  value: number;
  percent?: number;
}

/**
 * 前端估算口径 (与后端 engine.py 对齐):
 * - 无风险利率 2.5%/年, 年化因子 252 交易日 (engine 默认 risk_free_rate=0.025, annualization_factor=252)
 * - 滚动窗口 60 个交易日
 * 后端未在 result 中返回逐日滚动夏普与月度收益序列, 此处由日收益率近似重算,
 * 与后端整段夏普可能存在小数位级差异, UI 以"前端估算"角标明示。
 */
const RISK_FREE_RATE = 0.025;
const TRADING_DAYS_PER_YEAR = 252;
const ROLLING_WINDOW = 60;

/** 图表卡片上的"前端估算"角标说明 */
const CLIENT_CALC_HINT =
  '该序列由前端根据日收益率近似重算（无风险利率 2.5%、年化 252 日），非后端绩效口径原值。';

function ClientCalcTag() {
  return (
    <Tag tone="warn" title={CLIENT_CALC_HINT}>
      前端估算
    </Tag>
  );
}

export function Dashboard({ result }: DashboardProps) {
  const drawdownChartOption = useMemo(() => {
    if (!result) return {};
    return {
      tooltip: {
        ...TOOLTIP_STYLE,
        trigger: 'axis',
        formatter: (params: AxisTooltipPoint[]) => {
          const p = params[0];
          return `${escapeHtml(p.name)}<br/>回撤: ${formatPercent(p.value)}`;
        },
      },
      xAxis: { type: 'category', data: result.history.map(h => h.date) },
      yAxis: {
        type: 'value',
        axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
      },
      series: [
        {
          name: '回撤',
          type: 'line',
          data: result.history.map(h => h.drawdown || 0),
          sampling: 'lttb',
          showSymbol: false,
          // A股语义: 回撤为亏损状态, 用绿色 (down)
          lineStyle: { color: DOWN_COLOR, width: 1.5 },
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

  const rollingSharpeChartOption = useMemo(() => {
    if (!result || result.history.length < ROLLING_WINDOW) return null;

    const dates: string[] = [];
    const sharpes: number[] = [];

    for (let i = ROLLING_WINDOW; i < result.history.length; i++) {
      const windowData = result.history.slice(i - ROLLING_WINDOW, i);
      const returns = windowData.map(h => h.returns || 0);
      const mean = returns.reduce((a, b) => a + b, 0) / ROLLING_WINDOW;
      const variance = returns.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / (ROLLING_WINDOW - 1);
      const std = Math.sqrt(variance);
      const sharpe = std === 0
        ? 0
        : ((mean - RISK_FREE_RATE / TRADING_DAYS_PER_YEAR) / std) * Math.sqrt(TRADING_DAYS_PER_YEAR);

      dates.push(result.history[i].date);
      sharpes.push(sharpe);
    }

    const lineColor = paletteColor(2);
    return {
      tooltip: {
        ...TOOLTIP_STYLE,
        trigger: 'axis',
        formatter: (params: AxisTooltipPoint[]) =>
          `${escapeHtml(params[0].name)}<br/>滚动夏普(${ROLLING_WINDOW}日): ${formatNumber(params[0].value)}`,
      },
      xAxis: { type: 'category', data: dates },
      yAxis: { type: 'value' },
      series: [
        {
          name: '滚动夏普',
          type: 'line',
          data: sharpes,
          sampling: 'lttb',
          showSymbol: false,
          lineStyle: { color: lineColor, width: 1.5 },
          itemStyle: { color: lineColor },
          areaStyle: {
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(167, 139, 250, 0.25)' },
                { offset: 1, color: 'rgba(167, 139, 250, 0)' },
              ],
            },
          },
        },
      ],
    };
  }, [result]);

  const monthlyReturnsChartOption = useMemo(() => {
    if (!result) return {};
    const months = Array.from(new Set(result.history.map(h => h.date.substring(0, 7)))).sort();

    const monthlyData = months.map(m => {
      const monthDays = result.history.filter(h => h.date.startsWith(m));
      if (monthDays.length === 0) return { month: m, ret: 0 };
      // 用当月首日净值 / (1 + 当日收益) 反推上月末净值, 属近似口径
      const start = monthDays[0].total_value / (1 + (monthDays[0].returns || 0));
      const end = monthDays[monthDays.length - 1].total_value;
      const ret = (end - start) / start;
      return { month: m, ret };
    });

    return {
      tooltip: {
        ...TOOLTIP_STYLE,
        formatter: (params: AxisTooltipPoint) =>
          `${escapeHtml(params.name)}<br/>收益: ${formatPercent(params.value)}`,
      },
      xAxis: { type: 'category', data: monthlyData.map(d => d.month) },
      yAxis: {
        type: 'value',
        axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
      },
      series: [
        {
          type: 'bar',
          data: monthlyData.map(d => ({
            value: d.ret,
            // A股语义: 红涨绿跌
            itemStyle: { color: d.ret >= 0 ? UP_COLOR : DOWN_COLOR },
          })),
          label: {
            show: true,
            position: 'top',
            formatter: (p: { value: number }) => `${(p.value * 100).toFixed(1)}%`,
            fontSize: 9,
          },
        },
      ],
    };
  }, [result]);

  if (!result) {
    return (
      <EmptyState
        icon={<LayoutDashboard className="h-8 w-8" />}
        title="暂无绩效数据"
        description="先到仿真控制台运行一次回测，这里会展示回撤、月度收益、滚动夏普与持仓集中度。"
      />
    );
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Panel>
          <SectionTitle>回撤水下曲线</SectionTitle>
          <div className="h-56">
            <EChart option={drawdownChartOption} style={{ height: '100%', width: '100%' }} />
          </div>
        </Panel>

        <Panel>
          <SectionTitle right={<ClientCalcTag />}>月度收益分布</SectionTitle>
          <div className="h-56">
            <EChart option={monthlyReturnsChartOption} style={{ height: '100%', width: '100%' }} />
          </div>
        </Panel>
      </div>

      <Panel>
        <SectionTitle right={<ClientCalcTag />}>滚动夏普比率 ({ROLLING_WINDOW}日)</SectionTitle>
        {rollingSharpeChartOption ? (
          <div className="h-56">
            <EChart option={rollingSharpeChartOption} style={{ height: '100%', width: '100%' }} />
          </div>
        ) : (
          <EmptyState
            className="h-56 border-0"
            title="样本不足"
            description={`回测区间不足 ${ROLLING_WINDOW} 个交易日，无法计算滚动夏普。`}
          />
        )}
      </Panel>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
        <Panel className="lg:col-span-1">
          <SectionTitle>当前持仓集中度</SectionTitle>
          <div className="h-56">
            {result.final_positions && result.final_positions.length > 0 ? (
              <EChart
                option={{
                  tooltip: {
                    ...TOOLTIP_STYLE,
                    trigger: 'item',
                    formatter: (point: ItemTooltipPoint) =>
                      `${escapeHtml(point.name)}: ${formatNumber(Number(point.value || 0), 0)} (${Number(point.percent || 0).toFixed(1)}%)`,
                  },
                  series: [{
                    type: 'pie',
                    radius: ['42%', '68%'],
                    avoidLabelOverlap: false,
                    itemStyle: {
                      borderRadius: 3,
                      borderColor: '#10141d',
                      borderWidth: 2,
                    },
                    label: { show: false },
                    data: result.final_positions.map(p => ({
                      value: p.market_value,
                      name: p.stock_name,
                    })),
                  }],
                }}
                style={{ height: '100%', width: '100%' }}
              />
            ) : (
              <EmptyState className="h-full border-0" title="暂无持仓数据" />
            )}
          </div>
        </Panel>

        <Panel className="flex flex-col overflow-hidden lg:col-span-2">
          <SectionTitle right={<span className="text-[10px] text-slate-600">仅展示个股止损/止盈</span>}>
            风控事件时间轴
          </SectionTitle>
          <div className="custom-scrollbar max-h-56 flex-1 space-y-2 overflow-y-auto pr-2">
            {(() => {
              const riskTrades = result.trades
                .filter(t => t.side === 'stop_loss' || t.side === 'take_profit' || t.side === 'circuit_break')
                .reverse();
              if (riskTrades.length === 0) {
                return <EmptyState className="border-0 py-6" title="回测期间未触发任何风控事件" />;
              }
              return riskTrades.map((t, i) => (
                <div key={`${t.date}-${t.stock_code}-${i}`} className="flex items-center gap-3 text-xs">
                  <span className="num shrink-0 text-slate-600">{t.date}</span>
                  {t.side === 'circuit_break' ? (
                    <Tag tone="warn">熔断</Tag>
                  ) : t.side === 'take_profit' ? (
                    <Tag tone="down">止盈</Tag>
                  ) : (
                    <Tag tone="down">止损</Tag>
                  )}
                  <span className="truncate text-slate-300">
                    {t.stock_name}
                    <span className="num ml-1 text-[10px] text-slate-600">{t.stock_code}</span>
                  </span>
                  <span className="num ml-auto shrink-0 text-slate-400">
                    {formatNumber(t.price)} × {formatNumber(t.qty, 0)}股
                  </span>
                </div>
              ));
            })()}
          </div>
        </Panel>
      </div>
    </div>
  );
}
