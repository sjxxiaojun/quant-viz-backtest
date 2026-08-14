import { useState, useEffect } from 'react';
import { apiGet } from '../api/client';

interface SystemStatus {
  market_status?: string;
  data_coverage?: string;
  [key: string]: unknown;
}

/** 系统状态 (StatusBadge 消费); 行情快照无人使用, 已从本 hook 移除 */
export function useMarketData() {
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    apiGet<unknown>('/api/system/status', { timeout: 5000, signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted) {
          setSysStatus((response as SystemStatus) ?? null);
        }
      })
      .catch((e: unknown) => {
        if (!controller.signal.aborted) {
          console.error('Failed to fetch system status', e);
        }
      });

    return () => controller.abort();
  }, []);

  return { sysStatus };
}
