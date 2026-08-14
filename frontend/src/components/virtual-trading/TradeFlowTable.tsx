import { ChevronLeft, ChevronRight, History } from 'lucide-react';
import { cn, formatNumber } from '../../utils';
import { EmptyState, Panel, Skeleton, Tag } from '../ui';
import type { VirtualTrade } from './types';

interface TradeFlowTableProps {
  trades: VirtualTrade[];
  page: number;
  pageSize: number;
  loading: boolean;
  onPageChange: (page: number) => void;
}

const HEADER_CELL = 'px-3 py-2 label-caps whitespace-nowrap';
const CELL = 'px-3 py-1.5 whitespace-nowrap';

/** 交易流水: 紧凑终端排版, 服务端 offset 分页 */
export function TradeFlowTable({ trades, page, pageSize, loading, onPageChange }: TradeFlowTableProps) {
  const hasPrev = page > 0;
  const hasNext = trades.length === pageSize;

  return (
    <Panel padded={false} className="overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2">
        <span className="label-caps">交易流水 · 全场调仓动态</span>
        <div className="flex items-center gap-1.5">
          <span className="num text-[10px] text-slate-500">
            第 {page + 1} 页 · {trades.length} 条
          </span>
          <button
            type="button"
            onClick={() => onPageChange(page - 1)}
            disabled={!hasPrev || loading}
            aria-label="上一页"
            className="rounded-ctl border border-line bg-bg2 p-1 text-slate-400 transition-colors hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            onClick={() => onPageChange(page + 1)}
            disabled={!hasNext || loading}
            aria-label="下一页"
            className="rounded-ctl border border-line bg-bg2 p-1 text-slate-400 transition-colors hover:text-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {loading ? (
        <div className="space-y-1.5 p-3">
          {Array.from({ length: 8 }, (_, i) => (
            <Skeleton key={i} className="h-6 w-full" />
          ))}
        </div>
      ) : trades.length ? (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-xs">
            <thead>
              <tr className="border-b border-line bg-bg2">
                <th className={HEADER_CELL}>日期</th>
                <th className={HEADER_CELL}>策略</th>
                <th className={HEADER_CELL}>标的</th>
                <th className={HEADER_CELL}>方向</th>
                <th className={cn(HEADER_CELL, 'text-right')}>价格</th>
                <th className={cn(HEADER_CELL, 'text-right')}>股数</th>
                <th className={cn(HEADER_CELL, 'text-right')}>费用</th>
                <th className={HEADER_CELL}>备注</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {trades.map((trade) => (
                <tr key={trade.id} className="transition-colors hover:bg-bg2">
                  <td className={cn(CELL, 'num text-slate-400')}>{trade.date}</td>
                  <td className={cn(CELL, 'font-medium text-accent')}>{trade.strategy_id}</td>
                  <td className={cn(CELL, 'num font-medium text-slate-100')}>{trade.symbol}</td>
                  <td className={CELL}>
                    {/* A股动作语义: 买入红 / 卖出绿 */}
                    <Tag tone={trade.side === 'BUY' ? 'up' : 'down'}>
                      {trade.side === 'BUY' ? '买入' : '卖出'}
                    </Tag>
                  </td>
                  <td className={cn(CELL, 'num text-right text-slate-200')}>
                    ¥{formatNumber(trade.price)}
                  </td>
                  <td className={cn(CELL, 'num text-right text-slate-200')}>
                    {formatNumber(trade.shares, 0)}
                  </td>
                  <td className={cn(CELL, 'num text-right text-slate-400')}>
                    {formatNumber(trade.fee)}
                  </td>
                  <td className={cn(CELL, 'max-w-[280px] truncate text-[11px] text-slate-500')} title={trade.msg}>
                    {trade.msg}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          icon={<History className="h-6 w-6" />}
          title={page === 0 ? '暂无交易记录' : '没有更多流水'}
          description={page === 0 ? '等待第一个信号触发后，调仓流水会实时出现在这里。' : '已经翻到最后一页。'}
          className="m-3 border-0"
        />
      )}
    </Panel>
  );
}
