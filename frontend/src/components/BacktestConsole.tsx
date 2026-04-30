import React, { useEffect, useMemo } from 'react';
import { Target, Play, Loader2, Calendar, DollarSign, Settings2, Database, Lock } from 'lucide-react';
import { cn } from '../utils';
import {
  coerceRuntimePoolForStrategy,
  colorMap,
  getAssetClassLabel,
  getAllowedPoolOptions,
  getLockedPoolDescription,
  getLockedPoolLabel,
  getStrategyAssetClass,
  getStrategyMeta,
} from '../config/strategies';
import { BACKTEST_MAX_SYMBOLS, withPoolSelectionBudget } from '../config/backtest';
import type { BacktestConfig } from '../types';

interface BacktestConsoleProps {
  config: BacktestConfig;
  setConfig: React.Dispatch<React.SetStateAction<BacktestConfig>>;
  onRun: () => void;
  onSwitchStrategy: () => void;
  loading: boolean;
}

const DATE_MIN = "2022-01-01";
const TODAY = new Date().toISOString().slice(0, 10);

// Quick date range presets
const DATE_PRESETS = [
  { label: "近1年", months: 12 },
  { label: "近2年", months: 24 },
  { label: "近3年", months: 36 },
  { label: "全部", months: 0 },  // 0 = use DATE_MIN
] as const;

function getPresetDates(months: number): { start: string; end: string } {
  const today = new Date();
  const end = today.toISOString().slice(0, 10);
  if (months === 0) return { start: DATE_MIN, end };
  const startDate = new Date(today);
  startDate.setMonth(startDate.getMonth() - months);
  // Clamp to DATA_MIN
  const startStr = startDate.toISOString().slice(0, 10);
  return { start: startStr < DATE_MIN ? DATE_MIN : startStr, end };
}

export function BacktestConsole({ config, setConfig, onRun, onSwitchStrategy, loading }: BacktestConsoleProps) {
  const currentStrategy = getStrategyMeta(config.factor);
  const assetClass = getStrategyAssetClass(config.factor);
  const allowedPoolOptions = getAllowedPoolOptions(config.factor);
  const runtimePool = coerceRuntimePoolForStrategy(config.factor, config.pool);
  const lockedPoolLabel = getLockedPoolLabel(config.factor, runtimePool);
  const lockedPoolDescription = getLockedPoolDescription(config.factor, runtimePool);
  const dateRangeInvalid = Boolean(config.start_date && config.end_date && config.start_date > config.end_date);

  const activePreset = useMemo(() => {
    for (const p of DATE_PRESETS) {
      const { start, end } = getPresetDates(p.months);
      if (config.start_date === start && config.end_date === end) return p.label;
    }
    return null;
  }, [config.start_date, config.end_date]);

  useEffect(() => {
    if (config.pool !== runtimePool) {
      setConfig(prev => withPoolSelectionBudget(prev, runtimePool));
      return;
    }
    if (runtimePool === 'all' && config.max_symbols == null) {
      setConfig(prev => withPoolSelectionBudget(prev, runtimePool));
    }
  }, [config.max_symbols, config.pool, runtimePool, setConfig]);

  return (
    <section className="border rounded-3xl p-7 backdrop-blur-xl shadow-2xl space-y-6 relative overflow-hidden"
      style={{ background: 'rgba(13, 27, 50, 0.6)', borderColor: 'rgba(59, 130, 246, 0.1)' }}
    >
      {/* Strategy Header */}
      <div className="flex items-center gap-3">
        <div className={cn("p-2 rounded-lg", colorMap[currentStrategy.color]?.textBg || 'bg-blue-500/10', colorMap[currentStrategy.color]?.text || 'text-blue-400')}>
          {React.createElement(currentStrategy.icon, { className: "w-5 h-5" })}
        </div>
        <div>
          <h2 className="text-base font-bold text-slate-200 leading-tight">{currentStrategy.name}</h2>
          <p className="text-[10px] text-slate-500 mt-0.5">{currentStrategy.category}</p>
        </div>
      </div>
      
      <div className="space-y-5">
        {/* Quick Date Presets */}
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <Calendar className="w-3.5 h-3.5 text-blue-400" />
            <label className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.2em]">回测区间</label>
          </div>
          <div className="grid grid-cols-4 gap-1.5">
            {DATE_PRESETS.map(p => (
              <button
                key={p.label}
                className={cn(
                  "py-1.5 rounded-lg text-[10px] font-bold transition-all border",
                  activePreset === p.label
                    ? "bg-blue-600/20 text-blue-300 border-blue-500/40"
                    : "text-slate-500 border-transparent hover:text-slate-300 hover:bg-white/5"
                )}
                onClick={() => {
                  const { start, end } = getPresetDates(p.months);
                  setConfig(prev => ({ ...prev, start_date: start, end_date: end }));
                }}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        {/* Date Pickers */}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-1.5">
            <label className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">起始日期</label>
            <input 
              type="date"
              min={DATE_MIN}
              max={TODAY}
              className="w-full rounded-xl px-3 py-2.5 text-xs focus:ring-1 focus:ring-blue-500 outline-none text-slate-200 font-mono"
              style={{ background: 'rgba(8, 18, 36, 0.7)', borderWidth: '1px', borderColor: 'rgba(59, 130, 246, 0.12)' }}
              value={config.start_date}
              onChange={e => setConfig({...config, start_date: e.target.value})}
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">结束日期</label>
            <input 
              type="date"
              min={DATE_MIN}
              max={TODAY}
              className="w-full rounded-xl px-3 py-2.5 text-xs focus:ring-1 focus:ring-blue-500 outline-none text-slate-200 font-mono"
              style={{ background: 'rgba(8, 18, 36, 0.7)', borderWidth: '1px', borderColor: 'rgba(59, 130, 246, 0.12)' }}
              value={config.end_date}
              onChange={e => setConfig({...config, end_date: e.target.value})}
            />
          </div>
        </div>

        {/* Capital + Pool */}
        <div className="space-y-3 pt-3" style={{ borderTop: '1px solid rgba(59, 130, 246, 0.08)' }}>
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <DollarSign className="w-3.5 h-3.5 text-emerald-400" />
              <label className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.2em]">初始资金</label>
            </div>
            <div className="grid grid-cols-4 gap-1.5">
              {[500000, 1000000, 2000000, 5000000].map(v => (
                <button
                  key={v}
                  className={cn(
                    "py-1.5 rounded-lg text-[10px] font-bold transition-all border",
                    config.initial_capital === v
                      ? "bg-emerald-600/20 text-emerald-300 border-emerald-500/40"
                      : "text-slate-500 border-transparent hover:text-slate-300 hover:bg-white/5"
                  )}
                  onClick={() => setConfig({ ...config, initial_capital: v })}
                >
                  {(v / 10000).toFixed(0)}万
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <Database className="w-3.5 h-3.5 text-cyan-400" />
              <label className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.2em]">数据池路由</label>
            </div>
            <div
              className="rounded-2xl p-4 space-y-3"
              style={{ background: 'rgba(8, 18, 36, 0.7)', borderWidth: '1px', borderStyle: 'solid', borderColor: 'rgba(59, 130, 246, 0.12)' }}
            >
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-[11px] font-bold text-slate-200">{lockedPoolLabel}</div>
                  <div className="text-[10px] text-slate-500 mt-1">{lockedPoolDescription}</div>
                </div>
                <div className="shrink-0 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[10px] font-bold border text-cyan-300 border-cyan-500/20 bg-cyan-500/10">
                  <Lock className="w-3 h-3" />
                  资产锁定
                </div>
              </div>
              <div className="flex items-center justify-between text-[10px]">
                <span className="text-slate-500">策略资产类别</span>
                <span className="font-bold text-slate-300">{getAssetClassLabel(assetClass)}</span>
              </div>
              <div className="flex items-center justify-between text-[10px]">
                <span className="text-slate-500">发送给后端的池参数</span>
                <span className="font-mono font-bold text-slate-300">{runtimePool}</span>
              </div>
              <div className="grid grid-cols-2 gap-2 pt-1">
                {allowedPoolOptions.map((option) => {
                  const isSelected = runtimePool === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      className={cn(
                        "rounded-xl px-3 py-2 text-[10px] font-bold border transition-all text-left",
                        isSelected
                          ? "bg-cyan-600/20 text-cyan-200 border-cyan-500/40"
                          : "text-slate-400 border-slate-700/40 hover:text-slate-200 hover:border-cyan-500/30 hover:bg-white/5"
                      )}
                      onClick={() => setConfig(prev => withPoolSelectionBudget(prev, option.value))}
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
              {runtimePool === 'all' && (
                <div className="flex items-center justify-between rounded-xl border border-cyan-500/20 bg-cyan-500/5 px-3 py-2 text-[10px]">
                  <span className="font-bold text-cyan-200">全市场轻量预筛上限</span>
                  <span className="font-mono font-black text-cyan-100">{config.max_symbols ?? BACKTEST_MAX_SYMBOLS}</span>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Collapsible Advanced Settings */}
        <div className="space-y-2 pt-2" style={{ borderTop: '1px solid rgba(59, 130, 246, 0.08)' }}>
          {/* Position Management Settings */}
          <details className="group [&_summary::-webkit-details-marker]:hidden">
            <summary className="flex items-center gap-2 cursor-pointer outline-none py-1">
              <Settings2 className="w-3.5 h-3.5 text-emerald-400 group-open:text-emerald-300" />
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest group-open:text-slate-300">仓位与权重管理</span>
            </summary>
            <div className="pt-3 pb-1 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-[9px] text-slate-500 uppercase font-bold tracking-wider">最大持仓数</label>
                  <select 
                    className="w-full rounded-lg px-2 py-1.5 text-xs text-emerald-300 outline-none"
                    style={{ background: 'rgba(8, 18, 36, 0.5)', borderWidth: '1px', borderColor: 'rgba(59, 130, 246, 0.08)' }}
                    value={config.max_positions}
                    onChange={e => setConfig({...config, max_positions: parseInt(e.target.value)})}
                  >
                    <option value={1}>1 只</option>
                    <option value={3}>3 只</option>
                    <option value={5}>5 只</option>
                    <option value={8}>8 只</option>
                    <option value={10}>10 只</option>
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="text-[9px] text-slate-500 uppercase font-bold tracking-wider">权重模式</label>
                  <select 
                    className="w-full rounded-lg px-2 py-1.5 text-xs text-emerald-300 outline-none"
                    style={{ background: 'rgba(8, 18, 36, 0.5)', borderWidth: '1px', borderColor: 'rgba(59, 130, 246, 0.08)' }}
                    value={config.weight_mode}
                    onChange={e => setConfig({...config, weight_mode: e.target.value})}
                  >
                    <option value="equal">等权分配</option>
                    <option value="score">按分数加权</option>
                    <option value="risk_parity">风险平价</option>
                  </select>
                </div>
              </div>
              <div className="space-y-1">
                <label className="text-[9px] text-slate-500 uppercase font-bold tracking-wider">最大持仓天数 (留空不限制)</label>
                <input 
                  type="number" min="1" placeholder="如: 5"
                  className="w-full rounded-lg px-2 py-1.5 text-xs text-emerald-300 outline-none"
                  style={{ background: 'rgba(8, 18, 36, 0.5)', borderWidth: '1px', borderColor: 'rgba(59, 130, 246, 0.08)' }}
                  value={config.max_hold_days || ''}
                  onChange={e => setConfig({...config, max_hold_days: e.target.value ? parseInt(e.target.value) : undefined})}
                />
              </div>
            </div>
          </details>

          {/* Risk Control Settings */}
          <details className="group [&_summary::-webkit-details-marker]:hidden">
            <summary className="flex items-center gap-2 cursor-pointer outline-none py-1">
              <Target className="w-3.5 h-3.5 text-rose-400 group-open:text-rose-300" />
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest group-open:text-slate-300">高级风控参数</span>
            </summary>
            <div className="pt-3 pb-1 space-y-3">
              <div className="space-y-1">
                <div className="flex justify-between">
                  <label className="text-[9px] text-slate-500 uppercase font-bold tracking-wider">个股止损线</label>
                  <span className="text-[9px] text-rose-400 font-mono">{(config.stop_loss * 100).toFixed(0)}%</span>
                </div>
                <input 
                  type="range" min="-0.15" max="-0.03" step="0.01"
                  className="w-full accent-rose-500"
                  value={config.stop_loss}
                  onChange={e => setConfig({...config, stop_loss: parseFloat(e.target.value)})}
                />
              </div>
              <div className="space-y-1">
                <div className="flex items-center justify-between gap-3">
                  <label className="flex items-center gap-2 text-[9px] text-slate-500 uppercase font-bold tracking-wider">
                    <input
                      type="checkbox"
                      className="h-3.5 w-3.5 rounded border-slate-600 bg-slate-900 accent-emerald-500"
                      checked={config.take_profit != null}
                      onChange={e => setConfig({
                        ...config,
                        take_profit: e.target.checked ? (config.take_profit ?? 0.2) : undefined,
                      })}
                    />
                    个股止盈线
                  </label>
                  <span className="text-[9px] text-emerald-400 font-mono">
                    {config.take_profit != null ? `${(config.take_profit * 100).toFixed(0)}%` : '关闭'}
                  </span>
                </div>
                <input
                  type="range" min="0.05" max="0.5" step="0.01"
                  className="w-full accent-emerald-500 disabled:opacity-40"
                  disabled={config.take_profit == null}
                  value={config.take_profit ?? 0.2}
                  onChange={e => setConfig({...config, take_profit: parseFloat(e.target.value)})}
                />
              </div>
              <div className="space-y-1">
                <div className="flex justify-between">
                  <label className="text-[9px] text-slate-500 uppercase font-bold tracking-wider">单边滑点设定</label>
                  <span className="text-[9px] text-slate-300 font-mono">{(config.slippage_rate * 100).toFixed(2)}%</span>
                </div>
                <input 
                  type="range" min="0.0001" max="0.005" step="0.0001"
                  className="w-full accent-blue-500"
                  value={config.slippage_rate}
                  onChange={e => setConfig({...config, slippage_rate: parseFloat(e.target.value)})}
                />
              </div>
            </div>
          </details>
        </div>
        {dateRangeInvalid && (
          <div className="rounded-xl border border-rose-500/20 bg-rose-500/10 px-3 py-2 text-[11px] font-semibold text-rose-100">
            起始日期不能晚于结束日期。
          </div>
        )}

      <button 
        onClick={onRun}
        disabled={loading || dateRangeInvalid}
        className="w-full bg-blue-600 hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-bold py-3.5 rounded-2xl shadow-xl active:scale-[0.97] transition-all flex items-center justify-center gap-3 border border-blue-400/20"
      >
        {loading ? (
          <div className="flex items-center gap-3">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span className="animate-pulse">正在提取全市场数据...</span>
          </div>
        ) : (
          <><Play className="w-4 h-4 fill-current" /> <span>启动仿真回测</span></>
        )}
      </button>

        <button 
          onClick={onSwitchStrategy}
          className="w-full bg-transparent border hover:text-white font-bold py-2.5 rounded-2xl transition-all text-xs text-slate-400"
          style={{ borderColor: 'rgba(59, 130, 246, 0.15)' }}
        >
          切换策略算法
        </button>
      </div>
    </section>
  );
}
