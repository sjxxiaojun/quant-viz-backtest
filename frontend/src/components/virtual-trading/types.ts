/** 实盘模拟视图的领域类型 (与后端 /api/virtual-trade、/api/automation 响应对齐) */

export interface HoldingDetail {
  symbol: string;
  name?: string;
  shares: number;
  cost_price: number;
  current_price: number;
  eod_price?: number | null;
  market_value: number;
  weight: number;
  entry_date?: string | null;
  entry_price?: number | null;
}

export interface Account {
  strategy_id: string;
  name: string;
  total_value: number;
  cash: number;
  start_value: number;
  last_update: string;
  top_holdings: string[];
  top_holding_details?: HoldingDetail[];
  /** 百分数口径 (3.5 表示 +3.5%) */
  return_rate: number;
  eod_total_value?: number | null;
  eod_return_rate?: number | null;
  intraday_total_value?: number | null;
  intraday_return_rate?: number | null;
  valuation_source?: string | null;
  valuation_time?: string | null;
  snapshot_coverage?: number | null;
  snapshot_price_count?: number | null;
  snapshot_total_positions?: number | null;
}

export interface VirtualTrade {
  id: number;
  strategy_id: string;
  date: string;
  symbol: string;
  side: string;
  price: number;
  shares: number;
  fee: number;
  msg: string;
}

export interface PerformanceStats {
  total_return: number;
  annualized_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  volatility: number;
}

export interface EquityPoint {
  date: string;
  total_value: number;
}

export interface AutomationRun {
  run_id: string;
  job_type: string;
  status: string;
  trigger?: string;
  target_date?: string | null;
  started_at?: string;
  finished_at?: string | null;
  error?: string | null;
  summary?: Record<string, unknown>;
}

export interface AutomationSnapshot {
  snapshot_id: string;
  captured_at: string;
  market_session?: string;
  row_count: number;
  source?: string;
}

export interface AIDecision {
  decision_id: string;
  actor: string;
  source: string;
  status: string;
  created_at: string;
  summary?: string;
  actions?: { type?: string; params?: Record<string, unknown> }[];
}

export interface AIWorkItem {
  action?: string;
  status?: string;
  detail?: string;
}

export interface AIWorkLog {
  work_id: string;
  work_type: string;
  status: string;
  trigger?: string;
  target_date?: string | null;
  started_at?: string;
  finished_at?: string | null;
  title?: string;
  summary?: string;
  work_items?: AIWorkItem[];
  error?: string | null;
}

export interface AIWorkMessage {
  message_id: string;
  work_id?: string | null;
  work_type: string;
  trigger?: string;
  target_date?: string | null;
  action_type?: string | null;
  status: string;
  level: string;
  title?: string;
  body?: string;
  created_at: string;
  details?: Record<string, unknown>;
}

export interface FreshnessSample {
  total_local?: number;
  checked_count?: number;
  fresh_count?: number;
  stale_count?: number;
}

export interface AutomationStatus {
  scheduler?: {
    enabled?: boolean;
    running?: boolean;
    next_jobs?: { job_type: string; work_type?: string; run_at: string }[];
  };
  data_freshness?: {
    calendar_error?: string;
    target_date?: string;
    status?: string;
    score?: number;
    a_share?: FreshnessSample;
    etf?: FreshnessSample;
  };
  recent_runs?: AutomationRun[];
  recent_snapshots?: AutomationSnapshot[];
  ai_decisions?: AIDecision[];
  ai_work_logs?: AIWorkLog[];
  ai_work_messages?: AIWorkMessage[];
  last_eod_update?: Record<string, unknown>;
  last_virtual_trade?: Record<string, unknown>;
}

export type AutomationJobKind =
  | 'snapshot'
  | 'eodUpdate'
  | 'virtualTrade'
  | 'aiCycle'
  | 'aiSimulationCare'
  | 'aiFactorLabCare';

export type VirtualTradingSection = 'ai' | 'strategies' | 'flow';
