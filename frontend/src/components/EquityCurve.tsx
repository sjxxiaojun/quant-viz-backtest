import React, { useMemo } from 'react';
import { EChart } from './EChart';
import { BarChart3 } from 'lucide-react';
import type { BacktestResult, Trade } from '../types';
import { escapeHtml } from '../utils';

interface EquityCurveProps {
  result: BacktestResult | null;
}

interface AxisTooltipPoint {
  name: string;
  value: number;
}

export function EquityCurve({ result }: EquityCurveProps) {
  const chartOption = useMemo(() => {
    if (!result) return {};

    const dates = result.history.map(h => h.date);
    const values = result.history.map(h => h.total_value);
    const valueByDate = new Map(result.history.map(h => [h.date, h.total_value]));
    const tradeMarkers = result.trades
      .filter((trade) => valueByDate.has(trade.date))
      .slice(-200);
    const tradesByDate = new Map<string, Trade[]>();
    for (const day of result.history) {
      if (day.daily_trades?.length) {
        tradesByDate.set(day.date, day.daily_trades);
      }
    }

    return {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(10, 22, 40, 0.95)',
        borderColor: '#3b82f6',
        borderWidth: 1,
        textStyle: { color: '#f1f5f9', fontSize: 12 },
        formatter: (params: AxisTooltipPoint[]) => {
          const p = params[0];
          const dailyTrades = tradesByDate.get(p.name) || [];
          let tradesHtml = '';
          if (dailyTrades.length > 0) {
            tradesHtml = `<div class="mt-2 pt-2 border-t border-slate-700">
              <div class="text-[10px] text-slate-500 uppercase font-black mb-1 text-white/40">今日交易</div>
              ${dailyTrades.map((t) => `
                <div class="flex justify-between items-center gap-4 text-[11px] mb-1">
                  <span class="${t.side === 'buy' ? 'text-rose-400' : 'text-emerald-400'} font-bold">
                    [${t.side === 'buy' ? '买入' : '卖出'}] ${escapeHtml(t.stock_name)}
                  </span>
                  <span class="text-slate-400 font-mono">${escapeHtml(t.qty)}股</span>
                </div>
              `).join('')}
            </div>`;
          }
          return `<div class="p-2 min-w-[180px]">
            <div class="text-slate-400 text-[10px] mb-1 font-mono">${escapeHtml(p.name)}</div>
            <div class="flex justify-between items-end">
              <span class="text-slate-500 text-[10px]">组合净值</span>
              <span class="text-lg font-black text-white">${escapeHtml(p.value.toLocaleString('zh-CN', { style: 'currency', currency: 'CNY' }))}</span>
            </div>
            ${tradesHtml}
          </div>`;
        }
      },
      grid: { left: '4%', right: '4%', bottom: '5%', top: '5%', containLabel: true },
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
      series: [
        {
          name: '组合净值',
          type: 'line',
          data: values,
          smooth: 0.4,
          sampling: 'lttb',
          progressive: 1000,
          showSymbol: false,
          lineStyle: { color: '#3b82f6', width: 4, shadowBlur: 10, shadowColor: 'rgba(59, 130, 246, 0.3)' },
          areaStyle: {
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(59, 130, 246, 0.2)' },
                { offset: 1, color: 'rgba(59, 130, 246, 0)' }
              ]
            }
          },
          markPoint: {
            data: tradeMarkers.map(t => ({
              coord: [t.date, valueByDate.get(t.date) || 0],
              value: t.side === 'buy' ? 'B' : 'S',
              itemStyle: { color: t.side === 'buy' ? '#ef4444' : '#10b981' },
              symbol: 'triangle',
              symbolRotate: t.side === 'buy' ? 0 : 180,
              symbolSize: 10,
              label: { show: false }
            }))
          }
        },
        result.benchmark_history && result.benchmark_history.length > 0 ? {
          name: '基准(沪深300)',
          type: 'line',
          data: result.benchmark_history.map(h => h.value * result.summary.initial_capital),
          smooth: 0.4,
          sampling: 'lttb',
          progressive: 1000,
          showSymbol: false,
          lineStyle: { color: '#94a3b8', width: 2, type: 'dashed' },
        } : null
      ].filter(Boolean)
    };
  }, [result]);

  return (
    <div className="rounded-[2.5rem] p-8 backdrop-blur-xl shadow-2xl h-[500px] relative" style={{ background: 'rgba(13, 27, 50, 0.5)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}>
      {result ? (
        <EChart option={chartOption} style={{ height: '100%', width: '100%' }} />
      ) : (
        <div className="h-full flex flex-col items-center justify-center text-slate-600 space-y-4">
          <BarChart3 className="w-16 h-16 opacity-10 animate-bounce" />
          <p className="text-xs tracking-widest uppercase opacity-50">Preparing Simulation Engine...</p>
        </div>
      )}
    </div>
  );
}
