import { useState, useEffect } from 'react';
import { apiGet } from '../api/client';

type MarketDataItem = Record<string, unknown>;

interface SystemStatus {
  market_status?: string;
  data_coverage?: string;
  [key: string]: unknown;
}

export function useMarketData() {
  const [marketData, setMarketData] = useState<MarketDataItem[]>([]);
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const [marketResp, statusResp] = await Promise.all([
          apiGet<unknown>('/api/market/latest', { timeout: 5000 }),
          apiGet<unknown>('/api/system/status', { timeout: 5000 }),
        ]);
        if (cancelled) return;
        setMarketData(Array.isArray(marketResp) ? marketResp as MarketDataItem[] : []);
        setSysStatus((statusResp as SystemStatus) ?? null);
      } catch (e) {
        console.error("Failed to fetch market data or system status", e);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return { marketData, sysStatus };
}

export function useSystemStatus() {
  const [sysStatus, setSysStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const response = await apiGet<unknown>('/api/system/status', { timeout: 5000 });
        if (!cancelled) {
          setSysStatus((response as SystemStatus) ?? null);
        }
      } catch (e) {
        console.error("Failed to fetch system status", e);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  return { sysStatus };
}
