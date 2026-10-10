/**
 * 实盘模拟视图的数据访问层: 统一走 api/client, 响应逐字段收敛后返回强类型。
 * 所有会被渲染层直接调用方法的字段 (如 *.slice) 在此处收敛为 string/number。
 */
import { apiGet, apiPost } from '../../api/client';
import { assertArray, isRecord } from '../../api/guards';
import type {
  Account,
  AIDecision,
  AIWorkLog,
  AIWorkMessage,
  AutomationJobKind,
  AutomationRun,
  AutomationSnapshot,
  AutomationStatus,
  EquityPoint,
  FreshnessSample,
  HoldingDetail,
  PerformanceStats,
  VirtualTrade,
} from './types';

function numberValue(value: unknown, fallback = 0): number {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN;
  return Number.isFinite(parsed) ? parsed : fallback;
}

function optionalNumber(value: unknown): number | null {
  return value == null ? null : numberValue(value);
}

function stringValue(value: unknown, fallback = ''): string {
  return value == null ? fallback : String(value);
}

function optionalString(value: unknown): string | undefined {
  return value == null ? undefined : String(value);
}

function normalizeHoldingDetail(item: unknown): HoldingDetail | null {
  if (!isRecord(item)) return null;
  const symbol = stringValue(item.symbol).trim();
  if (!symbol) return null;
  return {
    symbol,
    name: optionalString(item.name),
    shares: numberValue(item.shares),
    cost_price: numberValue(item.cost_price),
    current_price: numberValue(item.current_price),
    eod_price: optionalNumber(item.eod_price),
    market_value: numberValue(item.market_value),
    weight: numberValue(item.weight),
    entry_date: item.entry_date == null ? null : stringValue(item.entry_date),
    entry_price: optionalNumber(item.entry_price),
  };
}

function normalizeAccount(item: unknown): Account {
  if (!isRecord(item)) throw new Error('账户数据格式无效');
  const topHoldingDetails = Array.isArray(item.top_holding_details)
    ? item.top_holding_details
        .map(normalizeHoldingDetail)
        .filter((holding): holding is HoldingDetail => holding !== null)
    : [];
  return {
    strategy_id: stringValue(item.strategy_id),
    name: stringValue(item.name),
    total_value: numberValue(item.total_value),
    cash: numberValue(item.cash),
    start_value: numberValue(item.start_value),
    last_update: stringValue(item.last_update),
    top_holdings: Array.isArray(item.top_holdings) ? item.top_holdings.map(String) : [],
    top_holding_details: topHoldingDetails,
    return_rate: numberValue(item.return_rate),
    eod_total_value: optionalNumber(item.eod_total_value),
    eod_return_rate: optionalNumber(item.eod_return_rate),
    intraday_total_value: optionalNumber(item.intraday_total_value),
    intraday_return_rate: optionalNumber(item.intraday_return_rate),
    valuation_source: item.valuation_source == null ? null : stringValue(item.valuation_source),
    valuation_time: item.valuation_time == null ? null : stringValue(item.valuation_time),
    snapshot_coverage: optionalNumber(item.snapshot_coverage),
    snapshot_price_count: optionalNumber(item.snapshot_price_count),
    snapshot_total_positions: optionalNumber(item.snapshot_total_positions),
  };
}

function normalizeTrade(item: unknown): VirtualTrade {
  if (!isRecord(item)) throw new Error('交易流水格式无效');
  return {
    id: numberValue(item.id),
    strategy_id: stringValue(item.strategy_id),
    date: stringValue(item.date),
    symbol: stringValue(item.symbol),
    side: stringValue(item.side),
    price: numberValue(item.price),
    shares: numberValue(item.shares),
    fee: numberValue(item.fee),
    msg: stringValue(item.msg),
  };
}

function normalizeEquityPoint(item: unknown): EquityPoint {
  if (!isRecord(item)) throw new Error('净值曲线格式无效');
  return { date: stringValue(item.date), total_value: numberValue(item.total_value) };
}

function normalizeStats(item: unknown): PerformanceStats {
  if (!isRecord(item)) throw new Error('绩效指标格式无效');
  return {
    total_return: numberValue(item.total_return),
    annualized_return: numberValue(item.annualized_return),
    sharpe_ratio: numberValue(item.sharpe_ratio),
    max_drawdown: numberValue(item.max_drawdown),
    win_rate: numberValue(item.win_rate),
    volatility: numberValue(item.volatility),
  };
}

function normalizeFreshnessSample(item: unknown): FreshnessSample | undefined {
  if (!isRecord(item)) return undefined;
  return {
    total_local: numberValue(item.total_local),
    checked_count: numberValue(item.checked_count),
    fresh_count: numberValue(item.fresh_count),
    stale_count: numberValue(item.stale_count),
  };
}

function normalizeRun(item: unknown): AutomationRun | null {
  if (!isRecord(item)) return null;
  return {
    run_id: stringValue(item.run_id),
    job_type: stringValue(item.job_type),
    status: stringValue(item.status),
    trigger: optionalString(item.trigger),
    target_date: item.target_date == null ? null : stringValue(item.target_date),
    started_at: optionalString(item.started_at),
    finished_at: item.finished_at == null ? null : stringValue(item.finished_at),
    error: item.error == null ? null : stringValue(item.error),
    summary: isRecord(item.summary) ? item.summary : undefined,
  };
}

function normalizeSnapshot(item: unknown): AutomationSnapshot | null {
  if (!isRecord(item)) return null;
  return {
    snapshot_id: stringValue(item.snapshot_id),
    captured_at: stringValue(item.captured_at),
    market_session: optionalString(item.market_session),
    row_count: numberValue(item.row_count),
    source: optionalString(item.source),
  };
}

function normalizeDecision(item: unknown): AIDecision | null {
  if (!isRecord(item)) return null;
  return {
    decision_id: stringValue(item.decision_id),
    actor: stringValue(item.actor),
    source: stringValue(item.source),
    status: stringValue(item.status),
    created_at: stringValue(item.created_at),
    summary: optionalString(item.summary),
    actions: Array.isArray(item.actions)
      ? item.actions.filter(isRecord).map((action) => ({
          type: optionalString(action.type),
          params: isRecord(action.params) ? action.params : undefined,
        }))
      : undefined,
  };
}

function normalizeWorkLog(item: unknown): AIWorkLog | null {
  if (!isRecord(item)) return null;
  return {
    work_id: stringValue(item.work_id),
    work_type: stringValue(item.work_type),
    status: stringValue(item.status),
    trigger: optionalString(item.trigger),
    target_date: item.target_date == null ? null : stringValue(item.target_date),
    started_at: optionalString(item.started_at),
    finished_at: item.finished_at == null ? null : stringValue(item.finished_at),
    title: optionalString(item.title),
    summary: optionalString(item.summary),
    work_items: Array.isArray(item.work_items)
      ? item.work_items.filter(isRecord).map((workItem) => ({
          action: optionalString(workItem.action),
          status: optionalString(workItem.status),
          detail: optionalString(workItem.detail),
        }))
      : undefined,
    error: item.error == null ? null : stringValue(item.error),
  };
}

function normalizeWorkMessage(item: unknown): AIWorkMessage | null {
  if (!isRecord(item)) return null;
  return {
    message_id: stringValue(item.message_id),
    work_id: item.work_id == null ? null : stringValue(item.work_id),
    work_type: stringValue(item.work_type),
    trigger: optionalString(item.trigger),
    target_date: item.target_date == null ? null : stringValue(item.target_date),
    action_type: item.action_type == null ? null : stringValue(item.action_type),
    status: stringValue(item.status),
    level: stringValue(item.level),
    title: optionalString(item.title),
    body: optionalString(item.body),
    created_at: stringValue(item.created_at),
    details: isRecord(item.details) ? item.details : undefined,
  };
}

function collect<T>(value: unknown, normalize: (item: unknown) => T | null): T[] {
  if (!Array.isArray(value)) return [];
  return value.map(normalize).filter((item): item is T => item !== null);
}

export function normalizeAutomationStatus(item: unknown): AutomationStatus {
  if (!isRecord(item)) throw new Error('自动化状态格式无效');
  const scheduler = isRecord(item.scheduler)
    ? {
        enabled: Boolean(item.scheduler.enabled),
        running: Boolean(item.scheduler.running),
        next_jobs: Array.isArray(item.scheduler.next_jobs)
          ? item.scheduler.next_jobs.filter(isRecord).map((job) => ({
              job_type: stringValue(job.job_type),
              work_type: optionalString(job.work_type),
              run_at: stringValue(job.run_at),
            }))
          : undefined,
      }
    : undefined;
  const freshness = isRecord(item.data_freshness)
    ? {
        target_date: optionalString(item.data_freshness.target_date),
        status: optionalString(item.data_freshness.status),
        score: optionalNumber(item.data_freshness.score) ?? undefined,
        a_share: normalizeFreshnessSample(item.data_freshness.a_share),
        etf: normalizeFreshnessSample(item.data_freshness.etf),
      }
    : undefined;
  return {
    scheduler,
    data_freshness: freshness,
    recent_runs: collect(item.recent_runs, normalizeRun),
    recent_snapshots: collect(item.recent_snapshots, normalizeSnapshot),
    ai_decisions: collect(item.ai_decisions, normalizeDecision),
    ai_work_logs: collect(item.ai_work_logs, normalizeWorkLog),
    ai_work_messages: collect(item.ai_work_messages, normalizeWorkMessage),
    last_eod_update: isRecord(item.last_eod_update) ? item.last_eod_update : undefined,
    last_virtual_trade: isRecord(item.last_virtual_trade) ? item.last_virtual_trade : undefined,
  };
}

/* ============================ 请求 ============================ */
export function accountVersion(): 'legacy' | 'v2' { return localStorage.getItem('momo:account-version') === 'legacy' ? 'legacy' : 'v2'; }

export async function fetchAccounts(signal?: AbortSignal): Promise<Account[]> {
  const data = await apiGet<unknown>(`/api/virtual-trade/accounts?version=${accountVersion()}`, { timeout: 10000, signal });
  return assertArray(data, normalizeAccount, '账户数据');
}

export async function fetchTradeHistory(
  limit: number,
  offset: number,
  signal?: AbortSignal,
): Promise<VirtualTrade[]> {
  const data = await apiGet<unknown>(
    `/api/virtual-trade/history?limit=${limit}&offset=${offset}&version=${accountVersion()}`,
    { timeout: 10000, signal },
  );
  return assertArray(data, normalizeTrade, '交易流水');
}

export async function fetchAutomationStatus(signal?: AbortSignal): Promise<AutomationStatus> {
  const data = await apiGet<unknown>('/api/automation/status', { timeout: 15000, signal });
  return normalizeAutomationStatus(data);
}

export async function fetchEquityHistory(
  strategyId: string,
  signal?: AbortSignal,
): Promise<EquityPoint[]> {
  const data = await apiGet<unknown>(
    `/api/virtual-trade/equity-history?strategy_id=${encodeURIComponent(strategyId)}&version=${accountVersion()}`,
    { timeout: 10000, signal },
  );
  return assertArray(data, normalizeEquityPoint, '净值曲线');
}

export async function fetchPerformanceStats(
  strategyId: string,
  signal?: AbortSignal,
): Promise<PerformanceStats> {
  const data = await apiGet<unknown>(
    `/api/virtual-trade/stats?strategy_id=${encodeURIComponent(strategyId)}&version=${accountVersion()}`,
    { timeout: 10000, signal },
  );
  return normalizeStats(data);
}

export async function executeDailySimulation(): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>('/api/virtual-trade/execute', undefined, {
    timeout: 120000,
  });
}

export const AUTOMATION_JOB_LABELS: Record<AutomationJobKind, string> = {
  snapshot: '盘中快照',
  eodUpdate: '收盘补数',
  virtualTrade: '自动模拟盘',
  aiCycle: 'AI cycle',
  aiSimulationCare: 'AI 模拟盘托管',
  aiFactorLabCare: 'AI 因子实验托管',
};

export async function runAutomationJob(kind: AutomationJobKind): Promise<void> {
  if (kind === 'snapshot') {
    await apiPost('/api/automation/jobs/realtime-snapshot', { limit: 6000 }, { timeout: 60000 });
  } else if (kind === 'eodUpdate') {
    await apiPost(
      '/api/automation/jobs/eod-update',
      { dry_run: false, workers_a_share: 8, workers_etf: 4, retry: 1, task_timeout: 30 },
      { timeout: 900000 },
    );
  } else if (kind === 'virtualTrade') {
    await apiPost('/api/automation/jobs/virtual-trade', undefined, { timeout: 120000 });
  } else if (kind === 'aiCycle') {
    await apiPost('/api/automation/jobs/ai-cycle', { dry_run: false }, { timeout: 120000 });
  } else if (kind === 'aiSimulationCare') {
    await apiPost(
      '/api/automation/jobs/ai-managed-work',
      { work_type: 'simulation_supervision', dry_run: false },
      { timeout: 180000 },
    );
  } else {
    await apiPost(
      '/api/automation/jobs/ai-managed-work',
      { work_type: 'factor_lab_iteration', dry_run: false },
      { timeout: 900000 },
    );
  }
}
