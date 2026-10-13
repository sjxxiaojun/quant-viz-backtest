import { useState } from 'react';
import { apiPost, getApiErrorMessage } from '../../api/client';
import type { ApiSchemas } from '../../api/schema.generated';
import { Panel } from '../ui';
type Analysis = ApiSchemas['AnalysisResponse'];
type Proposal = ApiSchemas['ExperimentProposal'];
export function ResearchAssistant({
  selected,
  requests,
  onSubmit,
}: {
  selected: string[];
  requests: Record<string, unknown>;
  onSubmit: (proposal: Proposal) => Promise<void>;
}) {
  const [external, setExternal] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [submitted, setSubmitted] = useState<number[]>([]);
  const analyze = async () => {
    setLoading(true);
    setError('');
    try {
      setAnalysis(
        await apiPost<Analysis>('/api/research/analysis', {
          job_ids: selected,
          use_external: external,
        }),
      );
      setSubmitted([]);
    } catch (e) {
      setError(getApiErrorMessage(e, '结果分析失败'));
    } finally {
      setLoading(false);
    }
  };
  const submit = async (proposal: Proposal, index: number) => {
    setLoading(true);
    setError('');
    try {
      await onSubmit(proposal);
      setSubmitted((prev) => [...prev, index]);
    } catch (e) {
      setError(getApiErrorMessage(e, '建议实验提交失败'));
    } finally {
      setLoading(false);
    }
  };
  return (
    <Panel>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">结果分析助手</h3>
          <p className="mt-1 text-xs text-slate-500">
            选择1至4个完成的任务。默认本地分析；模型仅接收所选结果的参数、指标和诊断。
          </p>
        </div>
        <button
          className="terminal-button"
          disabled={loading || !selected.length || selected.length > 4}
          onClick={() => void analyze()}
        >
          {loading ? '分析中…' : '分析所选结果'}
        </button>
      </div>
      <label className="mt-3 flex gap-2 text-xs text-slate-400">
        <input
          type="checkbox"
          checked={external}
          onChange={(e) => setExternal(e.target.checked)}
        />
        本次调用已配置的外部模型
      </label>
      {error && (
        <p role="alert" className="mt-3 text-xs text-rose-300">
          {error}
        </p>
      )}
      {analysis && (
        <div className="mt-4 space-y-2 text-xs leading-6">
          <span className="text-blue-300">
            {analysis.source === 'external' ? '外部模型分析' : '本地分析'}
          </span>
          <p>{analysis.summary}</p>
          {analysis.error && <p className="text-amber-300">{analysis.error}</p>}
          {analysis.observations?.map((note, index) => (
            <p key={index} className="text-slate-400">
              {note}
            </p>
          ))}
          {analysis.proposals?.map((proposal, index) => (
            <div key={index} className="rounded-md border border-line p-3">
              <p>{proposal.reason}</p>
              <p className="text-slate-500">
                来源任务 {proposal.job_id.slice(0, 8)} · 参数{' '}
                {Object.entries(proposal.changes)
                  .filter(([, v]) => v != null)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(' · ')}
              </p>
              <button
                className="terminal-button mt-2"
                disabled={
                  loading ||
                  submitted.includes(index) ||
                  !requests[proposal.job_id]
                }
                onClick={() => void submit(proposal, index)}
              >
                {submitted.includes(index)
                  ? '已提交实验'
                  : '确认参数并提交实验'}
              </button>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}
