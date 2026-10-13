import { useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn, formatAmountCN, formatNumber } from '../utils';
import { EmptyState, Panel, SectionTitle } from './ui';
import type { BacktestResult } from '../types';

interface TradeTableProps {
  result: BacktestResult;
}

const PAGE_SIZE = 50;

const SIDE_META: Record<string, { label: string; className: string }> = {
  // A股动作色: 买入红 / 卖出绿; 止损止盈本质是卖出, 保持绿色, 熔断标警示色
  buy: { label: '买入', className: 'border-buy/30 bg-buy/10 text-up-soft' },
  sell: { label: '卖出', className: 'border-sell/30 bg-sell/10 text-down-soft' },
  stop_loss: { label: '止损', className: 'border-sell/30 bg-sell/10 text-down-soft' },
  take_profit: { label: '止盈', className: 'border-sell/30 bg-sell/10 text-down-soft' },
  circuit_break: { label: '熔断', className: 'border-warn/30 bg-warn/10 text-warn' },
};

function sideMeta(side: string) {
  return SIDE_META[side] ?? { label: '卖出', className: SIDE_META.sell.className };
}

export function TradeTable({ result }: TradeTableProps) {
  const [page, setPage] = useState(0);

  const trades = useMemo(() => [...result.trades].reverse(), [result.trades]);
  const totalPages = Math.max(1, Math.ceil(trades.length / PAGE_SIZE));
  const currentPage = Math.min(page, totalPages - 1);
  const pageTrades = trades.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);

  const pager = (
    <div className="flex items-center gap-1.5">
      <span className="num text-[10px] text-slate-500">
        {trades.length === 0 ? '0' : `${currentPage * PAGE_SIZE + 1}-${currentPage * PAGE_SIZE + pageTrades.length}`} / {trades.length}
      </span>
      <button
        type="button"
        aria-label="上一页"
        disabled={currentPage === 0}
        onClick={() => setPage(currentPage - 1)}
        className="rounded-ctl border border-line p-1 text-slate-400 transition-colors hover:bg-bg3 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-30"
      >
        <ChevronLeft className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        aria-label="下一页"
        disabled={currentPage >= totalPages - 1}
        onClick={() => setPage(currentPage + 1)}
        className="rounded-ctl border border-line p-1 text-slate-400 transition-colors hover:bg-bg3 hover:text-slate-200 disabled:cursor-not-allowed disabled:opacity-30"
      >
        <ChevronRight className="h-3.5 w-3.5" />
      </button>
    </div>
  );

  return (
    <Panel padded={false} className="p-3">
      <SectionTitle right={pager}>历史成交记录</SectionTitle>
      {result.trades_truncated && <p className="text-amber-300">旧结果仅包含部分成交，请重新运行获取完整流水。</p>}
      <button className="my-2 text-xs text-blue-300" onClick={() => {
        const lines = ['date,stock_code,side,price,qty', ...result.trades.map(t => [t.date,t.stock_code,t.side,t.price,t.qty].join(','))];
        const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' }));
        const link = document.createElement('a'); link.href = url; link.download = 'backtest-trades.csv'; link.click(); URL.revokeObjectURL(url);
      }}>导出完整成交（{result.trades_total ?? trades.length}笔）</button>
      {trades.length === 0 ? (
        <EmptyState title="回测期间没有产生任何成交" className="border-0 py-6" />
      ) : (
        <div className="custom-scrollbar max-h-[420px] overflow-auto">
          <table className="w-full border-collapse text-xs">
            <thead className="sticky top-0 z-10 bg-bg1">
              <tr className="border-b border-line-strong text-left">
                <th className="label-caps py-1.5 pr-3 font-semibold">日期</th>
                <th className="label-caps py-1.5 pr-3 font-semibold">标的</th>
                <th className="label-caps py-1.5 pr-3 font-semibold">方向</th>
                <th className="label-caps py-1.5 pr-3 text-right font-semibold">价格</th>
                <th className="label-caps py-1.5 pr-3 text-right font-semibold">股数</th>
                <th className="label-caps py-1.5 text-right font-semibold">成交额</th>
              </tr>
            </thead>
            <tbody>
              {pageTrades.map((trade, i) => {
                const meta = sideMeta(trade.side);
                return (
                  <tr
                    key={`${trade.date}-${trade.stock_code}-${trade.side}-${i}`}
                    className="h-8 border-b border-line transition-colors last:border-0 hover:bg-bg2"
                  >
                    <td className="num whitespace-nowrap py-1 pr-3 text-slate-500">{trade.date}</td>
                    <td className="whitespace-nowrap py-1 pr-3">
                      <span className="font-medium text-slate-200">{trade.stock_name}</span>
                      <span className="num ml-1.5 text-[10px] text-slate-600">{trade.stock_code}</span>
                    </td>
                    <td className="whitespace-nowrap py-1 pr-3">
                      <span
                        className={cn(
                          'inline-flex items-center rounded-ctl border px-1.5 py-0.5 text-[10px] font-medium leading-none',
                          meta.className,
                        )}
                      >
                        {meta.label}
                      </span>
                    </td>
                    <td className="num whitespace-nowrap py-1 pr-3 text-right text-slate-300">
                      {formatNumber(trade.price)}
                    </td>
                    <td className="num whitespace-nowrap py-1 pr-3 text-right text-slate-300">
                      {trade.fill_status === 'partial' && trade.requested_qty ? (
                        <span title={`委托 ${trade.requested_qty} 股，部分成交`}>
                          {formatNumber(trade.qty, 0)}
                          <span className="text-slate-600">/{formatNumber(trade.requested_qty, 0)}</span>
                          <span className="ml-1 text-[9px] font-semibold text-warn">部分</span>
                        </span>
                      ) : (
                        formatNumber(trade.qty, 0)
                      )}
                    </td>
                    <td className="num whitespace-nowrap py-1 text-right text-slate-400">
                      {formatAmountCN(trade.price * trade.qty)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
