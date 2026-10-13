import { isRecord } from './guards';
import type { BacktestConfig } from '../types';

export function restoreBacktestConfig(value: unknown): BacktestConfig | null {
  if (!isRecord(value) || typeof value.start_date !== 'string' || typeof value.end_date !== 'string' || typeof value.initial_capital !== 'number') return null;
  const num = (key: string, fallback: number) => typeof value[key] === 'number' ? value[key] as number : fallback;
  const optional = (key: string) => typeof value[key] === 'number' ? value[key] as number : undefined;
  return { start_date:value.start_date, end_date:value.end_date, initial_capital:value.initial_capital,
    factor:typeof value.factor==='string' ? value.factor : 'bottom_fishing',
    pool:typeof value.pool==='string' ? value.pool : 'auto',
    stocks:Array.isArray(value.stocks) ? value.stocks.filter((s):s is string=>typeof s==='string') : undefined,
    max_symbols:optional('max_symbols'), max_positions:num('max_positions',5),
    weight_mode:typeof value.weight_mode==='string' ? value.weight_mode : 'equal',
    max_hold_days:optional('max_hold_days'), stop_loss:num('stop_loss',-.08), take_profit:optional('take_profit'),
    commission_rate:num('commission_rate',.0003), commission_min:num('commission_min',5),
    stamp_tax_rate:num('stamp_tax_rate',.0005), slippage_rate:num('slippage_rate',.0003), close_slippage_rate:optional('close_slippage_rate'),
    allow_mock:value.allow_mock===true, same_close_approximation:value.same_close_approximation===true,
    price_mode:value.price_mode==='approximate_adjusted' ? 'approximate_adjusted' : 'strict_raw',
  };
}
