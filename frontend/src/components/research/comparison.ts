import { assertBacktestResult, isRecord } from '../../api/guards';
import type { BacktestResult } from '../../types';
export interface ComparisonEntry {
  label: string;
  result: BacktestResult;
}
export function comparisonEntries(
  label: string,
  payload: unknown,
): ComparisonEntry[] {
  if (!isRecord(payload)) return [];
  if (payload.kind === 'experiment')
    return comparisonEntries(`${label} · 独立测试`, payload.test_result);
  if ('history' in payload && 'summary' in payload) {
    try {
      return [{ label, result: assertBacktestResult(payload) }];
    } catch {
      return [];
    }
  }
  if (isRecord(payload.strategy_backtests))
    return Object.entries(payload.strategy_backtests).flatMap(([key, value]) =>
      comparisonEntries(`${label} · ${key}`, value),
    );
  return Object.entries(payload).flatMap(([key, value]) =>
    isRecord(value) && 'history' in value
      ? comparisonEntries(`${label} · ${key}`, value)
      : [],
  );
}
export function metrics(result: BacktestResult) {
  const summary = result.summary;
  return {
    net: result.total_return,
    benchmark: result.benchmark_history?.length
      ? result.benchmark_history.at(-1)!.value - 1
      : null,
    drawdown: summary.max_drawdown,
    sharpe: summary.sharpe_ratio,
    cost: summary.cost_stats?.total_cost,
    turnover: summary.cost_stats?.turnover_ratio,
  };
}
export const pct = (value: number | null | undefined) =>
  typeof value === 'number' && Number.isFinite(value)
    ? `${(value * 100).toFixed(2)}%`
    : '—';
