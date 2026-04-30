import React, { useCallback, useState, useEffect, useRef } from 'react';
import { EChart } from './EChart';
import { 
  Trophy, Briefcase, Play, History, TrendingUp, 
  TrendingDown, Clock,
  ArrowRightLeft, Target, X,
  Activity, Zap, Shield, BarChart3, PieChart,
  Bot, FlaskConical, ClipboardList,
  type LucideIcon
} from 'lucide-react';
import { cn } from '../utils';
import { apiGet, apiPost, getApiErrorMessage } from '../api/client';
import { assertArray, isRecord } from '../api/guards';

interface HoldingDetail {
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

interface Account {
  strategy_id: string;
  name: string;
  total_value: number;
  cash: number;
  start_value: number;
  last_update: string;
  top_holdings: string[];
  top_holding_details?: HoldingDetail[];
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

interface Trade {
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

interface PerformanceStats {
  total_return: number;
  annualized_return: number;
  sharpe_ratio: number;
  max_drawdown: number;
  win_rate: number;
  volatility: number;
}

interface EquityPoint {
  date: string;
  total_value: number;
}

interface AutomationRun {
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

interface AutomationSnapshot {
  snapshot_id: string;
  captured_at: string;
  market_session?: string;
  row_count: number;
  source?: string;
}

interface AIDecision {
  decision_id: string;
  actor: string;
  source: string;
  status: string;
  created_at: string;
  summary?: string;
  actions?: { type?: string; params?: Record<string, unknown> }[];
}

interface AIWorkLog {
  work_id: string;
  work_type: string;
  status: string;
  trigger?: string;
  target_date?: string | null;
  started_at?: string;
  finished_at?: string | null;
  title?: string;
  summary?: string;
  work_items?: { action?: string; status?: string; detail?: string }[];
  error?: string | null;
}

interface AIWorkMessage {
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

interface AutomationStatus {
  scheduler?: {
    enabled?: boolean;
    running?: boolean;
    next_jobs?: { job_type: string; work_type?: string; run_at: string }[];
  };
  data_freshness?: {
    target_date?: string;
    status?: string;
    score?: number;
    a_share?: { total_local?: number; checked_count?: number; fresh_count?: number; stale_count?: number };
    etf?: { total_local?: number; checked_count?: number; fresh_count?: number; stale_count?: number };
  };
  recent_runs?: AutomationRun[];
  recent_snapshots?: AutomationSnapshot[];
  ai_decisions?: AIDecision[];
  ai_work_logs?: AIWorkLog[];
  ai_work_messages?: AIWorkMessage[];
  last_eod_update?: Record<string, unknown>;
  last_virtual_trade?: Record<string, unknown>;
}

type AutomationJobKind = 'snapshot' | 'eodDryRun' | 'virtualTrade' | 'aiCycle' | 'aiSimulationCare' | 'aiFactorLabCare';
type VirtualTradingSection = 'ai' | 'strategies' | 'flow';

function getErrorMessage(error: unknown, fallback: string): string {
  return getApiErrorMessage(error, error instanceof Error ? error.message : fallback);
}

function numberValue(value: unknown, fallback = 0): number {
  const parsed = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN;
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeHoldingDetail(item: unknown): HoldingDetail | null {
  if (!isRecord(item)) return null;
  const symbol = String(item.symbol || '').trim();
  if (!symbol) return null;
  return {
    symbol,
    name: item.name ? String(item.name) : undefined,
    shares: numberValue(item.shares),
    cost_price: numberValue(item.cost_price),
    current_price: numberValue(item.current_price),
    eod_price: item.eod_price == null ? null : numberValue(item.eod_price),
    market_value: numberValue(item.market_value),
    weight: numberValue(item.weight),
    entry_date: item.entry_date == null ? null : String(item.entry_date),
    entry_price: item.entry_price == null ? null : numberValue(item.entry_price),
  };
}

function normalizeAccount(item: unknown): Account {
  if (!isRecord(item)) throw new Error('账户数据格式无效');
  const topHoldingDetails = Array.isArray(item.top_holding_details)
    ? item.top_holding_details.map(normalizeHoldingDetail).filter((holding): holding is HoldingDetail => holding !== null)
    : [];
  return {
    strategy_id: String(item.strategy_id || ''),
    name: String(item.name || ''),
    total_value: numberValue(item.total_value),
    cash: numberValue(item.cash),
    start_value: numberValue(item.start_value),
    last_update: String(item.last_update || ''),
    top_holdings: Array.isArray(item.top_holdings) ? item.top_holdings.map(String) : [],
    top_holding_details: topHoldingDetails,
    return_rate: numberValue(item.return_rate),
    eod_total_value: item.eod_total_value == null ? null : numberValue(item.eod_total_value),
    eod_return_rate: item.eod_return_rate == null ? null : numberValue(item.eod_return_rate),
    intraday_total_value: item.intraday_total_value == null ? null : numberValue(item.intraday_total_value),
    intraday_return_rate: item.intraday_return_rate == null ? null : numberValue(item.intraday_return_rate),
    valuation_source: item.valuation_source == null ? null : String(item.valuation_source),
    valuation_time: item.valuation_time == null ? null : String(item.valuation_time),
    snapshot_coverage: item.snapshot_coverage == null ? null : numberValue(item.snapshot_coverage),
    snapshot_price_count: item.snapshot_price_count == null ? null : numberValue(item.snapshot_price_count),
    snapshot_total_positions: item.snapshot_total_positions == null ? null : numberValue(item.snapshot_total_positions),
  };
}

function normalizeTrade(item: unknown): Trade {
  if (!isRecord(item)) throw new Error('交易流水格式无效');
  return {
    id: numberValue(item.id),
    strategy_id: String(item.strategy_id || ''),
    date: String(item.date || ''),
    symbol: String(item.symbol || ''),
    side: String(item.side || ''),
    price: numberValue(item.price),
    shares: numberValue(item.shares),
    fee: numberValue(item.fee),
    msg: String(item.msg || ''),
  };
}

function normalizeEquityPoint(item: unknown): EquityPoint {
  if (!isRecord(item)) throw new Error('净值曲线格式无效');
  return { date: String(item.date || ''), total_value: numberValue(item.total_value) };
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

function normalizeAutomationStatus(item: unknown): AutomationStatus {
  if (!isRecord(item)) throw new Error('自动化状态格式无效');
  return item as unknown as AutomationStatus;
}

function statusTone(status?: string): string {
  if (status === 'success' || status === 'ready' || status === 'executed') return 'text-emerald-400';
  if (status === 'running') return 'text-cyan-400';
  if (status === 'partial' || status === 'degraded' || status === 'skipped' || status === 'dry_run') return 'text-amber-400';
  if (status === 'failed' || status === 'blocked' || status === 'rejected') return 'text-rose-400';
  return 'text-slate-400';
}

function messageTone(message?: AIWorkMessage): string {
  if (message?.level === 'error' || ['failed', 'rejected', 'blocked'].includes(message?.status || '')) {
    return 'border-rose-500/20 bg-rose-500/10 text-rose-100';
  }
  if (message?.level === 'warn' || ['partial', 'skipped', 'degraded'].includes(message?.status || '')) {
    return 'border-amber-500/20 bg-amber-500/10 text-amber-100';
  }
  if (message?.status === 'running') {
    return 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100';
  }
  return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-100';
}

function formatAutomationTime(value?: string | null): string {
  if (!value) return '--';
  return value.slice(0, 16).replace('T', ' ');
}

function findUnresolvedProblemRun(runs?: AutomationRun[]): AutomationRun | undefined {
  const recoveredJobTypes = new Set<string>();
  for (const run of runs || []) {
    if (['failed', 'partial'].includes(run.status)) {
      if (!recoveredJobTypes.has(run.job_type)) return run;
      continue;
    }
    if (['success', 'dry_run', 'executed', 'skipped'].includes(run.status)) {
      recoveredJobTypes.add(run.job_type);
    }
  }
  return undefined;
}

export function VirtualTrading() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [history, setHistory] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [executing, setExecuting] = useState(false);
  const [selectedStrategy, setSelectedStrategy] = useState<Account | null>(null);
  const [equityHistory, setEquityHistory] = useState<EquityPoint[]>([]);
  const [perfStats, setPerfStats] = useState<PerformanceStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [detailsError, setDetailsError] = useState<string | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [automationStatus, setAutomationStatus] = useState<AutomationStatus | null>(null);
  const [automationError, setAutomationError] = useState<string | null>(null);
  const [automationRunning, setAutomationRunning] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<VirtualTradingSection>('ai');
  const mountedRef = useRef(false);
  const dataRequestRef = useRef(0);
  const detailsRequestRef = useRef(0);

  const fetchData = useCallback(async () => {
    const requestId = ++dataRequestRef.current;
    try {
      setLoading(true);
      const [accData, histData] = await Promise.all([
        apiGet<unknown>('/api/virtual-trade/accounts', { timeout: 10000 }),
        apiGet<unknown>('/api/virtual-trade/history?limit=15&offset=0', { timeout: 10000 })
      ]);
      if (!mountedRef.current || requestId !== dataRequestRef.current) return;
      setAccounts(assertArray(accData, normalizeAccount, '账户数据').sort((a, b) => b.return_rate - a.return_rate));
      setHistory(assertArray(histData, normalizeTrade, '交易流水'));
      setError(null);
      try {
        const automation = await apiGet<unknown>('/api/automation/status', { timeout: 15000 });
        if (!mountedRef.current || requestId !== dataRequestRef.current) return;
        setAutomationStatus(normalizeAutomationStatus(automation));
        setAutomationError(null);
      } catch (automationErr: unknown) {
        if (!mountedRef.current || requestId !== dataRequestRef.current) return;
        setAutomationError(getErrorMessage(automationErr, '自动化状态加载失败'));
      }
    } catch (err: unknown) {
      if (!mountedRef.current || requestId !== dataRequestRef.current) return;
      setError(getErrorMessage(err, "获取数据失败"));
    } finally {
      if (mountedRef.current && requestId === dataRequestRef.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    const timer = window.setTimeout(() => {
      void fetchData();
    }, 0);
    return () => {
      mountedRef.current = false;
      dataRequestRef.current += 1;
      detailsRequestRef.current += 1;
      window.clearTimeout(timer);
    };
  }, [fetchData]);

  const fetchDetails = async (acc: Account) => {
    const requestId = ++detailsRequestRef.current;
    setSelectedStrategy(acc);
    setEquityHistory([]);
    setPerfStats(null);
    setDetailsError(null);
    setDetailsLoading(true);
    const strategyId = encodeURIComponent(acc.strategy_id);
    try {
      const [eqRes, statRes] = await Promise.all([
        apiGet<unknown>(`/api/virtual-trade/equity-history?strategy_id=${strategyId}`, { timeout: 10000 }),
        apiGet<unknown>(`/api/virtual-trade/stats?strategy_id=${strategyId}`, { timeout: 10000 })
      ]);
      if (!mountedRef.current || requestId !== detailsRequestRef.current) return;
      setEquityHistory(assertArray(eqRes, normalizeEquityPoint, '净值曲线'));
      setPerfStats(normalizeStats(statRes));
    } catch (err: unknown) {
      if (!mountedRef.current || requestId !== detailsRequestRef.current) return;
      setDetailsError(getErrorMessage(err, "策略详情加载失败"));
    } finally {
      if (mountedRef.current && requestId === detailsRequestRef.current) {
        setDetailsLoading(false);
      }
    }
  };

  const runDailyExecution = async () => {
    try {
      setExecuting(true);
      setError(null);
      setNotice(null);
      const data = await apiPost<Record<string, unknown>>('/api/virtual-trade/execute', undefined, { timeout: 120000 });
      const skipped = Array.isArray(data.skipped_days) && data.skipped_days.length > 0
        ? `，有 ${data.skipped_days.length} 个日期/股票池因数据不足被跳过`
        : '';
      if (!mountedRef.current) return;
      setNotice(`${data.message || '仿真运行完成'}，当前日期 ${data.date || '--'}${skipped}。`);
      await fetchData();
    } catch (err: unknown) {
      if (!mountedRef.current) return;
      setError(getErrorMessage(err, "执行失败"));
    } finally {
      if (mountedRef.current) {
        setExecuting(false);
      }
    }
  };

  const runAutomationJob = async (kind: AutomationJobKind) => {
    const labels: Record<AutomationJobKind, string> = {
      snapshot: '盘中快照',
      eodDryRun: '收盘补数演练',
      virtualTrade: '自动模拟盘',
      aiCycle: 'AI cycle',
      aiSimulationCare: 'AI 模拟盘托管',
      aiFactorLabCare: 'AI 因子实验托管',
    };
    try {
      setAutomationRunning(kind);
      setAutomationError(null);
      setNotice(null);
      if (kind === 'snapshot') {
        await apiPost('/api/automation/jobs/realtime-snapshot', { limit: 6000 }, { timeout: 60000 });
      } else if (kind === 'eodDryRun') {
        await apiPost('/api/automation/jobs/eod-update', { dry_run: true, limit_a_share: 1, limit_etf: 1 }, { timeout: 120000 });
      } else if (kind === 'virtualTrade') {
        await apiPost('/api/automation/jobs/virtual-trade', undefined, { timeout: 120000 });
      } else if (kind === 'aiCycle') {
        await apiPost('/api/automation/jobs/ai-cycle', { dry_run: false }, { timeout: 120000 });
      } else if (kind === 'aiSimulationCare') {
        await apiPost('/api/automation/jobs/ai-managed-work', { work_type: 'simulation_supervision', dry_run: false }, { timeout: 180000 });
      } else {
        await apiPost('/api/automation/jobs/ai-managed-work', { work_type: 'factor_lab_iteration', dry_run: false }, { timeout: 900000 });
      }
      if (!mountedRef.current) return;
      setNotice(`${labels[kind]}已完成，审计记录已刷新。`);
      await fetchData();
    } catch (err: unknown) {
      if (!mountedRef.current) return;
      setAutomationError(getErrorMessage(err, `${labels[kind]}执行失败`));
    } finally {
      if (mountedRef.current) {
        setAutomationRunning(null);
      }
    }
  };

  const getEquityOption = () => {
    if (!equityHistory.length) return {};
    return {
      backgroundColor: 'transparent',
      grid: { top: 20, right: 20, bottom: 40, left: 50 },
      tooltip: { 
        trigger: 'axis',
        backgroundColor: 'rgba(15, 23, 42, 0.9)',
        borderColor: '#1e293b',
        textStyle: { color: '#f1f5f9' }
      },
      xAxis: {
        type: 'category',
        data: equityHistory.map(h => h.date),
        axisLine: { lineStyle: { color: '#334155' } },
        axisLabel: { color: '#94a3b8', fontSize: 10 }
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLine: { show: false },
        axisLabel: { color: '#94a3b8', fontSize: 10 },
        splitLine: { lineStyle: { color: '#1e293b', type: 'dashed' } }
      },
      series: [{
        data: equityHistory.map(h => h.total_value),
        type: 'line',
        smooth: true,
        showSymbol: false,
        lineStyle: { color: '#3b82f6', width: 3 },
        areaStyle: {
          color: {
            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [{ offset: 0, color: 'rgba(59, 130, 246, 0.2)' }, { offset: 1, color: 'rgba(59, 130, 246, 0)' }]
          }
        }
      }]
    };
  };

  if (loading && accounts.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] space-y-4">
        <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
        <p className="text-slate-400 font-medium animate-pulse">正在加载仿真账户...</p>
      </div>
    );
  }

  const updateDates = accounts.map((account) => account.last_update).filter(Boolean).sort();
  const firstUpdate = updateDates[0];
  const lastAccountUpdate = updateDates[updateDates.length - 1];
  const lastUpdate = firstUpdate && lastAccountUpdate
    ? firstUpdate === lastAccountUpdate ? lastAccountUpdate : `${firstUpdate} 至 ${lastAccountUpdate}`
    : "N/A";
  const tickerTrades = history.slice(0, 5);
  const freshness = automationStatus?.data_freshness;
  const latestRun = automationStatus?.recent_runs?.[0];
  const latestProblemRun = findUnresolvedProblemRun(automationStatus?.recent_runs);
  const latestSnapshot = automationStatus?.recent_snapshots?.[0];
  const latestDecision = automationStatus?.ai_decisions?.[0];
  const latestWorkLog = automationStatus?.ai_work_logs?.[0];
  const latestMessage = automationStatus?.ai_work_messages?.[0];
  const nextJob = automationStatus?.scheduler?.next_jobs?.[0];
  const automationActions: Array<{ kind: AutomationJobKind; label: string; Icon: LucideIcon }> = [
    { kind: 'snapshot', label: '抓盘中快照', Icon: Activity },
    { kind: 'eodDryRun', label: '补数演练', Icon: Shield },
    { kind: 'virtualTrade', label: '追赶模拟盘', Icon: Play },
    { kind: 'aiCycle', label: '运行 AI cycle', Icon: Bot },
    { kind: 'aiSimulationCare', label: 'AI 托管模拟池', Icon: ClipboardList },
    { kind: 'aiFactorLabCare', label: 'AI 照料因子实验', Icon: FlaskConical },
  ];
  const tradingSections: Array<{ key: VirtualTradingSection; label: string; Icon: LucideIcon; meta: string }> = [
    { key: 'ai', label: 'AI', Icon: Bot, meta: latestMessage ? `${latestMessage.work_type} / ${latestMessage.status}` : '消息与托管' },
    { key: 'strategies', label: '策略', Icon: Briefcase, meta: `${accounts.length} 个账户` },
    { key: 'flow', label: '流水', Icon: History, meta: `${history.length} 条记录` },
  ];

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-700 pb-20">
      {/* 顶部行情滚动条 */}
      <div className="h-10 bg-slate-900/50 backdrop-blur-md border-y border-slate-800 overflow-hidden flex items-center relative">
        <div className="flex items-center gap-2 px-4 bg-blue-600 h-full z-10 shadow-xl">
          <Zap className="w-4 h-4 text-white fill-current" />
              <span className="text-[10px] font-black text-white whitespace-nowrap">调仓记录</span>
        </div>
        <div className="flex animate-marquee whitespace-nowrap">
          {tickerTrades.map((t, i) => (
            <div key={i} className="flex items-center gap-2 px-8 border-r border-slate-800">
              <span className="text-[10px] font-bold text-slate-500">{t.date}</span>
              <span className="text-[10px] font-black text-blue-400">{t.strategy_id}</span>
              <span className={cn(
                "text-[10px] font-black",
                t.side === 'BUY' ? "text-emerald-400" : "text-rose-400"
              )}>
                {t.side === 'BUY' ? '买入' : '卖出'} {t.symbol}
              </span>
              <span className="text-[10px] font-mono text-slate-300">¥{t.price}</span>
            </div>
          ))}
          {/* 重复一遍实现无缝滚动 */}
          {tickerTrades.map((t, i) => (
            <div key={`dup-${i}`} className="flex items-center gap-2 px-8 border-r border-slate-800">
              <span className="text-[10px] font-bold text-slate-500">{t.date}</span>
              <span className="text-[10px] font-black text-blue-400">{t.strategy_id}</span>
              <span className={cn(
                "text-[10px] font-black",
                t.side === 'BUY' ? "text-emerald-400" : "text-rose-400"
              )}>
                {t.side === 'BUY' ? '买入' : '卖出'} {t.symbol}
              </span>
              <span className="text-[10px] font-mono text-slate-300">¥{t.price}</span>
            </div>
          ))}
        </div>
      </div>

      {error && (
        <div className="rounded-2xl border border-rose-500/20 bg-rose-500/10 px-5 py-4 text-sm font-semibold text-rose-100">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-2xl border border-emerald-500/20 bg-emerald-500/10 px-5 py-4 text-sm font-semibold text-emerald-100">
          {notice}
        </div>
      )}

      {/* 顶部控制面板 */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-6 p-8 rounded-[2.5rem] border border-blue-500/10 bg-blue-950/20 backdrop-blur-xl shadow-2xl relative overflow-hidden group">
        <div className="absolute top-0 right-0 p-8 opacity-5 group-hover:opacity-10 transition-opacity">
          <Activity className="w-32 h-32 text-blue-500" />
        </div>
        
        <div className="space-y-3 relative z-10">
          <div className="flex items-center gap-3">
              <h2 className="text-4xl font-black text-white tracking-tighter">多策略仿真排行 <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-indigo-500">· 龟兔赛跑</span></h2>
              <div className="flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20">
                <Clock className="w-3.5 h-3.5 text-blue-400" />
                <span className="text-[10px] font-black text-blue-400 uppercase tracking-widest">数据日期: {lastUpdate}</span>
              </div>
            </div>
            <p className="text-slate-400 text-sm font-medium max-w-lg">
            本地仿真账户会按历史数据生成持仓，再用最新可用收盘价推进净值；每笔模拟成交计入 0.2% 交易摩擦。
          </p>
        </div>

        <div className="flex items-center gap-4 relative z-10">
          <button 
            onClick={runDailyExecution}
            disabled={executing}
            className={cn(
              "group flex items-center gap-3 px-10 py-5 rounded-2xl font-black text-sm transition-all shadow-2xl active:scale-95",
              executing ? "bg-slate-800 text-slate-500 cursor-not-allowed" : "bg-blue-600 hover:bg-blue-500 text-white shadow-blue-900/40"
            )}
          >
            {executing ? (
              <><div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" /> 运行仿真中...</>
            ) : (
              <><Play className="w-5 h-5 fill-current" /> 一键运行仿真</>
            )}
          </button>
        </div>
      </div>

      <nav className="grid grid-cols-1 md:grid-cols-3 gap-3 rounded-[2rem] border border-slate-800 bg-slate-950/50 p-2 backdrop-blur-xl">
        {tradingSections.map(({ key, label, Icon, meta }) => {
          const active = activeSection === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setActiveSection(key)}
              className={cn(
                "flex items-center justify-between gap-4 rounded-2xl border px-5 py-4 text-left transition-all",
                active
                  ? "border-cyan-500/30 bg-cyan-500/10 text-white shadow-lg shadow-cyan-950/20"
                  : "border-transparent bg-transparent text-slate-400 hover:border-slate-700 hover:bg-slate-900/60 hover:text-slate-100"
              )}
            >
              <span className="flex items-center gap-3">
                <span className={cn(
                  "flex h-10 w-10 items-center justify-center rounded-xl border",
                  active ? "border-cyan-400/30 bg-cyan-400/10 text-cyan-200" : "border-slate-800 bg-slate-900/60 text-slate-500"
                )}>
                  <Icon className="h-4 w-4" />
                </span>
                <span>
                  <span className="block text-lg font-black">{label}</span>
                  <span className="mt-0.5 block text-[10px] font-bold uppercase tracking-widest text-slate-500">{meta}</span>
                </span>
              </span>
            </button>
          );
        })}
      </nav>

      {activeSection === 'ai' && (
      <section className="rounded-[2rem] border border-cyan-500/10 bg-slate-900/50 backdrop-blur-xl p-6 shadow-2xl space-y-6">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-5">
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <div className="p-2 rounded-xl bg-cyan-500/10 border border-cyan-500/20">
                <Activity className="w-5 h-5 text-cyan-400" />
              </div>
              <div>
                <h3 className="text-2xl font-black text-white">自动化与 AI 运行层</h3>
                <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">
                  数据湖补数 · 模拟盘追赶 · AI 白名单动作
                </p>
              </div>
            </div>
            {automationError && (
              <div className="rounded-xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-xs font-semibold text-rose-100">
                {automationError}
              </div>
            )}
          </div>

          <div className="flex flex-wrap gap-3">
            {automationActions.map(({ kind, label, Icon }) => (
              <button
                key={kind}
                onClick={() => void runAutomationJob(kind)}
                disabled={automationRunning !== null}
                className={cn(
                  "inline-flex items-center gap-2 px-4 py-3 rounded-xl text-xs font-black border transition-all active:scale-95",
                  automationRunning === kind
                    ? "bg-cyan-500/20 border-cyan-400/30 text-cyan-100"
                    : "bg-slate-950/40 border-slate-800 text-slate-300 hover:border-cyan-500/30 hover:text-white",
                  automationRunning !== null && automationRunning !== kind ? "opacity-40 cursor-not-allowed" : ""
                )}
              >
                <Icon className="w-3.5 h-3.5" />
                {automationRunning === kind ? '执行中...' : label}
              </button>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
          <div className="rounded-2xl border border-slate-800 bg-slate-950/30 p-5 space-y-2">
            <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">数据新鲜度</p>
            <div className={cn("text-2xl font-black", statusTone(freshness?.status))}>
              {freshness?.score?.toFixed(1) ?? '--'}%
            </div>
            <p className="text-xs text-slate-400">
              目标 {freshness?.target_date || '--'} · {freshness?.status || 'unknown'}
            </p>
            <p className="text-[10px] text-slate-500">
              A股 {freshness?.a_share?.fresh_count ?? 0}/{freshness?.a_share?.checked_count ?? 0} · ETF {freshness?.etf?.fresh_count ?? 0}/{freshness?.etf?.checked_count ?? 0}
            </p>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-950/30 p-5 space-y-2">
            <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">调度器</p>
            <div className={cn("text-lg font-black", automationStatus?.scheduler?.running ? "text-emerald-400" : "text-amber-400")}>
              {automationStatus?.scheduler?.enabled ? (automationStatus.scheduler.running ? '运行中' : '已启用') : '未启用'}
            </div>
            <p className="text-xs text-slate-400">
              下次 {nextJob ? `${nextJob.work_type || nextJob.job_type} · ${nextJob.run_at.slice(5, 16).replace('T', ' ')}` : '--'}
            </p>
            <p className="text-[10px] text-slate-500">
              最近任务 {latestRun ? `${latestRun.job_type} / ${latestRun.status}` : '暂无'}
            </p>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-950/30 p-5 space-y-2">
            <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">盘中快照</p>
            <div className="text-lg font-black text-cyan-400">{latestSnapshot?.row_count ?? 0} 条</div>
            <p className="text-xs text-slate-400">{latestSnapshot?.captured_at || '尚未抓取'}</p>
            <p className="text-[10px] text-slate-500">{latestSnapshot?.source || '--'} · {latestSnapshot?.market_session || '--'}</p>
          </div>

          <div className="rounded-2xl border border-slate-800 bg-slate-950/30 p-5 space-y-2">
            <p className="text-[10px] font-black text-slate-500 uppercase tracking-widest">AI 决策</p>
            <div className={cn("text-lg font-black", statusTone(latestDecision?.status))}>
              {latestDecision?.status || '暂无'}
            </div>
            <p className="text-xs text-slate-400 line-clamp-2">{latestDecision?.summary || '等待外部 AI 或本地 guardrail 产生日报。'}</p>
            <p className="text-[10px] text-slate-500">
              {latestDecision?.actions?.map((action) => action.type).filter(Boolean).join(' · ') || '--'}
            </p>
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-950/30 overflow-hidden">
          <div className="flex items-center justify-between gap-4 px-5 py-4 border-b border-slate-800/70">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center">
                <Bot className="w-4 h-4 text-cyan-300" />
              </div>
              <div>
                <h4 className="text-sm font-black text-white">AI 消息入口</h4>
                <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">每次操作 · 时间 · 内容 · 结果</p>
              </div>
            </div>
            <div className={cn("text-xs font-black", statusTone(latestWorkLog?.status))}>
              {latestMessage ? `${latestMessage.work_type} / ${latestMessage.status}` : '暂无消息'}
            </div>
          </div>
          <div className="divide-y divide-slate-800/60">
            {(automationStatus?.ai_work_messages || []).slice(0, 12).map((message) => (
              <div key={message.message_id} className="px-5 py-4 grid grid-cols-1 lg:grid-cols-[210px_1fr_240px] gap-3 text-xs">
                <div>
                  <div className="font-black text-slate-200">{message.title || `${message.action_type || 'AI 动作'} / ${message.status}`}</div>
                  <div className="mt-1 font-mono text-[10px] text-slate-500">
                    {formatAutomationTime(message.created_at)} · {message.trigger || '--'}
                  </div>
                </div>
                <div className="text-slate-300 leading-5">
                  {message.body || 'AI 已记录一次操作。'}
                </div>
                <div className="flex flex-wrap gap-2 lg:justify-end">
                  <span className={cn("px-2.5 py-1 rounded-lg border text-[10px] font-black", messageTone(message))}>
                    {message.status}
                  </span>
                  <span className="px-2.5 py-1 rounded-lg border border-slate-700 bg-slate-900/60 text-[10px] font-black text-slate-400">
                    {message.work_type}
                  </span>
                  {message.action_type && (
                    <span className="px-2.5 py-1 rounded-lg border border-slate-700 bg-slate-900/60 text-[10px] font-black text-slate-400">
                      {message.action_type}
                    </span>
                  )}
                </div>
              </div>
            ))}
            {!(automationStatus?.ai_work_messages || []).length && (
              <div className="px-5 py-6 text-xs text-slate-500">
                等待 AI 首次运行。之后每一次动作都会在这里按时间记录，包括执行内容、状态和摘要。
              </div>
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-slate-800 bg-slate-950/30 overflow-hidden">
          <div className="flex items-center justify-between gap-4 px-5 py-4 border-b border-slate-800/70">
            <div>
              <h4 className="text-sm font-black text-white">AI 托管任务总结</h4>
              <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">一轮任务完成后的汇总记录</p>
            </div>
            <div className={cn("text-xs font-black", statusTone(latestWorkLog?.status))}>
              {latestWorkLog ? `${latestWorkLog.work_type} / ${latestWorkLog.status}` : '暂无托管日志'}
            </div>
          </div>
          <div className="divide-y divide-slate-800/60">
            {(automationStatus?.ai_work_logs || []).slice(0, 5).map((log) => (
              <div key={log.work_id} className="px-5 py-4 grid grid-cols-1 lg:grid-cols-[190px_1fr_220px] gap-3 text-xs">
                <div>
                  <div className="font-black text-slate-200">{log.title || log.work_type}</div>
                  <div className="mt-1 font-mono text-[10px] text-slate-500">
                    {formatAutomationTime(log.started_at)} · {log.trigger || '--'}
                  </div>
                </div>
                <div className="text-slate-300 leading-5">
                  {log.summary || log.error || '任务已记录，等待总结。'}
                </div>
                <div className="flex flex-wrap gap-2 lg:justify-end">
                  {(log.work_items || []).slice(0, 4).map((item, index) => (
                    <span
                      key={`${log.work_id}-${item.action || index}`}
                      className={cn(
                        "px-2.5 py-1 rounded-lg border text-[10px] font-black",
                        item.status === 'executed' || item.status === 'planned'
                          ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-300"
                          : item.status === 'failed' || item.status === 'rejected'
                            ? "border-rose-500/20 bg-rose-500/10 text-rose-300"
                            : "border-slate-700 bg-slate-900/60 text-slate-400"
                      )}
                    >
                      {item.action || 'action'} · {item.status || '--'}
                    </span>
                  ))}
                </div>
              </div>
            ))}
            {!(automationStatus?.ai_work_logs || []).length && (
              <div className="px-5 py-6 text-xs text-slate-500">
                等待 AI 托管任务首次运行，完成后会在这里按轮次记录工作总结。
              </div>
            )}
          </div>
        </div>

        {latestProblemRun && (
          <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 px-5 py-4 text-xs text-amber-100">
            最近未恢复异常：{latestProblemRun.job_type} / {latestProblemRun.status}
            {latestProblemRun.started_at ? ` · ${formatAutomationTime(latestProblemRun.started_at)}` : ''}
            {latestProblemRun.error ? ` · ${latestProblemRun.error}` : ''}
          </div>
        )}
      </section>
      )}

      {/* 策略网格 */}
      {activeSection === 'strategies' && (
      <section className="space-y-6">
        <div className="flex items-center justify-between px-2">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-blue-500/10 border border-blue-500/20">
              <Briefcase className="w-5 h-5 text-blue-400" />
            </div>
            <div>
              <h3 className="text-2xl font-black text-white">策略账户</h3>
              <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mt-0.5">收益排行 · 持仓概览 · 净值详情</p>
            </div>
          </div>
        </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
        {accounts.map((acc, index) => {
          const isIntraday = acc.valuation_source === 'intraday_snapshot';
          const coverageText = `${Math.round((acc.snapshot_coverage || 0) * 100)}%`;
          return (
          <div 
            key={acc.strategy_id}
            onClick={() => fetchDetails(acc)}
            className="group relative rounded-[2.5rem] p-8 border border-slate-800 hover:border-blue-500/40 bg-slate-900/40 hover:bg-slate-900/70 transition-all duration-500 cursor-pointer overflow-hidden shadow-2xl hover:-translate-y-2"
          >
            {/* 排名标识 */}
            <div className="absolute top-6 right-8 flex flex-col items-end">
              <span className="text-[54px] font-black text-white/5 group-hover:text-blue-500/10 transition-colors leading-none">#{index + 1}</span>
              {index === 0 && <Trophy className="w-6 h-6 text-amber-500 mt-1 animate-pulse" />}
            </div>

            <div className="relative z-10 space-y-8">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-2xl bg-blue-500/10 flex items-center justify-center border border-blue-500/20 group-hover:bg-blue-600 group-hover:text-white transition-all duration-500">
                  <Briefcase className="w-6 h-6" />
                </div>
                <div>
                  <h3 className="text-xl font-black text-slate-100">{acc.name}</h3>
                  <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">{acc.strategy_id}</div>
                  {isIntraday && (
                    <div className="mt-2 inline-flex items-center gap-2 rounded-lg border border-cyan-500/20 bg-cyan-500/10 px-2.5 py-1 text-[10px] font-black text-cyan-200">
                      <Activity className="h-3 w-3" />
                      盘中估值 {formatAutomationTime(acc.valuation_time)} · 覆盖 {coverageText}
                    </div>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-8">
                <div className="space-y-2">
                  <p className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">{isIntraday ? '盘中总值' : '账户总值'}</p>
                  <p className="text-2xl font-black text-white">¥{acc.total_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                  {isIntraday && acc.eod_total_value != null && (
                    <p className="text-[10px] font-bold text-slate-500">昨收估值 ¥{acc.eod_total_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}</p>
                  )}
                </div>
                <div className="space-y-2">
                  <p className="text-[10px] font-black text-slate-500 uppercase tracking-[0.2em]">{isIntraday ? '盘中回报' : '累计回报'}</p>
                  <div className={cn("text-2xl font-black flex items-center gap-1.5", acc.return_rate >= 0 ? "text-emerald-400" : "text-rose-400")}>
                    {acc.return_rate >= 0 ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
                    {acc.return_rate.toFixed(2)}%
                  </div>
                  {isIntraday && acc.eod_return_rate != null && (
                    <p className="text-[10px] font-bold text-slate-500">昨收 {acc.eod_return_rate.toFixed(2)}%</p>
                  )}
                </div>
              </div>

              <div className="pt-6 border-t border-slate-800/50 space-y-4">
                <div className="flex justify-between items-center">
                  <div className="flex items-center gap-2">
                    <PieChart className="w-3.5 h-3.5 text-slate-500" />
                    <span className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">核心持仓</span>
                  </div>
                  <span className="text-[10px] font-black text-slate-400">现金: ¥{(acc.cash / 1000).toFixed(1)}k</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {(acc.top_holding_details?.length ? acc.top_holding_details.slice(0, 3) : acc.top_holdings.map((code) => ({ symbol: code, name: code }))).map(holding => (
                    <span key={holding.symbol} className="px-3 py-1.5 rounded-xl bg-blue-500/5 border border-blue-500/10 text-[10px] font-black text-blue-400 group-hover:bg-blue-500/20 group-hover:border-blue-500/30 transition-all">
                      {holding.name && holding.name !== holding.symbol ? holding.name : holding.symbol}
                    </span>
                  ))}
                  {acc.top_holdings.length === 0 && <span className="text-[10px] font-bold text-slate-600 italic py-1">当前空仓等待信号</span>}
                </div>
              </div>
            </div>
          </div>
          );
        })}
      </div>
      </section>
      )}

      {/* 交易历史列表 */}
      {activeSection === 'flow' && (
      <div className="space-y-6">
        <div className="flex items-center justify-between px-2">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-indigo-500/10 border border-indigo-500/20">
              <History className="w-5 h-5 text-indigo-400" />
            </div>
            <div>
              <h3 className="text-2xl font-black text-white">实时交易流水</h3>
              <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mt-0.5">全场调仓动态实况</p>
            </div>
          </div>
        </div>

        <div className="rounded-[2.5rem] border border-slate-800 bg-slate-900/40 overflow-hidden backdrop-blur-xl shadow-2xl">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/60">
                <th className="px-8 py-5 text-[10px] font-black text-slate-500 uppercase tracking-widest">交易日期</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-500 uppercase tracking-widest">所属策略</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-500 uppercase tracking-widest">标的代码</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-500 uppercase tracking-widest">动作</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-500 uppercase tracking-widest text-right">价格</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-500 uppercase tracking-widest text-right">股数</th>
                <th className="px-8 py-5 text-[10px] font-black text-slate-500 uppercase tracking-widest">备注说明</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/30">
              {history.slice(0, 15).map((trade) => (
                <tr key={trade.id} className="hover:bg-white/5 transition-colors group">
                  <td className="px-8 py-5 font-mono text-xs text-slate-400">{trade.date}</td>
                  <td className="px-8 py-5 text-xs font-black text-blue-400">{trade.strategy_id}</td>
                  <td className="px-8 py-5 text-xs font-black text-slate-100">{trade.symbol}</td>
                  <td className="px-8 py-5">
                    <span className={cn(
                      "px-3 py-1 rounded-full text-[10px] font-black uppercase",
                      trade.side === 'BUY' ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20" : "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                    )}>
                      {trade.side === 'BUY' ? '买入' : '卖出'}
                    </span>
                  </td>
                  <td className="px-8 py-5 text-right font-mono text-xs font-bold text-slate-200">¥{trade.price.toFixed(2)}</td>
                  <td className="px-8 py-5 text-right font-mono text-xs font-bold text-slate-200">{trade.shares}</td>
                  <td className="px-8 py-5 text-[10px] text-slate-500 font-medium italic">{trade.msg}</td>
                </tr>
              ))}
              {history.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-8 py-20 text-center">
                    <div className="flex flex-col items-center gap-4 opacity-20">
                      <Zap className="w-12 h-12 text-slate-500" />
                      <p className="text-sm font-bold uppercase tracking-widest">暂无交易记录，等待第一个信号触发</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      )}

      {/* 策略详情弹窗/抽屉 */}
      {selectedStrategy && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-slate-950/60 backdrop-blur-sm animate-in fade-in duration-300">
          <div className="w-full max-w-4xl h-full max-h-[90vh] bg-slate-900 border border-slate-800 rounded-[3rem] shadow-2xl overflow-hidden flex flex-col animate-in zoom-in-95 duration-500">
            {/* 头部 */}
            <div className="p-8 border-b border-slate-800 flex justify-between items-center bg-slate-950/40">
              <div className="flex items-center gap-4">
                <div className="w-12 h-12 rounded-2xl bg-blue-500/10 flex items-center justify-center border border-blue-500/20">
                  <Target className="w-6 h-6 text-blue-400" />
                </div>
                <div>
                  <h3 className="text-2xl font-black text-white">{selectedStrategy.name} 详情报告</h3>
                  <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">{selectedStrategy.strategy_id}</p>
                </div>
              </div>
              <button 
                onClick={() => {
                  detailsRequestRef.current += 1;
                  setSelectedStrategy(null);
                  setEquityHistory([]);
                  setPerfStats(null);
                }}
                className="p-3 rounded-full hover:bg-white/5 transition-colors text-slate-400 hover:text-white"
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-8 space-y-10 custom-scrollbar">
              {/* 核心指标卡片 */}
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                {[
                  { label: "累计收益", val: `${selectedStrategy.return_rate.toFixed(2)}%`, icon: TrendingUp, color: "text-emerald-400" },
                  { label: "夏普比率", val: perfStats?.sharpe_ratio.toFixed(2) || "N/A", icon: Activity, color: "text-blue-400" },
                  { label: "最大回撤", val: `${perfStats?.max_drawdown.toFixed(2) || 0}%`, icon: Shield, color: "text-rose-400" },
                  { label: "年化收益", val: `${perfStats?.annualized_return.toFixed(2) || 0}%`, icon: BarChart3, color: "text-indigo-400" },
                  { label: "胜率", val: `${perfStats?.win_rate.toFixed(1) || 0}%`, icon: Zap, color: "text-amber-400" },
                  { label: "波动率", val: `${perfStats?.volatility.toFixed(1) || 0}%`, icon: PieChart, color: "text-slate-400" },
                ].map((item, i) => (
                  <div key={i} className="p-5 rounded-3xl bg-slate-800/30 border border-slate-800">
                    <div className="flex items-center gap-2 mb-2">
                      <item.icon className={cn("w-3.5 h-3.5", item.color)} />
                      <span className="text-[9px] font-black text-slate-500 uppercase tracking-widest">{item.label}</span>
                    </div>
                    <div className={cn("text-lg font-black", item.color)}>{item.val}</div>
                  </div>
                ))}
              </div>

              {/* 净值曲线图 */}
              <div className="space-y-4">
                <div className="flex items-center gap-2">
                  <BarChart3 className="w-4 h-4 text-blue-500" />
                  <h4 className="text-sm font-black text-white uppercase tracking-widest">历史净值曲线</h4>
                </div>
                <div className="h-[350px] w-full rounded-[2rem] bg-slate-950/40 border border-slate-800 p-4">
                  {detailsLoading ? (
                    <div className="h-full flex items-center justify-center">
                      <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                    </div>
                  ) : equityHistory.length > 0 ? (
                    <EChart option={getEquityOption()} style={{ height: '100%', width: '100%' }} />
                  ) : (
                    <div className="h-full flex items-center justify-center text-slate-600 text-xs font-bold italic">
                      暂无足够的历史净值数据进行绘图，请先执行今日模拟同步数据。
                    </div>
                  )}
                </div>
              </div>

              {/* 当前持仓 */}
              <div className="space-y-4">
                <div className="flex items-center gap-2">
                  <Briefcase className="w-4 h-4 text-emerald-500" />
                  <h4 className="text-sm font-black text-white uppercase tracking-widest">当前仓位详情</h4>
                </div>
                <div className="grid grid-cols-1 gap-3">
                  {detailsError && (
                    <div className="rounded-2xl border border-rose-500/20 bg-rose-500/10 p-4 text-xs font-semibold text-rose-100">
                      {detailsError}
                    </div>
                  )}
                  {(selectedStrategy.top_holding_details?.length ?? 0) > 0 ? selectedStrategy.top_holding_details!.map((holding) => (
                    <div key={holding.symbol} className="flex justify-between items-center p-4 rounded-2xl bg-slate-800/20 border border-slate-800">
                      <div className="flex items-center gap-3">
                        <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                        <div>
                          <span className="text-xs font-black text-slate-100">{holding.name && holding.name !== holding.symbol ? holding.name : holding.symbol}</span>
                          <div className="text-[10px] font-mono text-slate-500 mt-0.5">{holding.symbol} · {holding.shares.toLocaleString()} 股</div>
                        </div>
                      </div>
                      <div className="flex items-center gap-6">
                        <div className="text-right">
                          <p className="text-[8px] font-bold text-slate-500 uppercase">当前占比</p>
                          <p className="text-xs font-black text-slate-300">{(holding.weight * 100).toFixed(1)}%</p>
	                          <p className="mt-1 text-[10px] font-mono text-slate-500">
                              ¥{holding.current_price.toFixed(2)}
                              {selectedStrategy.valuation_source === 'intraday_snapshot' && holding.eod_price != null && holding.eod_price !== holding.current_price
                                ? ` · 昨收 ${holding.eod_price.toFixed(2)}`
                                : ''}
                            </p>
                        </div>
                        <ArrowRightLeft className="w-3.5 h-3.5 text-slate-700" />
                      </div>
                    </div>
                  )) : (
                    <div className="p-8 text-center text-slate-600 text-xs font-bold italic bg-slate-800/10 rounded-2xl border border-dashed border-slate-800">
                      目前处于空仓观望状态
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tailwind Marquee Keyframes */}
      <style>{`
        @keyframes marquee {
          0% { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
        .animate-marquee {
          display: flex;
          animation: marquee 40s linear infinite;
        }
        .animate-marquee:hover {
          animation-play-state: paused;
        }
        .custom-scrollbar::-webkit-scrollbar {
          width: 6px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: #1e293b;
          border-radius: 10px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: #334155;
        }
      `}</style>
    </div>
  );
}
