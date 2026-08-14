import { useEffect, useMemo, useState } from 'react';
import { getApiErrorMessage, isRequestCanceled } from '../api/client';
import {
  fetchStrategyCatalog,
  localFallbackCatalog,
  type StrategyCatalogEntry,
} from '../api/strategyCatalog';

/** 模块级缓存: 目录基本静态, 多视图共享一次请求 */
let cachedCatalog: StrategyCatalogEntry[] | null = null;
let inflight: Promise<StrategyCatalogEntry[]> | null = null;

function loadCatalogShared(signal: AbortSignal): Promise<StrategyCatalogEntry[]> {
  if (cachedCatalog) return Promise.resolve(cachedCatalog);
  if (!inflight) {
    // 共享请求不绑定单个组件的 signal, 由各订阅方自行判断是否还挂载
    inflight = fetchStrategyCatalog()
      .then((entries) => {
        cachedCatalog = entries;
        return entries;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight.then((entries) => {
    if (signal.aborted) throw new DOMException('aborted', 'AbortError');
    return entries;
  });
}

export interface StrategyCatalogState {
  catalog: StrategyCatalogEntry[];
  byId: Map<string, StrategyCatalogEntry>;
  loading: boolean;
  /** 后端目录不可用时的降级说明 (此时 catalog 为本地兜底) */
  fallbackReason: string | null;
}

export function useStrategyCatalog(): StrategyCatalogState {
  const [catalog, setCatalog] = useState<StrategyCatalogEntry[]>(cachedCatalog ?? []);
  const [loading, setLoading] = useState(cachedCatalog == null);
  const [fallbackReason, setFallbackReason] = useState<string | null>(null);

  useEffect(() => {
    if (cachedCatalog) return;
    const controller = new AbortController();
    loadCatalogShared(controller.signal)
      .then((entries) => {
        setCatalog(entries);
        setFallbackReason(null);
        setLoading(false);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted || isRequestCanceled(error)) return;
        setCatalog(localFallbackCatalog());
        setFallbackReason(getApiErrorMessage(error, '策略目录接口不可用'));
        setLoading(false);
      });
    return () => controller.abort();
  }, []);

  const byId = useMemo(() => new Map(catalog.map((entry) => [entry.id, entry])), [catalog]);

  return { catalog, byId, loading, fallbackReason };
}
