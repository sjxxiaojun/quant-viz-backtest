import { useCallback, useEffect, useState } from 'react';
import { apiGet, apiPost, getApiErrorMessage } from '../../api/client';
import { pollJobResult } from '../../api/pollJob';
import type { ApiSchemas } from '../../api/schema.generated';
import type { BacktestConfig, BacktestResult } from '../../types';
import { useStrategyCatalog } from '../../hooks/useStrategyCatalog';
import { ComparisonPanel } from './ComparisonPanel';
import { comparisonEntries, pct } from './comparison';
import { Panel } from '../ui';
type Candidate = ApiSchemas['ParameterCandidate'];
type ExperimentResult = {
  winner_candidate_id: number;
  test_result: BacktestResult;
  split: Record<string, string>;
  validation_candidates: {
    candidate_id: number;
    changes: Candidate;
    metrics: { net_return: number; max_drawdown: number };
  }[];
};

export function ExperimentWorkbench({ config }: { config: BacktestConfig }) {
  const [base, setBase] = useState(config);
  const [candidates, setCandidates] = useState<Candidate[]>([
    { stop_loss: -0.05 },
    { stop_loss: -0.08 },
    { stop_loss: -0.12 },
  ]);
  const [result, setResult] = useState<ExperimentResult | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [stage, setStage] = useState('');
  const { catalog } = useStrategyCatalog();
  const recover = useCallback(async (id: string, signal: AbortSignal) => {
    setLoading(true);
    setError('');
    setJobId(id);
    try {
      const meta = await apiGet<{
        kind: string;
        stage: string;
        request: ApiSchemas['ExperimentRequest'];
      }>(`/api/research/jobs/${id}`, { signal });
      if (meta.kind !== 'experiment')
        throw new Error('任务类型与参数实验不匹配');
      setStage(meta.stage);
      setBase({
        ...meta.request.base,
        factor: meta.request.base.factor ?? 'bottom_fishing',
        commission_rate: meta.request.base.commission_rate ?? 0.0003,
        slippage_rate: meta.request.base.slippage_rate ?? 0.0003,
        pool: meta.request.base.pool ?? 'auto',
        max_positions: meta.request.base.max_positions ?? 5,
        weight_mode: meta.request.base.weight_mode ?? 'equal',
        stop_loss: meta.request.base.stop_loss ?? -0.08,
        stocks: meta.request.base.stocks ?? undefined,
        max_symbols: meta.request.base.max_symbols ?? undefined,
        max_hold_days: meta.request.base.max_hold_days ?? undefined,
        take_profit: meta.request.base.take_profit ?? undefined,
        commission_min: meta.request.base.commission_min ?? 5,
        close_slippage_rate: meta.request.base.close_slippage_rate ?? undefined,
      });
      setCandidates(meta.request.candidates);
      const value = await pollJobResult<ExperimentResult>(
        `/api/research/jobs/${id}`,
        `/api/research/jobs/${id}/result`,
        {
          signal,
          timeoutMs: 60 * 60 * 1000,
          onStatus: (state) => setStage(state.stage || state.status),
        },
      );
      if (!signal?.aborted && value) {
        setResult(value);
        setStage('完成');
      }
    } catch (e) {
      if (!signal?.aborted) setError(getApiErrorMessage(e, '参数实验失败'));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, []);
  useEffect(() => {
    let controller = new AbortController();
    const changed = () => {
      const [view, query] = location.hash.slice(1).split('?');
      const id = new URLSearchParams(query).get('job');
      controller.abort();
      controller = new AbortController();
      if (view === 'experiment' && id) void recover(id, controller.signal);
    };
    const timer = setTimeout(changed, 0);
    window.addEventListener('hashchange', changed);
    return () => {
      controller.abort();
      clearTimeout(timer);
      window.removeEventListener('hashchange', changed);
    };
  }, [recover]);
  const effectiveBase = { ...base, end_date: base.end_date || config.end_date };
  const submit = async () => {
    setError('');
    setResult(null);
    setLoading(true);
    try {
      const job = await apiPost<{ job_id: string }>('/api/experiments/jobs', {
        base: effectiveBase,
        candidates,
      });
      location.hash = `experiment?job=${job.job_id}`;
    } catch (e) {
      setError(getApiErrorMessage(e, '实验提交失败'));
      setLoading(false);
    }
  };
  const change = (index: number, patch: Candidate) =>
    setCandidates((prev) =>
      prev.map((value, i) => (i === index ? { ...value, ...patch } : value)),
    );
  return (
    <div className="space-y-4">
      <Panel>
        <div className="flex items-center justify-between">
          <div>
            <p className="label-caps mb-2">PARAMETER EXPERIMENT</p>
            <h2 className="text-base font-semibold">验证选参 · 独立测试</h2>
            <p className="mt-2 text-xs text-slate-500">
              所有候选使用同一份冻结行情。前60%为历史准备，随后20%选择参数，最后20%仅评估胜出配置。
            </p>
          </div>
          <button
            className="terminal-button"
            disabled={
              loading ||
              !base.start_date ||
              !effectiveBase.end_date ||
              base.start_date >= effectiveBase.end_date
            }
            onClick={() => void submit()}
          >
            {loading ? '计算中…' : `运行 ${candidates.length} 组实验`}
          </button>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-4">
          <label className="text-xs text-slate-500">
            策略
            <select
              aria-label="实验策略"
              className="terminal-input mt-1"
              value={base.factor}
              onChange={(e) =>
                setBase({
                  ...base,
                  factor: e.target.value,
                  pool: 'auto',
                  stocks: undefined,
                })
              }
            >
              {catalog?.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-slate-500">
            开始日期
            <input
              aria-label="实验开始日期"
              type="date"
              className="terminal-input mt-1"
              value={base.start_date}
              onChange={(e) => setBase({ ...base, start_date: e.target.value })}
            />
          </label>
          <label className="text-xs text-slate-500">
            结束日期
            <input
              aria-label="实验结束日期"
              type="date"
              className="terminal-input mt-1"
              value={effectiveBase.end_date}
              onChange={(e) => setBase({ ...base, end_date: e.target.value })}
            />
          </label>
          <label className="text-xs text-slate-500">
            自选代码（逗号分隔）
            <input
              aria-label="实验自选代码"
              className="terminal-input mt-1"
              value={base.stocks?.join(',') ?? ''}
              placeholder="留空使用策略股票池"
              onChange={(e) =>
                setBase({
                  ...base,
                  stocks: e.target.value
                    ? e.target.value.split(/[,，\s]+/).filter(Boolean)
                    : undefined,
                  pool: e.target.value ? 'custom' : 'auto',
                })
              }
            />
          </label>
        </div>
        <label className="mt-3 flex gap-2 text-xs text-amber-300">
          <input
            type="checkbox"
            checked={base.price_mode === 'approximate_adjusted'}
            onChange={(e) =>
              setBase({
                ...base,
                price_mode: e.target.checked
                  ? 'approximate_adjusted'
                  : 'strict_raw',
              })
            }
          />
          允许复权价近似研究（默认使用严格未复权成交数据）
        </label>
      </Panel>
      <Panel padded={false}>
        <table className="terminal-table">
          <thead>
            <tr>
              <th>候选</th>
              <th>止损 %</th>
              <th>持仓上限</th>
              <th>持有天数</th>
              <th>止盈 %</th>
              <th>权重</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {candidates.map((candidate, index) => (
              <tr key={index}>
                <td className="num">{index + 1}</td>
                <td>
                  <input
                    aria-label={`候选${index + 1}止损`}
                    type="number"
                    min="-99"
                    max="-0.01"
                    step=".5"
                    className="terminal-input"
                    value={(candidate.stop_loss ?? base.stop_loss) * 100}
                    onChange={(e) =>
                      change(index, { stop_loss: Number(e.target.value) / 100 })
                    }
                  />
                </td>
                <td>
                  <input
                    aria-label={`候选${index + 1}持仓`}
                    type="number"
                    min="1"
                    max="50"
                    className="terminal-input"
                    value={candidate.max_positions ?? base.max_positions}
                    onChange={(e) =>
                      change(index, { max_positions: Number(e.target.value) })
                    }
                  />
                </td>
                <td>
                  <input
                    aria-label={`候选${index + 1}持有天数`}
                    type="number"
                    min="1"
                    max="260"
                    className="terminal-input"
                    placeholder="策略默认"
                    value={candidate.max_hold_days ?? ''}
                    onChange={(e) =>
                      change(index, {
                        max_hold_days: e.target.value
                          ? Number(e.target.value)
                          : null,
                      })
                    }
                  />
                </td>
                <td>
                  <input
                    aria-label={`候选${index + 1}止盈`}
                    type="number"
                    min=".01"
                    step=".5"
                    className="terminal-input"
                    placeholder="策略默认"
                    value={
                      candidate.take_profit == null
                        ? ''
                        : candidate.take_profit * 100
                    }
                    onChange={(e) =>
                      change(index, {
                        take_profit: e.target.value
                          ? Number(e.target.value) / 100
                          : null,
                      })
                    }
                  />
                </td>
                <td>
                  <select
                    aria-label={`候选${index + 1}权重`}
                    className="terminal-input"
                    value={candidate.weight_mode ?? base.weight_mode}
                    onChange={(e) =>
                      change(index, {
                        weight_mode: e.target.value as 'equal' | 'score',
                      })
                    }
                  >
                    <option value="equal">等权</option>
                    <option value="score">分数</option>
                  </select>
                </td>
                <td>
                  <button
                    disabled={candidates.length === 1 || loading}
                    className="terminal-button"
                    onClick={() =>
                      setCandidates((prev) =>
                        prev.filter((_, i) => i !== index),
                      )
                    }
                  >
                    移除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <button
          disabled={candidates.length >= 12 || loading}
          className="terminal-button m-3"
          onClick={() => setCandidates((prev) => [...prev, { ...prev.at(-1) }])}
        >
          添加候选（最多12组）
        </button>
      </Panel>
      {jobId && (
        <Panel>
          <div className="flex justify-between text-xs">
            <span>
              任务 {jobId.slice(0, 8)} · {stage || '等待计算'}
            </span>
            {loading && (
              <button
                className="terminal-button"
                onClick={() =>
                  void apiPost(`/api/research/jobs/${jobId}/cancel`).catch(
                    (e) => setError(getApiErrorMessage(e, '取消失败')),
                  )
                }
              >
                取消任务
              </button>
            )}
            <a href="#tasks" className="text-blue-300">
              打开任务历史
            </a>
          </div>
        </Panel>
      )}
      {error && (
        <p role="alert" className="text-sm text-rose-300">
          {error}
        </p>
      )}
      {result && (
        <>
          <Panel>
            <h3 className="text-sm font-semibold">验证期排名</h3>
            <p className="mt-2 text-xs text-slate-500">
              验证 {result.split.validation_start} 至{' '}
              {result.split.validation_end} · 独立测试 {result.split.test_start}{' '}
              至 {result.split.test_end}
            </p>
            <table className="terminal-table mt-3">
              <thead>
                <tr>
                  <th>候选</th>
                  <th>验证期扣成本收益</th>
                  <th>验证期最大回撤</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                {result.validation_candidates.map((row) => (
                  <tr key={row.candidate_id}>
                    <td>候选 {row.candidate_id + 1}</td>
                    <td className="num">{pct(row.metrics.net_return)}</td>
                    <td className="num">{pct(row.metrics.max_drawdown)}</td>
                    <td>
                      {row.candidate_id === result.winner_candidate_id
                        ? '胜出 · 进入独立测试'
                        : '未进入测试'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
          <ComparisonPanel
            entries={comparisonEntries(
              `候选 ${result.winner_candidate_id + 1} · 独立测试`,
              result.test_result,
            )}
          />
        </>
      )}
    </div>
  );
}
