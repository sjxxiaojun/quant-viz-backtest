import type { BacktestConfig } from '../types';

export const BACKTEST_MAX_SYMBOLS = 500;

type BacktestBudgetPayload = {
  pool?: string;
  max_symbols?: number;
  stocks?: string[] | null;
};

export function withAllPoolBudget<T extends BacktestBudgetPayload>(payload: T): T {
  const hasExplicitStocks = Array.isArray(payload.stocks) && payload.stocks.length > 0;
  if (payload.pool === 'all' && !hasExplicitStocks && payload.max_symbols == null) {
    return { ...payload, max_symbols: BACKTEST_MAX_SYMBOLS };
  }
  return payload;
}

export function withPoolSelectionBudget(config: BacktestConfig, pool: string): BacktestConfig {
  if (pool === 'all') {
    return {
      ...config,
      pool,
      max_symbols: config.max_symbols ?? BACKTEST_MAX_SYMBOLS,
    };
  }

  const next = { ...config, pool };
  delete next.max_symbols;
  return next;
}
