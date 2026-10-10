import { useCallback, useEffect, useState } from 'react';
import { apiGet, apiPost, getApiErrorMessage, API_BASE } from '../api/client';
import { Panel } from './ui';
import type { ApiSchemas } from '../api/schema.generated';

type Job = ApiSchemas['JobView'];
type Diagnostics = { target_date: string | null; calendar_error: string | null; note: string; groups: Record<string, { total_local: number; checked_count: number; fresh_count: number | null; sample_latest_date: string | null; stale_symbols_sample: string[] }> };
const labels: Record<string, string> = { queued: '等待计算', running: '计算中', succeeded: '完成', failed: '失败', interrupted: '服务重启中断', canceled: '已取消' };

export function ResearchTasks() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [data, setData] = useState<Diagnostics | null>(null);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [comparison, setComparison] = useState<unknown[]>([]);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const values = await apiGet<Job[]>('/api/research/jobs', { signal, timeout: 10000 });
      if (!Array.isArray(values)) throw new Error('任务列表格式无效');
      setJobs(values); setError('');
    } catch (e) { if (!signal?.aborted) setError(getApiErrorMessage(e, '任务加载失败')); }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    const initial = setTimeout(() => void refresh(controller.signal), 0);
    void apiGet<Diagnostics>('/api/data/diagnostics', { signal: controller.signal, timeout: 30000 }).then(setData).catch(e => { if (!controller.signal.aborted) setError(getApiErrorMessage(e, '数据诊断失败')); });
    const timer = setInterval(() => void refresh(controller.signal), 3000);
    return () => { controller.abort(); clearTimeout(initial); clearInterval(timer); };
  }, [refresh]);
  const cancel = async (id: string) => {
    try { await apiPost(`/api/research/jobs/${id}/cancel`); await refresh(); }
    catch (e) { setError(getApiErrorMessage(e, '取消失败')); }
  };
  const retry = async (job: Job) => {
    try {
      const endpoint = job.kind === 'factor_lab' ? '/api/factor-lab/jobs' : job.kind === 'compare' ? '/api/backtest/compare/jobs' : '/api/backtest/jobs';
      await apiPost(endpoint, job.request); await refresh();
    } catch (e) { setError(getApiErrorMessage(e, '重新提交失败')); }
  };
  const compare = async () => {
    try {
      const values = await Promise.all(selected.map(id => apiGet<Record<string, unknown>>(`/api/research/jobs/${id}/result`)));
      setComparison(values.map((v, i) => ({ job_id: selected[i], summary: v.summary, data_as_of: v.data_as_of, data_snapshot_id: v.data_snapshot_id, engine_version: v.engine_version, strategy_backtests: v.strategy_backtests })));
    } catch (e) { setError(getApiErrorMessage(e, '历史对比失败')); }
  };
  return <div className="space-y-6">
    <Panel><h2 className="text-xl font-bold">数据与任务</h2><p className="text-sm text-slate-400">两个计算槽 · 完整历史结果 · 服务重启后中断任务可重新提交</p>
      {error && <p role="alert" className="mt-3 text-rose-300">{error}</p>}
      <button className="mt-3 text-blue-300" onClick={() => void refresh()}>刷新任务 / 重试</button>
    </Panel>
    <Panel><h3 className="font-bold">行情截至日</h3><p>最近完成交易日：{data?.target_date ?? '待验证'}</p>
      {data?.calendar_error && <p className="text-amber-300">{data.calendar_error}</p>}
      {Object.entries(data?.groups ?? {}).map(([key, group]) => <div key={key} className="mt-3 rounded border border-slate-700 p-3">
        <b>{key === 'a_share' ? 'A股' : 'ETF'}</b>：{group.total_local} 个本地标的 · 抽样最新日期 {group.sample_latest_date ?? '缺失'}
        <p className="text-sm text-slate-400">检查 {group.checked_count} 个；达标 {group.fresh_count ?? '未确定'} 个；过期或缺失 {group.stale_symbols_sample.join('、') || '无'}</p>
      </div>)}<p className="mt-3 text-xs text-slate-500">{data?.note}</p>
    </Panel>
    <Panel><div className="flex justify-between"><h3 className="font-bold">研究与回测历史</h3><button disabled={selected.length < 2} onClick={() => void compare()} className="text-blue-300 disabled:opacity-30">对比选中的结果</button></div>
      {jobs.length === 0 && <p className="mt-4 text-slate-400">还没有持久化任务。完成一次回测或因子研究后会出现在这里。</p>}
      {jobs.map(job => <div key={job.job_id} className="mt-3 rounded border border-slate-700 p-3 text-sm">
        <div className="flex flex-wrap gap-3"><input aria-label={`选择 ${job.job_id}`} type="checkbox" disabled={job.status !== 'succeeded'} checked={selected.includes(job.job_id)} onChange={e => setSelected(prev => e.target.checked ? [...prev, job.job_id] : prev.filter(id => id !== job.job_id))}/>
          <b>{job.kind}</b><span>{labels[job.status] ?? job.status} · {job.stage}</span><time>{new Date(job.created_at * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}</time>
          {['failed', 'interrupted', 'canceled'].includes(job.status) && <button onClick={() => void retry(job)} className="text-blue-300">重新提交</button>}
          {['queued', 'running'].includes(job.status) && <button onClick={() => void cancel(job.job_id)} className="text-rose-300">取消任务</button>}
          {job.status === 'succeeded' && <><a className="text-blue-300" href={`#${job.kind === 'factor_lab' ? 'factorLab' : job.kind === 'compare' ? 'compare' : 'console'}?job=${job.job_id}`}>打开结果</a><a className="text-blue-300" href={`${API_BASE}/api/research/jobs/${job.job_id}/trades.csv`}>导出成交</a></>}
        </div><p className="mt-2 text-slate-500">{job.job_id}</p>{job.error && <p className="text-rose-300">{job.error}</p>}
      </div>)}
      {comparison.length > 0 && <pre className="mt-4 overflow-auto rounded bg-slate-950 p-4 text-xs">{JSON.stringify(comparison, null, 2)}</pre>}
    </Panel>
  </div>;
}
