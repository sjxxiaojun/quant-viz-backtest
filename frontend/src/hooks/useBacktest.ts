import { useEffect, useRef, useState } from 'react';
import { apiPost, getApiErrorMessage, isRequestCanceled } from '../api/client';
import { assertBacktestResult } from '../api/guards';
import { pollJobResult } from '../api/pollJob';
import { withAllPoolBudget } from '../config/backtest';
import type { BacktestConfig, BacktestResult } from '../types';

type BacktestJobSubmitResponse = {
  job_id: string;
};

export function useBacktest() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const requestSeq = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const runBacktest = async (config: BacktestConfig) => {
    const requestId = requestSeq.current + 1;
    requestSeq.current = requestId;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const payloadConfig = withAllPoolBudget(config);
      // 先提交异步 job, 避免长回测阻塞请求线程
      const submit = await apiPost<BacktestJobSubmitResponse>('/api/backtest/jobs', payloadConfig, {
        timeout: 15000,
        signal: controller.signal,
      });
      const jobId = submit?.job_id;
      if (!jobId) throw new Error('后端未返回 job_id');

      const payload = await pollJobResult<unknown>(
        `/api/backtest/jobs/${jobId}`,
        `/api/backtest/jobs/${jobId}/result`,
        {
          signal: controller.signal,
          timeoutMessage: '回测运行超时（已超过 8 分钟），请缩小区间或减少标的数量',
          failureMessage: '回测失败',
        },
      );
      if (payload == null) return;
      if (requestSeq.current !== requestId) return;
      setResult(assertBacktestResult(payload));
    } catch (e: unknown) {
      if (isRequestCanceled(e) || requestSeq.current !== requestId) return;
      setError(getApiErrorMessage(e, '回测执行失败，请确认后端已启动并有历史数据'));
      console.error(e);
    } finally {
      if (requestSeq.current === requestId) {
        setLoading(false);
      }
    }
  };

  return { loading, error, result, runBacktest, setResult };
}
