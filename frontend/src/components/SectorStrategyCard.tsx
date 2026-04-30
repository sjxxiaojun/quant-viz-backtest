import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { Activity, TrendingUp, AlertTriangle, Zap } from 'lucide-react';

interface StockInfo {
  code: string;
  name: string;
}

interface StrategyData {
  regime: string;
  metrics: {
    annual_return: number;
    sharpe: number;
    max_drawdown: number;
  };
  top_stocks: StockInfo[];
}

export function SectorStrategyCard() {
  const [data, setData] = useState<StrategyData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const response = await axios.get<StrategyData>('/api/v1/strategy/power-storage');
        setData(response.data);
        setError(null);
      } catch (err: unknown) {
        console.error('获取策略数据失败:', err);
        const errorMessage = err instanceof Error ? err.message : '获取数据失败';
        setError(errorMessage);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, []);

  if (loading) {
    return (
      <div className="rounded-2xl border border-slate-700/50 bg-slate-800/50 p-4 flex items-center justify-center animate-pulse shadow-md">
        <div className="flex items-center gap-2 text-slate-400">
          <Zap className="w-5 h-5 opacity-50 animate-pulse text-blue-400" />
          <span className="text-sm font-medium">加载电力与储能策略中...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-rose-500/20 bg-slate-800/50 p-4 shadow-md">
        <div className="flex items-center gap-2 text-rose-400 mb-1">
          <AlertTriangle className="w-4 h-4" />
          <h3 className="text-sm font-semibold">策略数据获取异常</h3>
        </div>
        <p className="text-xs text-slate-400">{error}</p>
      </div>
    );
  }

  if (!data) return null;

  const isTrending = data.regime.toLowerCase().includes('trending');
  
  return (
    <div className="rounded-2xl border border-slate-700/50 bg-slate-800/50 p-4 shadow-md hover:border-blue-500/30 transition-all">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-lg bg-blue-500/10 text-blue-400 ring-1 ring-inset ring-blue-500/20">
            <Zap className="w-4 h-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-slate-100 leading-tight">电力与储能板块策略</h3>
          </div>
        </div>
        <div className={`px-2 py-0.5 rounded-md text-xs font-semibold flex items-center gap-1 border ${
          isTrending 
            ? 'bg-orange-500/10 text-orange-400 border-orange-500/20' 
            : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
        }`}>
          {isTrending ? <TrendingUp className="w-3 h-3" /> : <Activity className="w-3 h-3" />}
          {isTrending ? '趋势进攻模式' : '震荡防御模式'}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2 mb-4">
        <div className="flex flex-col">
          <span className="text-[10px] font-medium text-slate-400">年化收益</span>
          <span className="text-base font-bold text-emerald-400">
            {(data.metrics.annual_return * 100).toFixed(2)}%
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-[10px] font-medium text-slate-400">夏普比率</span>
          <span className="text-base font-bold text-blue-400">
            {data.metrics.sharpe.toFixed(2)}
          </span>
        </div>
        <div className="flex flex-col">
          <span className="text-[10px] font-medium text-slate-400">最大回撤</span>
          <span className="text-base font-bold text-rose-400">
            {(data.metrics.max_drawdown * 100).toFixed(2)}%
          </span>
        </div>
      </div>

      <div className="pt-3 border-t border-slate-700/50 flex flex-wrap items-center gap-2 text-xs">
        <span className="font-medium text-slate-400 flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shadow-[0_0_4px_rgba(16,185,129,0.5)]"></span>
          当前最强推荐：
        </span>
        <div className="flex flex-wrap gap-1.5">
          {data.top_stocks.map((stock, idx) => (
            <span 
              key={idx} 
              className="px-1.5 py-0.5 font-medium rounded-md bg-slate-900 border border-slate-700 text-slate-300 transition-colors"
            >
              {stock.name} <span className="text-slate-500 text-[10px] ml-0.5">{stock.code}</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
