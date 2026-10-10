import { apiGet } from './client';

/**
 * 异步 job 轮询公共工具:
 * submit 由调用方完成, 此处只负责 status 轮询 → 取 result 的通用流程。
 * useBacktest / useCompare 共用同一实现, 避免两份手写 while(true)。
 */

interface JobStatusResponse {
  job_id: string;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | string;
  error?: string | null;
}

export interface PollJobOptions {
  /** 取消信号: 组件卸载或重复提交时 abort, 轮询立即停止并返回 null */
  signal: AbortSignal;
  /** 总超时, 默认 8 分钟 */
  timeoutMs?: number;
  /** 起始轮询间隔, 默认 1s; 按 1.5 倍退避至 maxIntervalMs */
  initialIntervalMs?: number;
  maxIntervalMs?: number;
  timeoutMessage?: string;
  failureMessage?: string;
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      resolve();
    };
    signal.addEventListener('abort', onAbort, { once: true });
  });
}

/**
 * 轮询 statusPath 直到 succeeded, 然后 GET resultPath 返回原始 payload。
 * - 被 abort 时返回 null (调用方直接放弃本次请求, 不算错误)
 * - failed / 超时抛 Error
 */
export async function pollJobResult<T = unknown>(
  statusPath: string,
  resultPath: string,
  options: PollJobOptions,
): Promise<T | null> {
  const {
    signal,
    timeoutMs = 8 * 60 * 1000,
    initialIntervalMs = 1000,
    maxIntervalMs = 3000,
    timeoutMessage = '任务运行超时（已超过 8 分钟），请缩小区间或减少标的数量',
    failureMessage = '任务执行失败',
  } = options;

  const start = Date.now();
  let interval = initialIntervalMs;

  for (;;) {
    if (signal.aborted) return null;

    const status = await apiGet<JobStatusResponse>(statusPath, { timeout: 8000, signal });

    if (status.status === 'succeeded') {
      if (signal.aborted) return null;
      return apiGet<T>(resultPath, { timeout: 30000, signal });
    }
    if (['failed', 'canceled', 'interrupted'].includes(status.status)) {
      throw new Error(status.error || failureMessage);
    }
    if (Date.now() - start > timeoutMs) {
      throw new Error(timeoutMessage);
    }

    await sleep(interval, signal);
    interval = Math.min(Math.round(interval * 1.5), maxIntervalMs);
  }
}
