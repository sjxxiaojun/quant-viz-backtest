import { apiGet } from './client';
import { isRecord } from './guards';
import { strategyInfo } from '../config/strategies';

/**
 * 动态策略目录: GET /api/strategies (后端 STRATEGY_REGISTRY 全量)。
 * 本地 config/strategies.ts 只覆盖了部分策略的营销文案,
 * 目录以后端为唯一事实来源, 本地 desc/tags 仅作为补充展示。
 */

export interface StrategyCatalogEntry {
  id: string;
  name: string;
  category: string;
  pool: string;
  assetClass: 'a_share' | 'etf';
  signalType: string;
  holdingPolicy: string;
  executionMode: string;
  requiresArtifact: boolean;
  defaultMaxHoldDays: number | null;
  defaultTakeProfit: number | null;
  canonicalStrategyId?: string;
  implementationVersion?: string;
  factorSemantics?: Record<string,string>;
  /** 本地补充文案 (仅老策略有) */
  desc?: string;
  tags?: string[];
}

const EXECUTION_MODE_LABELS: Record<string, string> = {
  next_open_rebalance: '次日开盘调仓',
  signal_close_to_next_open: '收盘信号 · 次开成交',
};

const HOLDING_POLICY_LABELS: Record<string, string> = {
  sell_on_minus_one: '信号翻空即卖',
  hold_while_selected: '入选期间持有',
  timeout_exit: '限时持有退出',
};

const POOL_SHORT_LABELS: Record<string, string> = {
  core: '核心池',
  blackhorse: '弹性池',
  etf: 'ETF池',
  power_energy: '电力池',
  all: '全市场',
};

export function getExecutionModeLabel(mode: string): string {
  return EXECUTION_MODE_LABELS[mode] || mode;
}

export function getHoldingPolicyLabel(policy: string): string {
  return HOLDING_POLICY_LABELS[policy] || policy;
}

export function getPoolShortLabel(pool: string): string {
  return POOL_SHORT_LABELS[pool] || pool;
}

function toOptionalNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function normalizeEntry(id: string, source: unknown): StrategyCatalogEntry | null {
  if (!isRecord(source)) return null;
  const local = strategyInfo[id];
  const name = typeof source.name === 'string' && source.name ? source.name : local?.name || id;
  const pool = typeof source.pool === 'string' && source.pool ? source.pool : local?.pool || 'core';
  return {
    id,
    name,
    category: typeof source.category === 'string' && source.category ? source.category : local?.category || '未分类',
    pool,
    assetClass: source.asset_class === 'etf' || pool === 'etf' ? 'etf' : 'a_share',
    signalType: typeof source.signal_type === 'string' ? source.signal_type : 'stateful',
    holdingPolicy: typeof source.holding_policy === 'string' ? source.holding_policy : 'sell_on_minus_one',
    executionMode: typeof source.execution_mode === 'string' ? source.execution_mode : 'next_open_rebalance',
    requiresArtifact: source.requires_artifact === true,
    defaultMaxHoldDays: toOptionalNumber(source.default_max_hold_days),
    defaultTakeProfit: toOptionalNumber(source.default_take_profit),
    canonicalStrategyId: typeof source.canonical_strategy_id === 'string' ? source.canonical_strategy_id : id,
    implementationVersion: typeof source.implementation_version === 'string' ? source.implementation_version : undefined,
    factorSemantics: isRecord(source.factor_semantics) ? Object.fromEntries(Object.entries(source.factor_semantics).filter((entry): entry is [string,string] => typeof entry[1] === 'string')) : undefined,
    desc: local?.desc,
    tags: local?.tags,
  };
}

/** 后端不可用时的本地兜底目录 (仅老策略) */
export function localFallbackCatalog(): StrategyCatalogEntry[] {
  return Object.entries(strategyInfo).map(([id, meta]) => ({
    id,
    name: meta.name,
    category: meta.category,
    pool: meta.pool,
    assetClass: meta.assetClass,
    signalType: 'stateful',
    holdingPolicy: 'sell_on_minus_one',
    executionMode: 'next_open_rebalance',
    requiresArtifact: false,
    defaultMaxHoldDays: null,
    defaultTakeProfit: null,
    desc: meta.desc,
    tags: meta.tags,
  }));
}

export async function fetchStrategyCatalog(signal?: AbortSignal): Promise<StrategyCatalogEntry[]> {
  const payload = await apiGet<unknown>('/api/strategies', { timeout: 10000, signal });
  if (!isRecord(payload)) throw new Error('策略目录响应不是对象');
  const entries: StrategyCatalogEntry[] = [];
  for (const [id, raw] of Object.entries(payload)) {
    const entry = normalizeEntry(id, raw);
    if (entry) entries.push(entry);
  }
  if (entries.length === 0) throw new Error('策略目录为空');
  return entries;
}

/** 按类别分组, 保持后端返回顺序 */
export function groupByCategory(entries: StrategyCatalogEntry[]): [string, StrategyCatalogEntry[]][] {
  const groups = new Map<string, StrategyCatalogEntry[]>();
  for (const entry of entries) {
    const list = groups.get(entry.category);
    if (list) {
      list.push(entry);
    } else {
      groups.set(entry.category, [entry]);
    }
  }
  return Array.from(groups.entries());
}
