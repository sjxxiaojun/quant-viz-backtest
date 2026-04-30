import React from 'react';
import { cn } from '../utils';
import type { BacktestResult } from '../types';

interface TradeTableProps {
  result: BacktestResult;
}

export function TradeTable({ result }: TradeTableProps) {
  const visibleTrades = result.trades.slice(-500).reverse();
  const hiddenCount = Math.max(0, result.trades.length - visibleTrades.length);
  return (
    <div className="rounded-[2.5rem] p-8 backdrop-blur-xl animate-in fade-in duration-700" style={{ background: 'rgba(13, 27, 50, 0.4)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}>
      <h3 className="text-lg font-bold mb-6 flex items-center gap-3">
        <div className="w-2 h-6 bg-blue-500 rounded-full" />
        历史成交记录
      </h3>
      {hiddenCount > 0 && (
        <div className="mb-4 rounded-xl border border-blue-500/10 bg-blue-500/5 px-4 py-2 text-xs text-slate-400">
          当前仅展示最近 500 条成交，已折叠较早的 {hiddenCount} 条。
        </div>
      )}
      <div className="overflow-x-auto max-h-[400px] custom-scrollbar">
        <table className="w-full text-left border-separate border-spacing-y-2">
          <thead className="sticky top-0 z-10" style={{ background: '#0d1f3c' }}>
            <tr className="text-[10px] text-slate-500 uppercase tracking-[0.2em] font-black">
              <th className="pb-4 px-4">成交日期</th>
              <th className="pb-4 px-4">标的代码/名称</th>
              <th className="pb-4 px-4">类型</th>
              <th className="pb-4 px-4 text-right">价格</th>
              <th className="pb-4 px-4 text-right">成交/委托股数</th>
            </tr>
          </thead>
          <tbody className="text-sm">
            {visibleTrades.map((trade, i) => (
              <tr key={i} className="hover:bg-blue-500/5 transition-colors" style={{ background: 'rgba(13, 27, 50, 0.5)' }}>
                <td className="py-4 px-4 rounded-l-2xl text-slate-400 font-mono">{trade.date}</td>
                <td className="py-4 px-4">
                  <div className="flex flex-col">
                    <span className="font-bold text-blue-400">{trade.stock_name}</span>
                    <span className="text-[10px] text-slate-500 font-mono">{trade.stock_code}</span>
                  </div>
                </td>
                <td className="py-4 px-4">
                  <span className={cn(
                    "px-3 py-1 rounded-full text-[10px] font-black uppercase",
                    trade.side === 'buy'
                      ? "bg-rose-500/10 text-rose-500 border border-rose-500/20"
                      : trade.side === 'stop_loss'
                      ? "bg-yellow-500/10 text-yellow-400 border border-yellow-500/20"
                      : trade.side === 'take_profit'
                      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
                      : trade.side === 'circuit_break'
                      ? "bg-purple-500/10 text-purple-400 border border-purple-500/20"
                      : "bg-emerald-500/10 text-emerald-500 border border-emerald-500/20"
                  )}>
                    {trade.side === 'buy' ? '建仓买入'
                      : trade.side === 'stop_loss' ? '个股止损'
                      : trade.side === 'take_profit' ? '个股止盈'
                      : trade.side === 'circuit_break' ? '旧版熔断'
                      : '减仓卖出'}
                  </span>
                </td>
                <td className="py-4 px-4 font-mono text-slate-300 text-right">¥{trade.price.toFixed(2)}</td>
                <td className="py-4 px-4 rounded-r-2xl text-right">
                  <div className="font-mono text-slate-300">
                    {trade.fill_status === 'partial' && trade.requested_qty
                      ? `${trade.qty}/${trade.requested_qty}`
                      : trade.qty}
                  </div>
                  {trade.fill_status === 'partial' && (
                    <div className="mt-1 text-[10px] font-bold text-amber-300">部分</div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
