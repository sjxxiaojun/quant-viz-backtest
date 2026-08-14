import { Activity, Briefcase, TrendingDown, TrendingUp } from 'lucide-react';
import { changeToneClass, cn, formatNumber, formatPercent } from '../../utils';
import { EmptyState, Tag } from '../ui';
import type { Account } from './types';
import { formatAutomationTime } from './presenters';

interface AccountGridProps {
  accounts: Account[];
  onSelect: (account: Account) => void;
}

function AccountCard({
  account,
  rank,
  onSelect,
}: {
  account: Account;
  rank: number;
  onSelect: (account: Account) => void;
}) {
  const isIntraday = account.valuation_source === 'intraday_snapshot';
  const coverageText = `${Math.round((account.snapshot_coverage || 0) * 100)}%`;
  // return_rate 为百分数口径 (3.5 = +3.5%)
  const rateTone = changeToneClass(account.return_rate);
  const holdings = account.top_holding_details?.length
    ? account.top_holding_details.slice(0, 3)
    : account.top_holdings.map((code) => ({ symbol: code, name: code }));

  return (
    <button
      type="button"
      onClick={() => onSelect(account)}
      className="panel group relative w-full cursor-pointer p-4 text-left transition-colors hover:border-accent/40 hover:bg-bg2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      aria-label={`查看 ${account.name} 详情`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="num text-[10px] text-slate-500">#{rank}</span>
            <span className="truncate text-sm font-semibold text-slate-100">{account.name}</span>
          </div>
          <div className="num mt-0.5 text-[10px] uppercase tracking-wider text-slate-500">
            {account.strategy_id}
          </div>
        </div>
        {isIntraday && (
          <Tag tone="accent" title={`盘中估值 ${formatAutomationTime(account.valuation_time)}`}>
            <Activity className="h-2.5 w-2.5" />
            盘中 · 覆盖 {coverageText}
          </Tag>
        )}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-3">
        <div>
          <div className="label-caps">{isIntraday ? '盘中总值' : '账户总值'}</div>
          <div className="num mt-0.5 text-lg font-semibold text-slate-100">
            ¥{formatNumber(account.total_value, 0)}
          </div>
          {isIntraday && account.eod_total_value != null && (
            <div className="num text-[10px] text-slate-500">
              昨收 ¥{formatNumber(account.eod_total_value, 0)}
            </div>
          )}
        </div>
        <div>
          <div className="label-caps">{isIntraday ? '盘中回报' : '累计回报'}</div>
          <div className={cn('num mt-0.5 flex items-center gap-1 text-lg font-semibold', rateTone)}>
            {account.return_rate > 0 ? (
              <TrendingUp className="h-3.5 w-3.5" />
            ) : account.return_rate < 0 ? (
              <TrendingDown className="h-3.5 w-3.5" />
            ) : null}
            {formatPercent(account.return_rate, { from: 'percent', signed: true })}
          </div>
          {isIntraday && account.eod_return_rate != null && (
            <div className={cn('num text-[10px]', changeToneClass(account.eod_return_rate))}>
              昨收 {formatPercent(account.eod_return_rate, { from: 'percent', signed: true })}
            </div>
          )}
        </div>
      </div>

      <div className="mt-3 border-t border-line pt-2">
        <div className="flex items-center justify-between gap-2">
          <span className="label-caps">核心持仓</span>
          <span className="num text-[10px] text-slate-400">现金 ¥{formatNumber(account.cash, 0)}</span>
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1">
          {holdings.map((holding) => (
            <Tag key={holding.symbol}>
              {holding.name && holding.name !== holding.symbol ? holding.name : holding.symbol}
            </Tag>
          ))}
          {account.top_holdings.length === 0 && !account.top_holding_details?.length && (
            <span className="text-[10px] text-slate-500">当前空仓等待信号</span>
          )}
        </div>
      </div>
    </button>
  );
}

/** 策略账户卡片网格 (按收益排序); 卡片为原生 button, 可键盘打开详情 */
export function AccountGrid({ accounts, onSelect }: AccountGridProps) {
  if (!accounts.length) {
    return (
      <EmptyState
        icon={<Briefcase className="h-6 w-6" />}
        title="暂无仿真账户"
        description="运行一次仿真后，各策略账户与净值排行会显示在这里。"
      />
    );
  }
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      {accounts.map((account, index) => (
        <AccountCard key={account.strategy_id} account={account} rank={index + 1} onSelect={onSelect} />
      ))}
    </div>
  );
}
