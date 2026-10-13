import { useMemo, useState } from 'react';
import { EChart } from '../EChart';
import { Panel } from '../ui';
import { metrics, pct, type ComparisonEntry } from './comparison';
export function ComparisonPanel({ entries }: { entries: ComparisonEntry[] }) {
  const [mode, setMode] = useState<'equity' | 'drawdown'>('equity');
  const option = useMemo(
    () => ({
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis' },
      legend: { top: 0, textStyle: { color: '#94a3b8' }, type: 'scroll' },
      grid: { left: 65, right: 25, top: 45, bottom: 50 },
      xAxis: { type: 'time', axisLabel: { color: '#64748b' } },
      yAxis: {
        type: 'value',
        axisLabel: {
          color: '#64748b',
          formatter: (v: number) => `${(v * 100).toFixed(0)}%`,
        },
        splitLine: { lineStyle: { color: '#1d2434' } },
      },
      dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 8 }],
      series: entries.map((entry) => ({
        name: entry.label,
        type: 'line',
        showSymbol: false,
        smooth: false,
        data: entry.result.history.map((point) => [
          point.date,
          mode === 'drawdown'
            ? (point.drawdown ?? null)
            : point.total_value / entry.result.summary.initial_capital - 1,
        ]),
      })),
    }),
    [entries, mode],
  );
  if (!entries.length)
    return (
      <Panel>
        <p className="text-xs text-slate-500">所选结果没有可比较的资金曲线。</p>
      </Panel>
    );
  return (
    <div className="space-y-3">
      <Panel padded={false}>
        <div className="border-b border-line px-4 py-3 text-sm font-semibold">
          研究结果比较{' '}
          <span className="ml-3 text-[10px] font-normal text-slate-500">
            不同时间区间及价格口径请分别评估
          </span>
        </div>
        <div className="overflow-auto">
          <table className="terminal-table">
            <thead>
              <tr>
                <th>实验</th>
                <th>扣成本收益</th>
                <th>基准</th>
                <th>超额收益</th>
                <th>最大回撤</th>
                <th>夏普</th>
                <th>换手倍数</th>
                <th>总成本</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => {
                const m = metrics(entry.result);
                return (
                  <tr key={entry.label}>
                    <td>{entry.label}</td>
                    <td className="num">{pct(m.net)}</td>
                    <td className="num">{pct(m.benchmark)}</td>
                    <td className="num">
                      {pct(m.benchmark == null ? null : m.net - m.benchmark)}
                    </td>
                    <td className="num text-down-soft">{pct(m.drawdown)}</td>
                    <td className="num">{m.sharpe.toFixed(3)}</td>
                    <td className="num">{m.turnover?.toFixed(2) ?? '—'}</td>
                    <td className="num">
                      {m.cost?.toLocaleString('zh-CN', {
                        maximumFractionDigits: 2,
                      }) ?? '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel>
        <div className="flex gap-2">
          {(['equity', 'drawdown'] as const).map((key) => (
            <button
              key={key}
              className={`terminal-button ${mode === key ? 'text-blue-300' : ''}`}
              onClick={() => setMode(key)}
            >
              {key === 'equity' ? '累计收益曲线' : '回撤曲线'}
            </button>
          ))}
        </div>
        <EChart option={option} style={{ height: 310 }} />
      </Panel>
    </div>
  );
}
