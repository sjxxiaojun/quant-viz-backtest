import type { BacktestResult, HistoryData, Trade } from '../types';

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function toFiniteNumber(value: unknown, field: string): number {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN;
  if (!Number.isFinite(parsed)) {
    throw new Error(`接口字段 ${field} 不是有效数字`);
  }
  return parsed;
}

function toStringField(value: unknown, field: string): string {
  if (typeof value !== 'string' || !value) {
    throw new Error(`接口字段 ${field} 不是有效字符串`);
  }
  return value;
}

function normalizeTrade(source: unknown): Trade {
  if (!isRecord(source)) throw new Error('成交记录格式无效');
  return {
    date: toStringField(source.date, 'trade.date'),
    stock_code: toStringField(source.stock_code, 'trade.stock_code'),
    stock_name: typeof source.stock_name === 'string' ? source.stock_name : String(source.stock_code ?? ''),
    side: toStringField(source.side, 'trade.side'),
    price: toFiniteNumber(source.price, 'trade.price'),
    qty: toFiniteNumber(source.qty, 'trade.qty'),
  };
}

function normalizeHistory(source: unknown): HistoryData {
  if (!isRecord(source)) throw new Error('净值记录格式无效');
  return {
    date: toStringField(source.date, 'history.date'),
    total_value: toFiniteNumber(source.total_value, 'history.total_value'),
    cash: toFiniteNumber(source.cash, 'history.cash'),
    drawdown: source.drawdown == null ? undefined : toFiniteNumber(source.drawdown, 'history.drawdown'),
    returns: source.returns == null ? undefined : toFiniteNumber(source.returns, 'history.returns'),
    daily_trades: Array.isArray(source.daily_trades) ? source.daily_trades.map(normalizeTrade) : undefined,
  };
}

export function assertBacktestResult(source: unknown): BacktestResult {
  if (!isRecord(source)) throw new Error('回测结果不是对象');
  if (!Array.isArray(source.history) || !Array.isArray(source.trades) || !isRecord(source.summary)) {
    throw new Error('回测结果缺少 history/trades/summary');
  }
  const result: BacktestResult = {
    ...source,
    total_return: toFiniteNumber(source.total_return, 'total_return'),
    history: source.history.map(normalizeHistory),
    trades: source.trades.map(normalizeTrade),
    summary: {
      ...source.summary,
      initial_capital: toFiniteNumber(source.summary.initial_capital, 'summary.initial_capital'),
      final_value: toFiniteNumber(source.summary.final_value, 'summary.final_value'),
      max_drawdown: toFiniteNumber(source.summary.max_drawdown, 'summary.max_drawdown'),
      sharpe_ratio: toFiniteNumber(source.summary.sharpe_ratio, 'summary.sharpe_ratio'),
    },
  };
  return result;
}

export function assertArray<T>(source: unknown, itemGuard: (item: unknown) => T, label: string): T[] {
  if (!Array.isArray(source)) throw new Error(`${label} 不是数组`);
  return source.map(itemGuard);
}
