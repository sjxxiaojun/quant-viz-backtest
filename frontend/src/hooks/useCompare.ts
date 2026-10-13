import { useJobResume } from './useJobResume';
import { useCallback, useEffect, useRef, useState } from 'react';
import { apiPost, getApiErrorMessage, isRequestCanceled } from '../api/client';
import { assertBacktestResult, isRecord } from '../api/guards';
import { pollJobResult } from '../api/pollJob';
import { withAllPoolBudget } from '../config/backtest';
import type { BacktestConfig, BacktestResult } from '../types';

type CompareJobSubmitResponse = {
  job_id: string;
};

export function useCompare() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, BacktestResult> | null>(null);
  const recoverResult = useCallback((value: unknown) => {
    if (!isRecord(value)) throw new Error('对比结果格式错误');
    setResults(Object.fromEntries(Object.entries(value).map(([key,item]) => [key, assertBacktestResult(item)])));
  }, []);
  useJobResume('compare', recoverResult, setError, setLoading);
  const requestSeq = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const runCompare = async (config: Omit<BacktestConfig, 'factor'>, strategies: string[]) => {
    if (strategies.length === 0) return;
    const requestId = requestSeq.current + 1;
    requestSeq.current = requestId;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    window.dispatchEvent(new Event('momo:job-submitted'));
    setLoading(true);
    setError(null);
    try {
      const payloadConfig = withAllPoolBudget(config);
      const submit = await apiPost<CompareJobSubmitResponse>('/api/backtest/compare/jobs', {
        ...payloadConfig,
        strategies,
      }, { timeout: 15000, signal: controller.signal });
      const jobId = submit?.job_id;
      if (!jobId) throw new Error('后端未返回 compare job_id');
      localStorage.setItem('momo:compare:job', jobId);

      const payload = await pollJobResult<unknown>(
        `/api/backtest/compare/jobs/${jobId}`,
        `/api/backtest/compare/jobs/${jobId}/result`,
        {
          signal: controller.signal,
          timeoutMessage: '策略对比运行超时（已超过 8 分钟），请减少策略数量或缩小回测区间',
          failureMessage: '策略对比失败',
        },
      );
      if (payload == null) return;
      if (requestSeq.current !== requestId) return;
      if (!isRecord(payload)) throw new Error('策略对比结果不是对象');
      setResults(Object.fromEntries(
        Object.entries(payload).map(([key, value]) => [key, assertBacktestResult(value)]),
      ));
    } catch (e: unknown) {
      if (isRequestCanceled(e) || requestSeq.current !== requestId) return;
      setError(getApiErrorMessage(e, '对比执行失败，请确认后端已启动并有历史数据'));
      console.error(e);
    } finally {
      if (requestSeq.current === requestId) {
        setLoading(false);
      }
    }
  };

  return { loading, error, results, runCompare };
}
