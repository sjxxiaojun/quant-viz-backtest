import { ArrowUpRight } from 'lucide-react';
import type { TerminalStatus } from '../hooks/useTerminalStatus';
import type { AppView } from '../hooks/useView';
import { Panel } from './ui';
export function MarketOverview({
  status,
  error,
  navigate,
}: {
  status: TerminalStatus | null;
  error: string | null;
  navigate: (view: AppView) => void;
}) {
  const cards = [
    ['缓存截至日', status?.data_as_of ?? '待验证', '以实际行情记录为准'],
    [
      '最近完成交易日',
      status?.target_date ?? '日历待验证',
      status ? status.calendar_error ?? '已验证交易日历' : '正在检查交易日历',
    ],
    [
      '研究计算槽',
      `${status?.active_jobs ?? 0} 个任务 · 2 个槽位`,
      '任务持久化，可取消与重放',
    ],
  ];
  return (
    <div className="space-y-5">
      <div className="flex items-end justify-between">
        <div>
          <p className="label-caps mb-2">MARKET & RESEARCH</p>
          <h2 className="text-xl font-semibold text-slate-100">
            从行情到研究证据
          </h2>
          <p className="mt-2 text-xs text-slate-500">
            查看缓存新鲜度，冻结数据，再比较策略的收益与风险。
          </p>
        </div>
        <button className="terminal-button" onClick={() => navigate('console')}>
          开始回测 <ArrowUpRight size={14} />
        </button>
      </div>
      {error && (
        <p
          role="alert"
          className="rounded-md border border-amber-500/20 bg-amber-500/5 p-3 text-xs text-amber-300"
        >
          {error}
        </p>
      )}
      <div className="grid gap-3 md:grid-cols-3">
        {cards.map(([label, value, note]) => (
          <Panel key={label} className="p-4">
            <span className="text-xs text-slate-500">{label}</span>
            <p className="num mt-4 text-lg text-slate-100">{value}</p>
            <p className="mt-2 text-[10px] leading-5 text-slate-500">{note}</p>
          </Panel>
        ))}
      </div>
      <Panel padded={false}>
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h3 className="text-sm font-semibold">观察池 · 历史行情</h3>
          <span className="text-[10px] text-slate-500">
            缓存快照 · 非实时行情
          </span>
        </div>
        <div className="overflow-auto">
          <table className="terminal-table">
            <thead>
              <tr>
                <th>标的</th>
                <th>代码</th>
                <th>收盘价</th>
                <th>当日涨跌</th>
                <th>行情日期</th>
                <th>数据状态</th>
              </tr>
            </thead>
            <tbody>
              {status?.rows.map((row) => (
                <tr key={row.symbol}>
                  <td className="text-slate-200">{row.name}</td>
                  <td className="num text-slate-500">{row.symbol}</td>
                  <td className="num">{row.close.toFixed(3)}</td>
                  <td
                    className={`num ${row.pct_chg != null && row.pct_chg >= 0 ? 'text-up-soft' : 'text-down-soft'}`}
                  >
                    {row.pct_chg == null
                      ? '—'
                      : `${row.pct_chg > 0 ? '+' : ''}${row.pct_chg.toFixed(2)}%`}
                  </td>
                  <td className="num">{row.date}</td>
                  <td>
                    <span
                      className={
                        status.target_date && row.date < status.target_date
                          ? 'text-amber-400'
                          : 'text-slate-500'
                      }
                    >
                      {status.target_date
                        ? row.date < status.target_date
                          ? '缓存待更新'
                          : '覆盖目标日'
                        : '日期待核验'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!status?.rows.length && (
          <p className="p-8 text-center text-xs text-slate-500">
            没有可展示的缓存行情，请在“数据与任务”检查数据来源。
          </p>
        )}
      </Panel>
      <div className="grid gap-3 md:grid-cols-2">
        <button
          className="panel p-5 text-left hover:border-accent/30"
          onClick={() => navigate('factorLab')}
        >
          <p className="label-caps mb-2">EXPERIMENTS</p>
          <h3 className="text-sm text-slate-200">
            因子与参数实验 <span className="float-right text-blue-400">↗</span>
          </h3>
          <p className="mt-2 text-xs leading-6 text-slate-500">
            按历史窗口训练，在验证期选择，再检查独立测试期。
          </p>
        </button>
        <button
          className="panel p-5 text-left hover:border-accent/30"
          onClick={() => navigate('tasks')}
        >
          <p className="label-caps mb-2">DATA & PROVENANCE</p>
          <h3 className="text-sm text-slate-200">
            任务历史与数据诊断{' '}
            <span className="float-right text-blue-400">↗</span>
          </h3>
          <p className="mt-2 text-xs leading-6 text-slate-500">
            恢复结果、比较实验、导出完整成交，并核对数据缺口。
          </p>
        </button>
      </div>
    </div>
  );
}
