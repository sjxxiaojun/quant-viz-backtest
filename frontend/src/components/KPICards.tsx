import { AlertTriangle } from 'lucide-react';
import { cn, formatAmountCN, formatNumber, formatPercent, formatSignedPercent, changeToneClass } from '../utils';
import { getPoolLabel, type RuntimePool } from '../config/strategies';
import { Panel, SectionTitle, Skeleton, Stat, Tag } from './ui';
import type { BacktestResult } from '../types';

interface KPICardsProps {
  result: BacktestResult | null;
}

/** summary 中后端已返回但 types 尚未收录的扩展字段 */
interface SummaryExtras {
  benchmark_return?: number;
  excess_return?: number;
  cost_stats?: Record<string, number>;
}

const COST_STAT_ROWS: { key: string; label: string; kind: 'amount' | 'ratio' | 'number' }[] = [
  { key: 'commission_total', label: '佣金合计', kind: 'amount' },
  { key: 'stamp_tax_total', label: '印花税合计', kind: 'amount' },
  { key: 'slippage_total', label: '滑点损耗', kind: 'amount' },
  { key: 'total_cost', label: '总交易成本', kind: 'amount' },
  { key: 'turnover_amount', label: '累计成交额', kind: 'amount' },
  { key: 'cost_pct_initial', label: '成本/初始资金', kind: 'ratio' },
  { key: 'cost_bps_turnover', label: '成本 (bp/成交额)', kind: 'number' },
];

const EXECUTION_STAT_ROWS: { key: string; label: string; kind: 'ratio' | 'count' }[] = [
  { key: 'buy_fill_rate', label: '买入成交率', kind: 'ratio' },
  { key: 'sell_fill_rate', label: '卖出成交率', kind: 'ratio' },
  { key: 'partial_fill_count', label: '部分成交笔数', kind: 'count' },
  { key: 'blocked_limit_up_buy_count', label: '涨停拒买', kind: 'count' },
  { key: 'blocked_limit_down_sell_count', label: '跌停拒卖', kind: 'count' },
  { key: 'blocked_halt_trade_count', label: '停牌拦截', kind: 'count' },
  { key: 't1_sell_block_count', label: 'T+1 卖出限制', kind: 'count' },
  { key: 'delayed_exit_count', label: '延迟退出', kind: 'count' },
];

function StatRows({
  data,
  rows,
}: {
  data: Record<string, number>;
  rows: { key: string; label: string; kind: string }[];
}) {
  const visible = rows.filter((row) => typeof data[row.key] === 'number');
  if (visible.length === 0) {
    return <div className="py-2 text-[11px] text-slate-600">本次回测未返回该统计。</div>;
  }
  return (
    <table className="w-full">
      <tbody>
        {visible.map((row) => {
          const value = data[row.key];
          const text =
            row.kind === 'amount'
              ? formatAmountCN(value)
              : row.kind === 'ratio'
                ? formatPercent(value)
                : row.kind === 'count'
                  ? formatNumber(value, 0)
                  : formatNumber(value);
          return (
            <tr key={row.key} className="border-b border-line last:border-0">
              <td className="py-1 pr-2 text-[11px] text-slate-500">{row.label}</td>
              <td className="num py-1 text-right text-[11px] text-slate-300">{text}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function sharpeTier(sharpe: number): { label: string; tone: 'ok' | 'warn' | 'up' } {
  if (sharpe >= 1) return { label: '优秀', tone: 'ok' };
  if (sharpe >= 0) return { label: '一般', tone: 'warn' };
  return { label: '较差', tone: 'up' };
}

function drawdownTier(absDrawdown: number): { label: string; tone: 'ok' | 'warn' | 'up' } {
  if (absDrawdown < 0.15) return { label: '可控', tone: 'ok' };
  if (absDrawdown < 0.25) return { label: '偏高', tone: 'warn' };
  return { label: '过深', tone: 'up' };
}

export function KPICards({ result }: KPICardsProps) {
  // 无数据: 骨架占位, 不渲染 '--' 占位数字
  if (!result) {
    return (
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Panel key={i} className="space-y-2 p-3">
            <Skeleton className="h-2.5 w-16" />
            <Skeleton className="h-6 w-24" />
            <Skeleton className="h-2.5 w-20" />
          </Panel>
        ))}
      </div>
    );
  }

  const summary = result.summary;
  const extras = summary as BacktestResult['summary'] & SummaryExtras;
  const benchmarkReturn =
    result.benchmark_history?.length && typeof extras.benchmark_return === 'number'
      ? extras.benchmark_return
      : result.benchmark_history && result.benchmark_history.length > 0
        ? result.benchmark_history[result.benchmark_history.length - 1].value - 1
        : null;
  const excessReturn =
    benchmarkReturn != null && typeof extras.excess_return === 'number'
      ? extras.excess_return
      : benchmarkReturn != null
        ? result.total_return - benchmarkReturn
        : null;

  const sharpe = sharpeTier(summary.sharpe_ratio);
  const drawdown = drawdownTier(Math.abs(summary.max_drawdown));

  const hasMockData = result.data_sources_used && Object.values(result.data_sources_used).includes('MOCK');
  const resolvedPool = result.resolved_pool;
  const allPoolSelectionSummary =
    resolvedPool?.effective_pool === 'all' && resolvedPool.asset_class === 'a_share'
      ? {
          selected: resolvedPool.symbols_count,
          total: resolvedPool.local_universe_size ?? resolvedPool.symbols_before_budget,
          note: resolvedPool.sample_source_note,
          method: resolvedPool.method_cn,
        }
      : null;
  const sourceSummary = result.data_sources_used
    ? Object.entries(
        Object.values(result.data_sources_used).reduce<Record<string, number>>((acc, source) => {
          acc[source] = (acc[source] || 0) + 1;
          return acc;
        }, {}),
      )
    : [];

  return (
    <div className="space-y-3">
      {/* KPI 行 */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Panel className="p-3">
          <Stat
            label="累计收益率"
            value={formatSignedPercent(result.total_return)}
            delta={result.total_return}
            toneByDelta
            hint="回测区间内组合总收益"
          />
          <div className="num mt-1 text-[10px] text-slate-500">
            年化 {formatPercent(summary.annual_return ?? null)}
          </div>
        </Panel>
        <Panel className="p-3">
          <div className="flex items-start justify-between gap-2">
            <Stat label="夏普比率" value={formatNumber(summary.sharpe_ratio)} />
            <Tag tone={sharpe.tone}>{sharpe.label}</Tag>
          </div>
          <div className="num mt-1 text-[10px] text-slate-500">
            卡尔马 {formatNumber(summary.calmar_ratio ?? null)}
          </div>
        </Panel>
        <Panel className="p-3">
          <div className="flex items-start justify-between gap-2">
            <Stat label="最大回撤" value={formatPercent(summary.max_drawdown)} />
            <Tag tone={drawdown.tone}>{drawdown.label}</Tag>
          </div>
          <div className="num mt-1 text-[10px] text-slate-500">
            胜率 {formatPercent(summary.win_rate ?? null, { digits: 1 })}
          </div>
        </Panel>
        <Panel className="p-3">
          <Stat label="总交易次数" value={formatNumber(summary.total_trades ?? null, 0)} />
          <div className="num mt-1 text-[10px] text-slate-500">
            盈亏比 {formatNumber(summary.profit_loss_ratio ?? null)}
          </div>
        </Panel>
      </div>

      {/* 基准对比行 */}
      {benchmarkReturn != null && (
        <Panel className="flex flex-wrap items-center gap-x-6 gap-y-1 p-3">
          <span className="label-caps">基准对比</span>
          <span className="text-[11px] text-slate-500">
            沪深300{' '}
            <span className={cn('num font-medium', changeToneClass(benchmarkReturn))}>
              {formatSignedPercent(benchmarkReturn)}
            </span>
          </span>
          <span className="text-[11px] text-slate-500">
            组合{' '}
            <span className={cn('num font-medium', changeToneClass(result.total_return))}>
              {formatSignedPercent(result.total_return)}
            </span>
          </span>
          {excessReturn != null && (
            <span className="text-[11px] text-slate-500">
              超额收益{' '}
              <span className={cn('num font-semibold', changeToneClass(excessReturn))}>
                {formatSignedPercent(excessReturn)}
              </span>
            </span>
          )}
        </Panel>
      )}

      {/* 成本 / 执行统计 */}
      {(extras.cost_stats || summary.execution_stats) && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          <Panel className="p-3">
            <SectionTitle className="mb-2">成本统计</SectionTitle>
            <StatRows data={extras.cost_stats ?? {}} rows={COST_STAT_ROWS} />
          </Panel>
          <Panel className="p-3">
            <SectionTitle
              className="mb-2"
              right={
                summary.execution_model?.name ? (
                  <span className="num text-[9px] text-slate-600" title="执行撮合模型">
                    {summary.execution_model.name}
                  </span>
                ) : undefined
              }
            >
              执行统计
            </SectionTitle>
            <StatRows data={summary.execution_stats ?? {}} rows={EXECUTION_STAT_ROWS} />
          </Panel>
        </div>
      )}

      {/* 数据路由说明 */}
      {resolvedPool && (
        <Panel className="space-y-1.5 p-3">
          <SectionTitle className="mb-1" right={<Tag tone="accent">{resolvedPool.asset_class === 'etf' ? 'ETF 池' : 'A股池'}</Tag>}>
            本次数据路由
          </SectionTitle>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
            <span>
              请求参数 <span className="num text-slate-300">{resolvedPool.requested_pool}</span>
            </span>
            <span>
              实际池{' '}
              <span className="text-slate-300">
                {getPoolLabel(resolvedPool.effective_pool as RuntimePool) || resolvedPool.effective_pool}
              </span>
            </span>
            {resolvedPool.symbols_count !== undefined && (
              <span>
                标的数量 <span className="num text-slate-300">{resolvedPool.symbols_count}</span>
              </span>
            )}
            {allPoolSelectionSummary?.selected !== undefined && allPoolSelectionSummary.total !== undefined && (
              <span>
                全A轻量预筛{' '}
                <span className="num text-slate-300">
                  {allPoolSelectionSummary.selected} / {allPoolSelectionSummary.total}
                </span>
              </span>
            )}
            {sourceSummary.length > 0 && (
              <span>
                数据源{' '}
                <span className="num text-slate-300">
                  {sourceSummary.map(([source, count]) => `${source}×${count}`).join(' / ')}
                </span>
              </span>
            )}
          </div>
          {allPoolSelectionSummary?.note && (
            <p className="text-[10px] leading-relaxed text-slate-600">
              {allPoolSelectionSummary.method ? `${allPoolSelectionSummary.method}。` : ''}
              {allPoolSelectionSummary.note}
            </p>
          )}
        </Panel>
      )}

      {/* 模拟数据警告 */}
      {hasMockData && (
        <div className="flex items-start gap-2 rounded-panel border border-warn/30 bg-warn/10 p-3">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
          <div>
            <div className="text-xs font-semibold text-warn">模拟数据警告</div>
            <p className="mt-0.5 text-[11px] leading-relaxed text-warn/80">
              本次回测包含自动生成的 MOCK 模拟数据，可能由于节假日休市或网络接口限流导致未能拉取到真实历史行情。回测结果可能偏向乐观，请勿作为实盘唯一依据。
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
