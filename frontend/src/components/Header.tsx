import {
  Activity,
  ArrowLeftRight,
  CandlestickChart,
  Database,
  FlaskConical,
  Layers,
  LineChart,
  Wallet,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../utils';
import type { AppView } from '../hooks/useView';
import type { TerminalStatus } from '../hooks/useTerminalStatus';
const primary = [
  ['market', '行情概览', CandlestickChart],
  ['console', '策略回测', LineChart],
  ['compare', '策略比较', ArrowLeftRight],
  ['factorLab', '因子实验', FlaskConical],
  ['virtualTrade', '模拟账户', Wallet],
  ['tasks', '数据与任务', Database],
] as const;
const tools: [AppView, string][] = [
  ['mall', '策略目录'],
  ['dashboard', '绩效分析'],
  ['dailyReport', '研究日报'],
  ['overnight', '隔夜观察'],
];
export function Header({
  view,
  setView,
  status,
  error,
}: {
  view: AppView;
  setView: (view: AppView) => void;
  status?: TerminalStatus | null;
  error?: string | null;
}) {
  const link = (key: AppView, label: string, icon?: ReactNode) => (
    <a
      key={key}
      href={`#${key}`}
      aria-current={
        view === key || (key === 'factorLab' && view === 'experiment')
          ? 'page'
          : undefined
      }
      onClick={(e) => {
        e.preventDefault();
        setView(key);
      }}
      className={cn(
        'flex shrink-0 items-center gap-3 rounded-md px-3 py-2.5 text-xs transition-colors',
        view === key || (key === 'factorLab' && view === 'experiment')
          ? 'bg-accent/15 text-blue-300 ring-1 ring-accent/20'
          : 'text-slate-400 hover:bg-bg3 hover:text-slate-100',
      )}
    >
      {icon}
      {label}
      {(view === key || (key === 'factorLab' && view === 'experiment')) && (
        <span className="ml-auto h-1.5 w-1.5 rounded-full bg-accent" />
      )}
    </a>
  );
  return (
    <>
      <aside className="fixed left-0 right-0 top-14 z-30 flex overflow-x-auto border-b border-line bg-[#0c1019] lg:inset-y-0 lg:right-auto lg:w-56 lg:flex-col lg:border-r">
        <div className="hidden items-center gap-3 px-5 py-6 lg:flex">
          <span className="rounded-lg bg-blue-500/15 p-2 text-blue-400">
            <Layers size={21} />
          </span>
          <div>
            <h1 className="text-sm font-bold tracking-wide text-slate-100">
              momo quant <span className="text-blue-400">pro</span>
            </h1>
            <p className="mt-1 text-[9px] tracking-[.22em] text-slate-500">
              RESEARCH TERMINAL
            </p>
          </div>
        </div>
        <p className="label-caps hidden px-6 pb-3 lg:block">工作空间</p>
        <nav
          aria-label="主导航"
          className="flex shrink-0 gap-1 px-2 py-2 lg:block lg:space-y-1 lg:px-3 lg:py-0"
        >
          {primary.map(([key, label, Icon]) =>
            link(key, label, <Icon size={16} />),
          )}
        </nav>
        <div className="mx-5 my-6 hidden border-t border-line lg:block" />
        <p className="label-caps hidden px-6 pb-2 lg:block">研究工具</p>
        <nav className="flex shrink-0 gap-1 px-2 py-2 lg:block lg:space-y-1 lg:px-3 lg:py-0">
          {tools.map(([key, label]) => link(key, label))}
        </nav>
        <div className="mt-auto m-4 hidden rounded-md lg:block border border-line bg-bg1 p-3 text-[10px] leading-5 text-slate-500">
          <span className="flex items-center gap-2 text-slate-300">
            <Activity size={12} />
            本地研究环境
          </span>
          日线行情 · 冻结快照 · 可追溯结果
        </div>
      </aside>
      <header className="fixed inset-x-0 top-0 z-20 border-b border-line bg-bg0/95 backdrop-blur lg:left-56">
        <div className="flex h-14 items-center justify-between gap-4 px-4 lg:px-6">
          <div className="flex items-center gap-3">
            <span
              className={cn(
                'h-1.5 w-1.5 rounded-full',
                error
                  ? 'bg-amber-400'
                  : status
                    ? 'bg-emerald-400'
                    : 'bg-slate-600',
              )}
            />
            <span className="text-xs text-slate-300">
              {(view === 'experiment' ? '参数实验' : primary.find(([key]) => key === view)?.[1]) ??
                tools.find(([key]) => key === view)?.[1] ??
                '研究终端'}
            </span>
            <span className="hidden border-l border-line pl-3 text-[10px] text-slate-500 sm:block">
              {error
                ? '连接待恢复'
                : status
                  ? `本地 API · ${status.engine_version}`
                  : '正在连接本地服务'}
            </span>
          </div>
          <div className="flex gap-4 text-[10px] text-slate-500">
            <span className="hidden sm:block">
              行情截至{' '}
              <b className="num font-normal text-slate-300">
                {status?.data_as_of ?? '待验证'}
              </b>
            </span>
            <span>
              计算任务{' '}
              <b className="num text-blue-300">{status?.active_jobs ?? '—'}</b>{' '}
              / 2 槽
            </span>
          </div>
        </div>
      </header>
    </>
  );
}
