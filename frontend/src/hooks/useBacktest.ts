import { useRef, useState } from 'react';
import { apiGet, apiPost, getApiErrorMessage, isRequestCanceled } from '../api/client';
import { assertBacktestResult } from '../api/guards';
import { withAllPoolBudget } from '../config/backtest';
import type { BacktestConfig, BacktestResult } from '../types';

type BacktestJobSubmitResponse = {
  job_id: string;
};

type BacktestJobStatusResponse = {
  job_id: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | string;
  error?: string | null;
};

export function useBacktest() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const requestSeq = useRef(0);
  const abortRef = useRef<AbortController | null>(null);

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
      // Submit job first to avoid blocking the UI on long backtests.
      const submit = await apiPost<BacktestJobSubmitResponse>('/api/backtest/jobs', payloadConfig, {
        timeout: 15000,
        signal: controller.signal,
      });
      const jobId = submit?.job_id;
      if (!jobId) throw new Error('后端未返回 job_id');

      const poll = async (): Promise<unknown> => {
        const start = Date.now();
        while (true) {
          if (requestSeq.current !== requestId) return null;
          if (controller.signal.aborted) return null;

          const status = await apiGet<BacktestJobStatusResponse>(
            `/api/backtest/jobs/${jobId}`,
            { timeout: 8000, signal: controller.signal }
          );

          if (status.status === 'succeeded') {
            const payload = await apiGet<unknown>(
              `/api/backtest/jobs/${jobId}/result`,
              { timeout: 30000, signal: controller.signal }
            );
            return payload;
          }

          if (status.status === 'failed') {
            throw new Error(status.error || '回测失败');
          }

          // Safety timeout: 8 minutes.
          if (Date.now() - start > 8 * 60 * 1000) {
            throw new Error('回测运行超时（已超过 8 分钟），请缩小区间或减少标的数量');
          }

          await new Promise((r) => setTimeout(r, 1000));
        }
      };

      const payload = await poll();
      if (payload == null) return;
      if (requestSeq.current !== requestId) return;
      setResult(assertBacktestResult(payload));
    } catch (e: unknown) {
      if (isRequestCanceled(e) || requestSeq.current !== requestId) return;
      setError(getApiErrorMessage(e, "回测执行失败，请确认后端已启动并有历史数据"));
      console.error(e);
    } finally {
      if (requestSeq.current === requestId) {
        setLoading(false);
      }
    }
  };

  return { loading, error, result, runBacktest, setResult };
}
