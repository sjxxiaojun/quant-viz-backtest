import React, { useMemo } from 'react';
import { EChart } from './EChart';
import type { BacktestResult } from '../types';
import { escapeHtml } from '../utils';

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

export function Dashboard({ result }: DashboardProps) {
  const drawdownChartOption = useMemo(() => {
    if (!result) return {};
    return {
      backgroundColor: 'transparent',
      tooltip: {
	        trigger: 'axis',
	        formatter: (params: AxisTooltipPoint[]) => {
	          const p = params[0];
	          return `${escapeHtml(p.name)}<br/>回撤: ${(p.value * 100).toFixed(2)}%`;
	        }
      },
      grid: { left: '4%', right: '4%', bottom: '5%', top: '10%', containLabel: true },
      xAxis: {
        type: 'category',
        data: result.history.map(h => h.date),
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8' }
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisLabel: { color: '#94a3b8', formatter: (v: number) => (v * 100).toFixed(0) + '%' },
        splitLine: { lineStyle: { color: '#0d2244', type: 'dashed' } }
      },
      series: [
        {
          name: 'Drawdown',
          type: 'line',
          data: result.history.map(h => h.drawdown || 0),
          smooth: true,
          showSymbol: false,
          lineStyle: { color: '#ef4444', width: 2 },
          areaStyle: {
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(239, 68, 68, 0.4)' },
                { offset: 1, color: 'rgba(239, 68, 68, 0.05)' }
              ]
            }
          }
        }
      ]
    };
  }, [result]);

  const rollingSharpeChartOption = useMemo(() => {
    if (!result || result.history.length < 60) return {};
    
    const windowSize = 60;
    const dates: string[] = [];
    const sharpes: number[] = [];
    
    for (let i = windowSize; i < result.history.length; i++) {
      const windowData = result.history.slice(i - windowSize, i);
      const returns = windowData.map(h => h.returns || 0);
      const mean = returns.reduce((a, b) => a + b, 0) / windowSize;
      const variance = returns.reduce((a, b) => a + Math.pow(b - mean, 2), 0) / (windowSize - 1);
      const std = Math.sqrt(variance);
      const sharpe = std === 0 ? 0 : ((mean - 0.025 / 252) / std) * Math.sqrt(252);
      
      dates.push(result.history[i].date);
      sharpes.push(sharpe);
    }

    return {
      backgroundColor: 'transparent',
	      tooltip: {
	        trigger: 'axis',
	        formatter: (params: AxisTooltipPoint[]) => `${escapeHtml(params[0].name)}<br/>滚动夏普(60日): ${params[0].value.toFixed(2)}`
	      },
      grid: { left: '4%', right: '4%', bottom: '5%', top: '10%', containLabel: true },
      xAxis: {
        type: 'category',
        data: dates,
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8' }
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisLabel: { color: '#94a3b8' },
        splitLine: { lineStyle: { color: '#0d2244', type: 'dashed' } }
      },
      series: [
        {
          name: 'Rolling Sharpe',
          type: 'line',
          data: sharpes,
          smooth: true,
          showSymbol: false,
          lineStyle: { color: '#8b5cf6', width: 2 },
          areaStyle: {
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(139, 92, 246, 0.4)' },
                { offset: 1, color: 'rgba(139, 92, 246, 0.05)' }
              ]
            }
          }
        }
      ]
    };
  }, [result]);

  const monthlyReturnsChartOption = useMemo(() => {
    if (!result) return {};
    const months = Array.from(new Set(result.history.map(h => h.date.substring(0, 7)))).sort();
    
    const monthlyData = months.map(m => {
      const monthDays = result.history.filter(h => h.date.startsWith(m));
      if (monthDays.length === 0) return { month: m, ret: 0 };
      const start = monthDays[0].total_value / (1 + (monthDays[0].returns || 0)); // approximate previous day close
      const end = monthDays[monthDays.length - 1].total_value;
      const ret = (end - start) / start;
      return { month: m, ret };
    });

    return {
      backgroundColor: 'transparent',
	      tooltip: {
	        formatter: (params: AxisTooltipPoint) => `${escapeHtml(params.name)}<br/>收益: ${(params.value * 100).toFixed(2)}%`
	      },
      grid: { left: '4%', right: '4%', bottom: '5%', top: '10%', containLabel: true },
      xAxis: {
        type: 'category',
        data: monthlyData.map(d => d.month),
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8' }
      },
      yAxis: {
        type: 'value',
        axisLine: { show: false },
        axisLabel: { color: '#94a3b8', formatter: (v: number) => (v * 100).toFixed(0) + '%' },
        splitLine: { lineStyle: { color: '#0d2244', type: 'dashed' } }
      },
      series: [
        {
          type: 'bar',
          data: monthlyData.map(d => ({
            value: d.ret,
            itemStyle: { color: d.ret >= 0 ? '#10b981' : '#ef4444' } // Emerald for positive, Rose for negative
          })),
          label: {
            show: true,
            position: 'top',
            formatter: (p: { value: number }) => (p.value * 100).toFixed(1) + '%',
            color: '#94a3b8',
            fontSize: 10
          }
        }
      ]
    };
  }, [result]);

  if (!result) {
    return (
      <div className="flex items-center justify-center h-64 rounded-3xl text-slate-500" style={{ background: 'rgba(13, 27, 50, 0.4)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}>
        请先运行回测以查看绩效仪表盘
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      {/* Top Row: Drawdown and Monthly Returns */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div className="rounded-3xl p-6 backdrop-blur-xl shadow-2xl" style={{ background: 'rgba(13, 27, 50, 0.5)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}>
          <h3 className="text-sm font-bold text-slate-400 mb-4 tracking-widest uppercase">回撤水下曲线</h3>
          <div className="h-64">
            <EChart option={drawdownChartOption} style={{ height: '100%', width: '100%' }} />
          </div>
        </div>

        <div className="rounded-3xl p-6 backdrop-blur-xl shadow-2xl" style={{ background: 'rgba(13, 27, 50, 0.5)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}>
          <h3 className="text-sm font-bold text-slate-400 mb-4 tracking-widest uppercase">月度收益分布</h3>
          <div className="h-64">
            <EChart option={monthlyReturnsChartOption} style={{ height: '100%', width: '100%' }} />
          </div>
        </div>
      </div>

      {/* Middle Row: Rolling Sharpe */}
      <div className="rounded-3xl p-6 backdrop-blur-xl shadow-2xl" style={{ background: 'rgba(13, 27, 50, 0.5)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}>
        <h3 className="text-sm font-bold text-slate-400 mb-4 tracking-widest uppercase">滚动夏普比率 (60日)</h3>
        <div className="h-64">
          <EChart option={rollingSharpeChartOption} style={{ height: '100%', width: '100%' }} />
        </div>
      </div>

      {/* Bottom Row: Positions Pie Chart and Risk Timeline */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-1 rounded-3xl p-6 backdrop-blur-xl shadow-2xl" style={{ background: 'rgba(13, 27, 50, 0.5)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}>
          <h3 className="text-sm font-bold text-slate-400 mb-4 tracking-widest uppercase">当前持仓集中度</h3>
          <div className="h-64">
            {result.final_positions && result.final_positions.length > 0 ? (
              <EChart option={{
                backgroundColor: 'transparent',
                tooltip: {
                  trigger: 'item',
                  formatter: (point: ItemTooltipPoint) =>
                    `${escapeHtml(point.name)}: ${Number(point.value || 0).toLocaleString('zh-CN')} (${Number(point.percent || 0).toFixed(1)}%)`,
                },
                series: [{
                  type: 'pie',
                  radius: ['40%', '70%'],
                  avoidLabelOverlap: false,
                  itemStyle: {
                    borderRadius: 10,
                    borderColor: '#0d1f3c',
                    borderWidth: 2
                  },
                  label: { show: false },
                  data: result.final_positions.map(p => ({
                    value: p.market_value,
                    name: p.stock_name
                  }))
                }]
              }} style={{ height: '100%', width: '100%' }} />
            ) : (
              <div className="flex items-center justify-center h-full text-slate-500 text-sm">暂无持仓数据</div>
            )}
          </div>
        </div>

        <div className="lg:col-span-2 rounded-3xl p-6 backdrop-blur-xl shadow-2xl overflow-hidden flex flex-col" style={{ background: 'rgba(13, 27, 50, 0.5)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}>
          <h3 className="text-sm font-bold text-slate-400 mb-4 tracking-widest uppercase flex justify-between items-center">
            <span>风控事件时间轴</span>
            <span className="text-xs font-normal text-rose-400">仅展示个股止损/止盈</span>
          </h3>
          <div className="flex-1 overflow-y-auto pr-2 space-y-3 custom-scrollbar">
            {(() => {
              const riskTrades = result.trades.filter(t => t.side === 'stop_loss' || t.side === 'take_profit' || t.side === 'circuit_break').reverse();
              if (riskTrades.length === 0) {
                return <div className="text-slate-500 text-sm text-center py-8">回测期间未触发任何风控事件</div>;
              }
              return riskTrades.map((t, i) => (
                <div key={i} className="flex gap-4 items-start">
                  <div className="flex flex-col items-center">
                    <div className="w-2 h-2 rounded-full bg-rose-500 mt-1.5 shadow-[0_0_8px_rgba(244,63,94,0.6)]"></div>
                    {i !== riskTrades.length - 1 && <div className="w-0.5 h-full bg-slate-700/50 my-1"></div>}
                  </div>
                  <div className="pb-4">
                    <div className="text-xs text-slate-500 font-mono mb-1">{t.date}</div>
                    <div className="text-sm text-slate-300">
                      {t.side === 'circuit_break' ? (
                        <span className="text-purple-400 font-bold mr-2">[旧版组合熔断]</span>
                      ) : t.side === 'take_profit' ? (
                        <span className="text-emerald-400 font-bold mr-2">[个股止盈]</span>
                      ) : (
                        <span className="text-rose-400 font-bold mr-2">[个股止损]</span>
                      )}
                      {t.stock_name} ({t.stock_code}) 以 {t.price.toFixed(2)} 价格退出 {t.qty} 股
                    </div>
                  </div>
                </div>
              ));
            })()}
          </div>
        </div>
      </div>
    </div>
  );
}
