import { useEffect, useMemo, useRef } from 'react';
import { Target, X } from 'lucide-react';
import type { EChartsCoreOption } from 'echarts/core';
import { EChart } from '../EChart';
import { changeToneClass, cn, formatNumber, formatPercent } from '../../utils';
import { paletteColor, TOOLTIP_STYLE } from '../../theme/echartsTheme';
import { Panel, SectionTitle, Skeleton, Stat } from '../ui';
import type { Account, EquityPoint, PerformanceStats } from './types';

interface StrategyDetailModalProps {
  account: Account;
  equityHistory: EquityPoint[];
  stats: PerformanceStats | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}

/** 策略详情弹窗: Esc 关闭, aria-modal, 打开时聚焦关闭按钮并在关闭后归还焦点 */
export function StrategyDetailModal({
  account,
  equityHistory,
  stats,
  loading,
  error,
  onClose,
}: StrategyDetailModalProps) {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previouslyFocused?.focus?.();
    };
  }, [onClose]);

  const lineColor = paletteColor(0);
  const equityOption = useMemo<EChartsCoreOption>(() => {
    if (!equityHistory.length) return {};
    return {
      backgroundColor: 'transparent',
      grid: { top: 16, right: 12, bottom: 8, left: 8, containLabel: true },
      tooltip: { trigger: 'axis', ...TOOLTIP_STYLE },
      xAxis: {
        type: 'category',
        data: equityHistory.map((point) => point.date),
        axisLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.12)' } },
        axisLabel: { color: '#64748b', fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLine: { show: false },
        axisLabel: { color: '#64748b', fontSize: 10 },
        splitLine: { lineStyle: { color: 'rgba(148, 163, 184, 0.12)', type: [3, 3] } },
      },
      series: [
        {
          data: equityHistory.map((point) => point.total_value),
          type: 'line',
          smooth: true,
          showSymbol: false,
          lineStyle: { color: lineColor, width: 1.5 },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(91, 141, 239, 0.18)' },
                { offset: 1, color: 'rgba(91, 141, 239, 0)' },
              ],
            },
          },
        },
      ],
    };
  }, [equityHistory, lineColor]);

  const holdings = account.top_holding_details ?? [];
  const isIntraday = account.valuation_source === 'intraday_snapshot';

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg0/70 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${account.name} 详情`}
        onClick={(event) => event.stopPropagation()}
        className="flex h-full max-h-[88vh] w-full max-w-4xl flex-col overflow-hidden rounded-panel border border-line bg-bg1 shadow-panel"
      >
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-line bg-bg2 px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-ctl border border-accent/30 bg-accent/10 text-accent">
              <Target className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-100">{account.name} · 详情报告</h3>
              <p className="num text-[10px] uppercase tracking-wider text-slate-500">{account.strategy_id}</p>
            </div>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="关闭详情弹窗"
            className="rounded-ctl p-2 text-slate-400 transition-colors hover:bg-bg3 hover:text-slate-100 focus-visible:outline-2 focus-visible:outline-accent"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="custom-scrollbar flex-1 space-y-4 overflow-y-auto p-4">
          {/* 核心指标 */}
          <Panel level={2} className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Stat
              label="累计收益"
              value={formatPercent(account.return_rate, { from: 'percent', signed: true })}
              delta={account.return_rate}
              toneByDelta
            />
            <Stat label="夏普比率" value={stats ? formatNumber(stats.sharpe_ratio) : '--'} />
            <Stat
              label="最大回撤"
              value={stats ? formatPercent(stats.max_drawdown, { from: 'percent' }) : '--'}
            />
            <Stat
              label="年化收益"
              value={stats ? formatPercent(stats.annualized_return, { from: 'percent', signed: true }) : '--'}
              delta={stats?.annualized_return}
              toneByDelta
            />
            <Stat
              label="胜率"
              value={stats ? formatPercent(stats.win_rate, { from: 'percent', digits: 1 }) : '--'}
            />
            <Stat
              label="波动率"
              value={stats ? formatPercent(stats.volatility, { from: 'percent', digits: 1 }) : '--'}
            />
          </Panel>

          {/* 净值曲线 */}
          <div>
            <SectionTitle>历史净值曲线</SectionTitle>
            <Panel level={2} padded={false} className="h-[300px] w-full p-2">
              {loading ? (
                <div className="flex h-full flex-col justify-center gap-2 p-4">
                  <Skeleton className="h-3 w-1/3" />
                  <Skeleton className="h-40 w-full" />
                </div>
              ) : equityHistory.length > 0 ? (
                <EChart option={equityOption} style={{ height: '100%', width: '100%' }} />
              ) : (
                <div className="flex h-full items-center justify-center text-xs text-slate-500">
                  暂无足够的历史净值数据，请先执行今日模拟同步数据。
                </div>
              )}
            </Panel>
          </div>

          {/* 当前持仓 */}
          <div>
            <SectionTitle>当前仓位详情</SectionTitle>
            {error && (
              <div className="mb-2 rounded-ctl border border-up/30 bg-up/10 px-3 py-2 text-xs text-up-soft">
                {error}
              </div>
            )}
            {holdings.length > 0 ? (
              <Panel level={2} padded={false} className="overflow-hidden">
                <table className="w-full border-collapse text-left text-xs">
                  <thead>
                    <tr className="border-b border-line bg-bg3/50">
                      <th className="label-caps px-3 py-2">标的</th>
                      <th className="label-caps px-3 py-2 text-right">持仓股数</th>
                      <th className="label-caps px-3 py-2 text-right">现价</th>
                      <th className="label-caps px-3 py-2 text-right">成本</th>
                      <th className="label-caps px-3 py-2 text-right">浮动盈亏</th>
                      <th className="label-caps px-3 py-2 text-right">占比</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {holdings.map((holding) => {
                      const pnlRatio =
                        holding.cost_price > 0
                          ? (holding.current_price - holding.cost_price) / holding.cost_price
                          : null;
                      return (
                        <tr key={holding.symbol} className="transition-colors hover:bg-bg3/40">
                          <td className="px-3 py-1.5">
                            <div className="font-medium text-slate-100">
                              {holding.name && holding.name !== holding.symbol ? holding.name : holding.symbol}
                            </div>
                            <div className="num text-[10px] text-slate-500">{holding.symbol}</div>
                          </td>
                          <td className="num px-3 py-1.5 text-right text-slate-300">
                            {formatNumber(holding.shares, 0)}
                          </td>
                          <td className="num px-3 py-1.5 text-right text-slate-200">
                            ¥{formatNumber(holding.current_price)}
                            {isIntraday && holding.eod_price != null && holding.eod_price !== holding.current_price && (
                              <div className="text-[10px] text-slate-500">昨收 {formatNumber(holding.eod_price)}</div>
                            )}
                          </td>
                          <td className="num px-3 py-1.5 text-right text-slate-400">
                            {holding.cost_price > 0 ? `¥${formatNumber(holding.cost_price)}` : '--'}
                          </td>
                          <td className={cn('num px-3 py-1.5 text-right', changeToneClass(pnlRatio))}>
                            {pnlRatio != null ? formatPercent(pnlRatio, { signed: true }) : '--'}
                          </td>
                          <td className="num px-3 py-1.5 text-right text-slate-300">
                            {formatPercent(holding.weight, { digits: 1 })}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </Panel>
            ) : (
              <div className="rounded-ctl border border-dashed border-line px-3 py-6 text-center text-xs text-slate-500">
                目前处于空仓观望状态
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
