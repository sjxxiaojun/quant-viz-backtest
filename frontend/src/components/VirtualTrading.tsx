import { useCallback, useEffect, useRef, useState } from 'react';
import { Bot, Briefcase, History, Play, type LucideIcon } from 'lucide-react';
import { cn } from '../utils';
import { getApiErrorMessage, isRequestCanceled } from '../api/client';
import { Panel, Skeleton } from './ui';
import type {
  Account,
  AutomationJobKind,
  AutomationStatus,
  EquityPoint,
  PerformanceStats,
  VirtualTrade,
  VirtualTradingSection,
} from './virtual-trading/types';
import {
  AUTOMATION_JOB_LABELS,
  executeDailySimulation,
  fetchAccounts,
  fetchAutomationStatus,
  fetchEquityHistory,
  fetchPerformanceStats,
  fetchTradeHistory,
  runAutomationJob,
} from './virtual-trading/api';
import { TradeTicker } from './virtual-trading/TradeTicker';
import { AutomationPanel } from './virtual-trading/AutomationPanel';
import { AccountGrid } from './virtual-trading/AccountGrid';
import { TradeFlowTable } from './virtual-trading/TradeFlowTable';
import { StrategyDetailModal } from './virtual-trading/StrategyDetailModal';

const FLOW_PAGE_SIZE = 50;
const TICKER_SIZE = 8;

export function VirtualTrading() {
  const [accountVersion, setAccountVersion] = useState<'legacy' | 'v2'>(() => localStorage.getItem('momo:account-version') === 'legacy' ? 'legacy' : 'v2');
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [tickerTrades, setTickerTrades] = useState<VirtualTrade[]>([]);
  const [flowTrades, setFlowTrades] = useState<VirtualTrade[]>([]);
  const [flowPage, setFlowPage] = useState(0);
  const [flowLoading, setFlowLoading] = useState(false);
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
  const [automationRunning, setAutomationRunning] = useState<AutomationJobKind | null>(null);
  const [activeSection, setActiveSection] = useState<VirtualTradingSection>('ai');
  const mountedRef = useRef(false);
  const dataRequestRef = useRef(0);
  const flowRequestRef = useRef(0);
  const detailsRequestRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  // 首屏加载态由 loading 的初始值 true 承担, 这里不再 setLoading(true):
  // 挂载 effect 会同步调用本函数, 在 effect 内同步 setState 会多触发一轮渲染
  // (react-hooks/set-state-in-effect)。需要显示加载态的刷新路径由调用方(事件处理器)
  // 自行 setLoading(true), 结束时统一由下面的 finally 复位。
  const fetchData = useCallback(async () => {
    const requestId = ++dataRequestRef.current;
    const signal = abortRef.current?.signal;
    try {
      const [accData, histData] = await Promise.all([
        fetchAccounts(signal),
        fetchTradeHistory(FLOW_PAGE_SIZE, 0, signal),
      ]);
      if (!mountedRef.current || requestId !== dataRequestRef.current) return;
      setAccounts([...accData].sort((a, b) => b.return_rate - a.return_rate));
      setFlowTrades(histData);
      setFlowPage(0);
      setTickerTrades(histData.slice(0, TICKER_SIZE));
      setError(null);
      try {
        const automation = await fetchAutomationStatus(signal);
        if (!mountedRef.current || requestId !== dataRequestRef.current) return;
        setAutomationStatus(automation);
        setAutomationError(null);
      } catch (automationErr: unknown) {
        if (isRequestCanceled(automationErr)) return;
        if (!mountedRef.current || requestId !== dataRequestRef.current) return;
        setAutomationError(getApiErrorMessage(automationErr, '自动化状态加载失败'));
      }
    } catch (err: unknown) {
      if (isRequestCanceled(err)) return;
      if (!mountedRef.current || requestId !== dataRequestRef.current) return;
      setError(getApiErrorMessage(err, '获取数据失败'));
    } finally {
      if (mountedRef.current && requestId === dataRequestRef.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    abortRef.current = new AbortController();
    void fetchData();
    return () => {
      mountedRef.current = false;
      dataRequestRef.current += 1;
      flowRequestRef.current += 1;
      detailsRequestRef.current += 1;
      abortRef.current?.abort();
    };
  }, [fetchData]);

  const loadFlowPage = async (page: number) => {
    if (page < 0) return;
    const requestId = ++flowRequestRef.current;
    setFlowLoading(true);
    try {
      const trades = await fetchTradeHistory(FLOW_PAGE_SIZE, page * FLOW_PAGE_SIZE, abortRef.current?.signal);
      if (!mountedRef.current || requestId !== flowRequestRef.current) return;
      setFlowTrades(trades);
      setFlowPage(page);
      if (page === 0) setTickerTrades(trades.slice(0, TICKER_SIZE));
    } catch (err: unknown) {
      if (isRequestCanceled(err)) return;
      if (!mountedRef.current || requestId !== flowRequestRef.current) return;
      setError(getApiErrorMessage(err, '交易流水加载失败'));
    } finally {
      if (mountedRef.current && requestId === flowRequestRef.current) {
        setFlowLoading(false);
      }
    }
  };

  const fetchDetails = async (account: Account) => {
    const requestId = ++detailsRequestRef.current;
    setSelectedStrategy(account);
    setEquityHistory([]);
    setPerfStats(null);
    setDetailsError(null);
    setDetailsLoading(true);
    try {
      const signal = abortRef.current?.signal;
      const [equity, stats] = await Promise.all([
        fetchEquityHistory(account.strategy_id, signal),
        fetchPerformanceStats(account.strategy_id, signal),
      ]);
      if (!mountedRef.current || requestId !== detailsRequestRef.current) return;
      setEquityHistory(equity);
      setPerfStats(stats);
    } catch (err: unknown) {
      if (isRequestCanceled(err)) return;
      if (!mountedRef.current || requestId !== detailsRequestRef.current) return;
      setDetailsError(getApiErrorMessage(err, '策略详情加载失败'));
    } finally {
      if (mountedRef.current && requestId === detailsRequestRef.current) {
        setDetailsLoading(false);
      }
    }
  };

  const closeDetails = () => {
    detailsRequestRef.current += 1;
    setSelectedStrategy(null);
    setEquityHistory([]);
    setPerfStats(null);
    setDetailsError(null);
  };

  const runDailyExecution = async () => {
    try {
      setExecuting(true);
      setError(null);
      setNotice(null);
      const data = await executeDailySimulation();
      const skipped =
        Array.isArray(data.skipped_days) && data.skipped_days.length > 0
          ? `，有 ${data.skipped_days.length} 个日期/股票池因数据不足被跳过`
          : '';
      if (!mountedRef.current) return;
      setNotice(`${data.message || '仿真运行完成'}，当前日期 ${data.date || '--'}${skipped}。`);
      setLoading(true);
      await fetchData();
    } catch (err: unknown) {
      if (isRequestCanceled(err)) return;
      if (!mountedRef.current) return;
      setError(getApiErrorMessage(err, '执行失败'));
    } finally {
      if (mountedRef.current) {
        setExecuting(false);
      }
    }
  };

  const handleAutomationJob = async (kind: AutomationJobKind) => {
    try {
      setAutomationRunning(kind);
      setAutomationError(null);
      setNotice(null);
      await runAutomationJob(kind);
      if (!mountedRef.current) return;
      setNotice(`${AUTOMATION_JOB_LABELS[kind]}已完成，审计记录已刷新。`);
      setLoading(true);
      await fetchData();
    } catch (err: unknown) {
      if (isRequestCanceled(err)) return;
      if (!mountedRef.current) return;
      setAutomationError(getApiErrorMessage(err, `${AUTOMATION_JOB_LABELS[kind]}执行失败`));
    } finally {
      if (mountedRef.current) {
        setAutomationRunning(null);
      }
    }
  };

  if (loading && accounts.length === 0) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-8 w-full" />
        <Panel className="space-y-3">
          <Skeleton className="h-5 w-56" />
          <Skeleton className="h-3 w-full max-w-md" />
        </Panel>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-40 w-full" />
          ))}
        </div>
      </div>
    );
  }

  const updateDates = accounts.map((account) => account.last_update).filter(Boolean).sort();
  const firstUpdate = updateDates[0];
  const lastAccountUpdate = updateDates[updateDates.length - 1];
  const lastUpdate =
    firstUpdate && lastAccountUpdate
      ? firstUpdate === lastAccountUpdate
        ? lastAccountUpdate
        : `${firstUpdate} 至 ${lastAccountUpdate}`
      : 'N/A';
  const latestMessage = automationStatus?.ai_work_messages?.[0];
  const tradingSections: Array<{ key: VirtualTradingSection; label: string; Icon: LucideIcon; meta: string }> = [
    { key: 'ai', label: 'AI 运行层', Icon: Bot, meta: latestMessage ? `${latestMessage.work_type}/${latestMessage.status}` : '消息与托管' },
    { key: 'strategies', label: '策略账户', Icon: Briefcase, meta: `${accounts.length} 个账户` },
    { key: 'flow', label: '交易流水', Icon: History, meta: `第 ${flowPage + 1} 页` },
  ];

  return (
    <div className="space-y-3 pb-12">
      <Panel><label>账户口径 <select aria-label="账户口径" className="ml-3 bg-slate-900 p-2" value={accountVersion} onChange={e => {
        const version = e.target.value as 'legacy' | 'v2'; localStorage.setItem('momo:account-version', version); setAccountVersion(version); setSelectedStrategy(null); void fetchData();
      }}><option value="v2">新版日线账户</option><option value="legacy">旧账（保留历史）</option></select></label>
      <p className="mt-2 text-xs text-amber-300">{accountVersion === 'legacy' ? '旧账保持原成本和撮合口径；执行按钮只更新新版账户。' : '数据完整后才创建或推进账户；首次创建为100万元现金，不重算旧账。'}</p></Panel>
      <TradeTicker trades={tickerTrades} />

      {error && (
        <div className="rounded-panel border border-up/30 bg-up/10 px-4 py-2.5 text-xs text-up-soft">
          {error}
        </div>
      )}
      {notice && (
        <div className="rounded-panel border border-ok/30 bg-ok/10 px-4 py-2.5 text-xs text-ok">
          {notice}
        </div>
      )}

      {/* 顶部控制面板 */}
      <Panel className="flex flex-col justify-between gap-3 md:flex-row md:items-center">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base font-semibold text-slate-100">多策略实盘模拟</h2>
            <span className="num rounded-ctl border border-line bg-bg2 px-2 py-0.5 text-[10px] text-slate-400">
              数据日期 {lastUpdate}
            </span>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            仿真账户按历史数据生成持仓，用最新可用收盘价推进净值；每笔模拟成交计入 0.2% 交易摩擦。
          </p>
        </div>
        <button
          type="button"
          onClick={runDailyExecution}
          disabled={executing}
          className={cn(
            'inline-flex shrink-0 items-center gap-2 rounded-ctl px-4 py-2 text-xs font-semibold transition-colors',
            executing
              ? 'cursor-not-allowed bg-bg3 text-slate-500'
              : 'bg-accent text-white hover:bg-accent/85',
          )}
        >
          {executing ? (
            <>
              <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              运行仿真中...
            </>
          ) : (
            <>
              <Play className="h-3.5 w-3.5 fill-current" />
              一键运行仿真
            </>
          )}
        </button>
      </Panel>

      {/* 分区切换 */}
      <nav className="panel flex flex-col gap-1 p-1 sm:flex-row" aria-label="实盘模拟分区">
        {tradingSections.map(({ key, label, Icon, meta }) => {
          const active = activeSection === key;
          return (
            <button
              key={key}
              type="button"
              onClick={() =>

 setActiveSection(key)}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'flex flex-1 items-center justify-between gap-2 rounded-ctl px-3 py-2 text-left transition-colors',
                active ? 'bg-bg3 text-slate-100' : 'text-slate-400 hover:bg-bg2 hover:text-slate-200',
              )}
            >
              <span className="flex items-center gap-2">
                <Icon className={cn('h-3.5 w-3.5', active ? 'text-accent' : 'text-slate-500')} />
                <span className="text-xs font-semibold">{label}</span>
              </span>
              <span className="num text-[10px] text-slate-500">{meta}</span>
            </button>
          );
        })}
      </nav>

      {activeSection === 'ai' && (
        <AutomationPanel
          status={automationStatus}
          error={automationError}
          runningJob={automationRunning}
          onRunJob={(kind) => void handleAutomationJob(kind)}
        />
      )}

      {activeSection === 'strategies' && (
        <AccountGrid accounts={accounts} onSelect={(account) => void fetchDetails(account)} />
      )}

      {activeSection === 'flow' && (
        <TradeFlowTable
          trades={flowTrades}
          page={flowPage}
          pageSize={FLOW_PAGE_SIZE}
          loading={flowLoading}
          onPageChange={(page) => void loadFlowPage(page)}
        />
      )}

      {selectedStrategy && (
        <StrategyDetailModal
          account={selectedStrategy}
          equityHistory={equityHistory}
          stats={perfStats}
          loading={detailsLoading}
          error={detailsError}
          onClose={closeDetails}
        />
      )}
    </div>
  );
}
