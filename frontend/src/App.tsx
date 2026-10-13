import { useTerminalStatus } from './hooks/useTerminalStatus';
import { MarketOverview } from './components/MarketOverview';
const ExperimentWorkbench = lazy(() =>
  import('./components/research/ExperimentWorkbench').then((mod) => ({
    default: mod.ExperimentWorkbench,
  })),
);
import React, { lazy, Suspense, useState } from 'react';
import { Header } from './components/Header';
import { StrategyMall } from './components/StrategyMall';
import { useBacktest } from './hooks/useBacktest';
import { useMarketData } from './hooks/useMarketData';
import { useView } from './hooks/useView';
import { ResultContext } from './components/ResultContext';
const ResearchTasks = lazy(() =>
  import('./components/ResearchTasks').then((mod) => ({
    default: mod.ResearchTasks,
  })),
);
import type { BacktestConfig } from './types';
import {
  coerceRuntimePoolForStrategy,
  getRuntimePoolForStrategy,
} from './config/strategies';

const BacktestConsole = lazy(() =>
  import('./components/BacktestConsole').then((mod) => ({
    default: mod.BacktestConsole,
  })),
);
const KPICards = lazy(() =>
  import('./components/KPICards').then((mod) => ({ default: mod.KPICards })),
);
const EquityCurve = lazy(() =>
  import('./components/EquityCurve').then((mod) => ({
    default: mod.EquityCurve,
  })),
);
const TradeTable = lazy(() =>
  import('./components/TradeTable').then((mod) => ({
    default: mod.TradeTable,
  })),
);
const StatusBadge = lazy(() =>
  import('./components/StatusBadge').then((mod) => ({
    default: mod.StatusBadge,
  })),
);
const Dashboard = lazy(() =>
  import('./components/Dashboard').then((mod) => ({ default: mod.Dashboard })),
);
const StrategyCompare = lazy(() =>
  import('./components/StrategyCompare').then((mod) => ({
    default: mod.StrategyCompare,
  })),
);
const FactorLab = lazy(() =>
  import('./components/FactorLab').then((mod) => ({ default: mod.FactorLab })),
);
const VirtualTrading = lazy(() =>
  import('./components/VirtualTrading').then((mod) => ({
    default: mod.VirtualTrading,
  })),
);
const DailyReport = lazy(() =>
  import('./components/DailyReport').then((mod) => ({
    default: mod.DailyReport,
  })),
);
const OvernightConsole = lazy(() =>
  import('./components/OvernightConsole').then((mod) => ({
    default: mod.OvernightConsole,
  })),
);

const DEFAULT_START_DATE = '2022-01-01';
const DEFAULT_END_DATE = '';

function ViewFallback() {
  return (
    <div className="min-h-[320px] flex items-center justify-center text-sm text-slate-400">
      正在加载工作台...
    </div>
  );
}

export default function App() {
  const [view, setView] = useView();
  const { sysStatus } = useMarketData();
  const { status: terminalStatus, error: terminalError } = useTerminalStatus();

  const [config, setConfig] = useState<BacktestConfig>({
    start_date: DEFAULT_START_DATE,
    end_date: DEFAULT_END_DATE,
    initial_capital: 1000000,
    factor: 'bottom_fishing',
    commission_rate: 0.0003,
    slippage_rate: 0.0003,
    pool: getRuntimePoolForStrategy(),
    max_positions: 5,
    weight_mode: 'equal',
    max_hold_days: undefined,
    stop_loss: -0.08,
    take_profit: undefined,
  });

  const { loading, error, result, runBacktest, setResult } = useBacktest(setConfig);

  const effectiveConfig = {
    ...config,
    end_date: config.end_date || terminalStatus?.default_end_date || '',
  };

  const handleRunFromMall = (factor: string) => {
    setConfig((prev) => ({
      ...prev,
      factor,
      pool: coerceRuntimePoolForStrategy(
        factor,
        prev.pool || getRuntimePoolForStrategy(),
      ),
    }));
    setView('console');
    setResult(null);
  };

  return (
    <div className="min-h-screen bg-bg0 text-slate-200 selection:bg-blue-500/30 lg:pl-56">
      <Header
        view={view}
        setView={setView}
        status={terminalStatus}
        error={terminalError}
      />
      <div className="mx-auto max-w-[1600px] space-y-5 px-4 pb-8 pt-32 lg:px-6 lg:pt-20">
        {view === 'mall' && <StrategyMall onRun={handleRunFromMall} />}

        <Suspense fallback={<ViewFallback />}>
          {view === 'market' && (
            <MarketOverview
              status={terminalStatus}
              error={terminalError}
              navigate={setView}
            />
          )}
          {view === 'tasks' && <ResearchTasks />}
          {view === 'console' && (
            <main className="grid grid-cols-1 lg:grid-cols-12 gap-4 animate-in slide-in-from-right-4 duration-500">
              <div className="lg:col-span-3 space-y-4">
                <BacktestConsole
                  config={effectiveConfig}
                  setConfig={setConfig}
                  onRun={() => runBacktest(effectiveConfig)}
                  onSwitchStrategy={() => setView('mall')}
                  loading={loading}
                />
                <StatusBadge sysStatus={sysStatus} />
              </div>

              <div className="lg:col-span-9 space-y-4">
                {error && (
                  <div className="rounded-2xl border border-rose-500/20 bg-rose-500/10 px-5 py-4 text-sm font-semibold text-rose-100">
                    {error}
                  </div>
                )}
                <ResultContext result={result} />
                <KPICards result={result} />
                <EquityCurve result={result} />
                {result && <TradeTable result={result} />}
              </div>
            </main>
          )}

          {view === 'dashboard' && <Dashboard result={result} />}

          {view === 'compare' && <StrategyCompare config={effectiveConfig} />}

          {(view === 'factorLab' || view === 'experiment') && (
            <div className="space-y-4">
              <div className="flex gap-2">
                <button
                  className="terminal-button"
                  onClick={() => setView('factorLab')}
                >
                  因子研究
                </button>
                <button
                  className="terminal-button"
                  onClick={() => setView('experiment')}
                >
                  参数实验
                </button>
              </div>
              {view === 'experiment' ? (
                <ExperimentWorkbench config={effectiveConfig} />
              ) : (
                <FactorLab
                  defaultEndDate={terminalStatus?.default_end_date ?? ''}
                />
              )}
            </div>
          )}

          {view === 'virtualTrade' && <VirtualTrading />}

          {view === 'dailyReport' && <DailyReport />}

          {view === 'overnight' && <OvernightConsole />}
        </Suspense>
      </div>
    </div>
  );
}
