import React from 'react';
import { TrendingUp, Wallet, Activity, Shield, AlertTriangle } from 'lucide-react';
import { cn } from '../utils';
import type { BacktestResult } from '../types';
import { colorMap } from '../config/strategies';

const poolLabelMap: Record<string, string> = {
  auto: '系统自动匹配',
  core: 'A股核心池 (Core 15)',
  blackhorse: 'A股弹性池 (Blackhorse 15)',
  etf: 'ETF 精选池',
  all: '本地全市场数据池',
};

interface KPICardsProps {
  result: BacktestResult | null;
}

export function KPICards({ result }: KPICardsProps) {
  const fmt = (v: number | undefined, suffix = '', decimals = 2) =>
    v !== undefined && !isNaN(v) ? v.toFixed(decimals) + suffix : '--';

  const kpis = [
    {
      title: "累计收益率",
      value: result ? fmt(result.total_return * 100, '%') : '--',
      sub: result ? `年化 ${fmt(result.summary.annual_return ? result.summary.annual_return * 100 : undefined, '%')}` : '',
      icon: TrendingUp,
      color: result && result.total_return >= 0 ? "rose" : "emerald",
      valueColor: result ? (result.total_return >= 0 ? "text-rose-500" : "text-emerald-500") : "text-white",
    },
    {
      title: "夏普比率",
      value: result ? fmt(result.summary.sharpe_ratio) : '--',
      sub: result ? `卡尔马 ${fmt(result.summary.calmar_ratio)}` : '',
      icon: Wallet,
      color: "blue",
      valueColor: result && result.summary.sharpe_ratio >= 1 ? "text-emerald-400" : result && result.summary.sharpe_ratio >= 0 ? "text-yellow-400" : "text-red-400",
    },
    {
      title: "最大回撤",
      value: result ? fmt(result.summary.max_drawdown * 100, '%') : '--',
      sub: result ? `胜率 ${fmt(result.summary.win_rate ? result.summary.win_rate * 100 : undefined, '%', 1)}` : '',
      icon: Shield,
      color: "emerald",
      valueColor: result && Math.abs(result.summary.max_drawdown) < 0.15 ? "text-emerald-400" : result && Math.abs(result.summary.max_drawdown) < 0.25 ? "text-yellow-400" : "text-red-400",
    },
    {
      title: "总交易次数",
      value: result ? String(result.summary.total_trades ?? '--') : '--',
      sub: result ? `盈亏比 ${fmt(result.summary.profit_loss_ratio)}` : '',
      icon: Activity,
      color: "indigo",
      valueColor: "text-white",
    },
  ];

  const hasMockData = result?.data_sources_used && Object.values(result.data_sources_used).includes("MOCK");
  const resolvedPool = result?.resolved_pool;
  const allPoolSelectionSummary = resolvedPool?.effective_pool === 'all' && resolvedPool.asset_class === 'a_share'
    ? {
        selected: resolvedPool.symbols_count,
        total: resolvedPool.local_universe_size ?? resolvedPool.symbols_before_budget,
        note: resolvedPool.sample_source_note,
        method: resolvedPool.method_cn,
      }
    : null;
  const sourceSummary = result?.data_sources_used
    ? Object.entries(
        Object.values(result.data_sources_used).reduce<Record<string, number>>((acc, source) => {
          acc[source] = (acc[source] || 0) + 1;
          return acc;
        }, {})
      )
    : [];

  return (
    <div className="space-y-4">
      {resolvedPool && (
        <div className="bg-cyan-500/10 border border-cyan-500/20 rounded-2xl p-4 space-y-2">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h4 className="text-sm font-bold text-cyan-300">本次数据路由</h4>
              <p className="text-xs text-cyan-100/80 mt-1">
                {resolvedPool.asset_class === 'etf' ? 'ETF 策略已命中 ETF 数据池。' : 'A股策略已命中 A股数据池。'}
              </p>
            </div>
            <div className="text-right text-[10px] text-slate-400">
              <div>请求参数: <span className="font-mono text-slate-200">{resolvedPool.requested_pool}</span></div>
              <div>实际池: <span className="font-mono text-slate-200">{poolLabelMap[resolvedPool.effective_pool] || resolvedPool.effective_pool}</span></div>
            </div>
          </div>
          <div className="flex flex-wrap gap-3 text-[10px] text-slate-400">
            <span>策略默认池: <span className="font-mono text-slate-200">{poolLabelMap[resolvedPool.strategy_pool] || resolvedPool.strategy_pool}</span></span>
            <span>资产类别: <span className="font-mono text-slate-200">{resolvedPool.asset_class}</span></span>
            {resolvedPool.symbols_count !== undefined && (
              <span>标的数量: <span className="font-mono text-slate-200">{resolvedPool.symbols_count}</span></span>
            )}
            {allPoolSelectionSummary?.selected !== undefined && allPoolSelectionSummary.total !== undefined && (
              <span>
                全A轻量预筛:
                <span className="font-mono text-slate-200">
                  {' '}{allPoolSelectionSummary.selected} / {allPoolSelectionSummary.total}
                </span>
              </span>
            )}
            {sourceSummary.length > 0 && (
              <span>
                数据源:
                <span className="font-mono text-slate-200">
                  {' '}{sourceSummary.map(([source, count]) => `${source}×${count}`).join(' / ')}
                </span>
              </span>
            )}
          </div>
          {allPoolSelectionSummary?.note && (
            <p className="text-[10px] leading-relaxed text-cyan-100/70">
              {allPoolSelectionSummary.method ? `${allPoolSelectionSummary.method}。` : ''}{allPoolSelectionSummary.note}
            </p>
          )}
        </div>
      )}
      {hasMockData && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-2xl p-4 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
          <div>
            <h4 className="text-sm font-bold text-amber-500">模拟数据警告</h4>
            <p className="text-xs text-amber-400/80 mt-1">
              本次回测包含自动生成的 MOCK 模拟数据，可能由于节假日休市或网络接口限流导致未能拉取到真实历史行情。回测结果可能偏向乐观，请勿作为实盘唯一依据。
            </p>
          </div>
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {kpis.map((kpi, i) => (
        <div key={i} className="rounded-3xl p-6 flex items-center gap-5 shadow-xl" style={{ background: 'rgba(13, 27, 50, 0.5)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.08)' }}>
          <div className={cn("p-4 rounded-2xl shrink-0", colorMap[kpi.color]?.textBg || 'bg-blue-500/10', colorMap[kpi.color]?.text || 'text-blue-400')}>
            <kpi.icon className="w-6 h-6" />
          </div>
          <div className="min-w-0">
            <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-0.5">{kpi.title}</p>
            <p className={cn("text-xl font-black", kpi.valueColor)}>
              {kpi.value}
            </p>
            {kpi.sub && (
              <p className="text-[10px] text-slate-500 mt-0.5">{kpi.sub}</p>
            )}
          </div>
        </div>
      ))}
      </div>
    </div>
  );
}
