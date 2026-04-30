import { useState } from 'react';
import { apiGet, apiPost, getApiErrorMessage } from '../api/client';
import { assertBacktestResult, isRecord } from '../api/guards';
import { withAllPoolBudget } from '../config/backtest';
import type { BacktestConfig, BacktestResult } from '../types';

type CompareJobSubmitResponse = {
  job_id: string;
};

type CompareJobStatusResponse = {
  job_id: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | string;
  error?: string | null;
};

export function useCompare() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, BacktestResult> | null>(null);

  const runCompare = async (config: Omit<BacktestConfig, 'factor'>, strategies: string[]) => {
    if (strategies.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const payloadConfig = withAllPoolBudget(config);
      const submit = await apiPost<CompareJobSubmitResponse>('/api/backtest/compare/jobs', {
        ...payloadConfig,
        strategies
      }, { timeout: 15000 });
      const jobId = submit?.job_id;
      if (!jobId) throw new Error('后端未返回 compare job_id');

      const start = Date.now();
      while (true) {
        const status = await apiGet<CompareJobStatusResponse>(`/api/backtest/compare/jobs/${jobId}`, { timeout: 8000 });
        if (status.status === 'succeeded') break;
        if (status.status === 'failed') throw new Error(status.error || '策略对比失败');
        if (Date.now() - start > 8 * 60 * 1000) {
          throw new Error('策略对比运行超时（已超过 8 分钟），请减少策略数量或缩小回测区间');
        }
        await new Promise((r) => setTimeout(r, 1000));
      }

      const payload = await apiGet<unknown>(`/api/backtest/compare/jobs/${jobId}/result`, { timeout: 30000 });
      if (!isRecord(payload)) throw new Error('策略对比结果不是对象');
      setResults(Object.fromEntries(
        Object.entries(payload).map(([key, value]) => [key, assertBacktestResult(value)])
      ));
    } catch (e: unknown) {
      setError(getApiErrorMessage(e, "对比执行失败，请确认后端已启动并有历史数据"));
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return { loading, error, results, runCompare };
}
