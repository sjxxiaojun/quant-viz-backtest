import { useEffect, useState } from 'react';
import { apiGet, getApiErrorMessage } from '../api/client';
export interface TerminalStatus {
  target_date: string | null;
  data_as_of: string | null;
  default_end_date: string | null;
  calendar_error: string | null;
  engine_version: string;
  compute_slots: number;
  active_jobs: number;
  rows: {
    symbol: string;
    name: string;
    date: string;
    close: number;
    pct_chg: number | null;
    source: string;
  }[];
}
export function useTerminalStatus() {
  const [status, setStatus] = useState<TerminalStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    const refresh = () =>
      void apiGet<TerminalStatus>('/api/terminal/status', {
        signal: controller.signal,
        timeout: 10000,
      })
        .then((value) => {
          if (!controller.signal.aborted) {
            setStatus(value);
            setError(null);
          }
        })
        .catch((e) => {
          if (!controller.signal.aborted)
            setError(getApiErrorMessage(e, '后端连接失败'));
        });
    refresh();
    const timer = setInterval(refresh, 30000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, []);
  return { status, error };
}
