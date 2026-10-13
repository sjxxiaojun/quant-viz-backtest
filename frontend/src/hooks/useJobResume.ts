import { useEffect } from 'react';
import { apiGet, getApiErrorMessage } from '../api/client';
import { pollJobResult } from '../api/pollJob';

export function useJobResume(kind: 'backtest' | 'compare', onResult: (value: unknown) => void, onError: (message: string | null) => void, onLoading: (loading: boolean) => void, onRequest?: (value: unknown) => void) {
  useEffect(() => {
    let controller = new AbortController();
    const recover = async () => {
      const [view, query] = location.hash.slice(1).split('?');
      if (view !== (kind === 'backtest' ? 'console' : 'compare')) return;
      const id = new URLSearchParams(query).get('job') ?? localStorage.getItem(`momo:${kind}:job`);
      if (!id) return;
      controller.abort(); controller = new AbortController();
      const signal = controller.signal;
      onLoading(true);
      try {
        const meta = await apiGet<{ kind: string; request?: unknown }>(`/api/research/jobs/${id}`, { signal });
        if (meta.kind !== kind) throw new Error('任务类型与页面不匹配');
        if (!signal.aborted && meta.request) onRequest?.(meta.request);
        const result = await pollJobResult(`/api/research/jobs/${id}`, `/api/research/jobs/${id}/result`, { signal, timeoutMs: 60 * 60 * 1000 });
        if (!signal.aborted && result) { onResult(result); onError(null); }
      } catch (e) { if (!signal.aborted) onError(getApiErrorMessage(e, '恢复任务失败')); }
      finally { if (!signal.aborted) onLoading(false); }
    };
    const changed = () => void recover();
    const submitted = () => controller.abort();
    window.addEventListener('momo:job-submitted', submitted);
    changed(); window.addEventListener('hashchange', changed);
    return () => { controller.abort(); window.removeEventListener('hashchange', changed); window.removeEventListener('momo:job-submitted', submitted); };
  }, [kind, onResult, onError, onLoading, onRequest]);
}
