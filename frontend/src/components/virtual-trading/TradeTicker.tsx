import { Zap } from 'lucide-react';
import { cn, formatNumber } from '../../utils';
import type { VirtualTrade } from './types';

interface TradeTickerProps {
  trades: VirtualTrade[];
}

function TickerItem({ trade }: { trade: VirtualTrade }) {
  const isBuy = trade.side === 'BUY';
  return (
    <div className="flex items-center gap-2 border-r border-line px-5">
      <span className="num text-[10px] text-slate-500">{trade.date}</span>
      <span className="text-[10px] font-semibold text-accent">{trade.strategy_id}</span>
      {/* A股动作语义: 买入红 / 卖出绿 */}
      <span className={cn('text-[10px] font-semibold', isBuy ? 'text-up' : 'text-down')}>
        {isBuy ? '买入' : '卖出'} {trade.symbol}
      </span>
      <span className="num text-[10px] text-slate-300">¥{formatNumber(trade.price)}</span>
    </div>
  );
}

/** 顶部调仓记录跑马灯: 同一数组渲染两遍实现无缝滚动 */
export function TradeTicker({ trades }: TradeTickerProps) {
  if (!trades.length) return null;
  return (
    <div className="relative flex h-8 items-center overflow-hidden border-y border-line bg-bg1">
      <div className="z-10 flex h-full items-center gap-1.5 bg-bg2 px-3">
        <Zap className="h-3 w-3 text-accent" />
        <span className="label-caps whitespace-nowrap text-slate-300">调仓记录</span>
      </div>
      <div className="vt-marquee flex whitespace-nowrap">
        {[0, 1].map((copy) =>
          trades.map((trade) => <TickerItem key={`${copy}-${trade.id}`} trade={trade} />),
        )}
      </div>
      {/* marquee 关键帧仅本组件使用, 作用域限定于 .vt-marquee, 不覆写全局类 */}
      <style>{`
        @keyframes vt-marquee {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
        .vt-marquee {
          animation: vt-marquee 40s linear infinite;
        }
        .vt-marquee:hover {
          animation-play-state: paused;
        }
      `}</style>
    </div>
  );
}
