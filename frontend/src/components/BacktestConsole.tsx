import React, { useEffect, useMemo } from 'react';
import { Loader2, Lock, Play } from 'lucide-react';
import { cn } from '../utils';
import { getPoolLabel, getStrategyMeta, type RuntimePool } from '../config/strategies';
import { BACKTEST_MAX_SYMBOLS, withPoolSelectionBudget } from '../config/backtest';
import { getExecutionModeLabel, getPoolShortLabel, type StrategyCatalogEntry } from '../api/strategyCatalog';
import { useStrategyCatalog } from '../hooks/useStrategyCatalog';
import { Panel, SectionTitle, Tag } from './ui';
import type { BacktestConfig } from '../types';

interface BacktestConsoleProps {
  config: BacktestConfig;
  setConfig: React.Dispatch<React.SetStateAction<BacktestConfig>>;
  onRun: () => void;
  onSwitchStrategy: () => void;
  loading: boolean;
}

const DATE_MIN = '2022-01-01';
const TODAY = new Date().toISOString().slice(0, 10);

const DATE_PRESETS = [
  { label: '近1年', months: 12 },
  { label: '近2年', months: 24 },
  { label: '近3年', months: 36 },
  { label: '全部', months: 0 }, // 0 = 从 DATE_MIN 起
] as const;

const CAPITAL_PRESETS = [500000, 1000000, 2000000, 5000000];

function getPresetDates(months: number): { start: string; end: string } {
  const today = new Date();
  const end = today.toISOString().slice(0, 10);
  if (months === 0) return { start: DATE_MIN, end };
  const startDate = new Date(today);
  startDate.setMonth(startDate.getMonth() - months);
  const startStr = startDate.toISOString().slice(0, 10);
  return { start: startStr < DATE_MIN ? DATE_MIN : startStr, end };
}

/** 目录未命中时用本地元数据凑一个最小条目 (老策略) */
function localEntryFor(factor: string): StrategyCatalogEntry {
  const meta = getStrategyMeta(factor);
  return {
    id: factor,
    name: meta.name,
    category: meta.category,
    pool: meta.pool,
    assetClass: meta.assetClass,
    signalType: 'stateful',
    holdingPolicy: 'sell_on_minus_one',
    executionMode: 'next_open_rebalance',
    requiresArtifact: false,
    defaultMaxHoldDays: null,
    defaultTakeProfit: null,
    desc: meta.desc,
    tags: meta.tags,
  };
}

/** 资产类别决定可用数据池; 后端会再做一次校验, 这里只约束 UI 可选项 */
function allowedPoolValues(entry: StrategyCatalogEntry): RuntimePool[] {
  if (entry.assetClass === 'etf') return ['auto', 'etf', 'all'];
  if (entry.pool === 'power_energy') return ['auto', 'power_energy', 'all'];
  return ['auto', 'core', 'blackhorse', 'all'];
}

const inputClass =
  'w-full rounded-ctl border border-line bg-bg2 px-2.5 py-1.5 text-xs text-slate-200 outline-none focus:border-accent/50';

const chipClass = (active: boolean) =>
  cn(
    'rounded-ctl border py-1.5 text-[11px] font-medium transition-colors',
    active
      ? 'border-accent/40 bg-accent/15 text-accent'
      : 'border-line text-slate-500 hover:bg-bg3 hover:text-slate-300',
  );

export function BacktestConsole({ config, setConfig, onRun, onSwitchStrategy, loading }: BacktestConsoleProps) {
  const { byId } = useStrategyCatalog();
  const entry = byId.get(config.factor) ?? localEntryFor(config.factor);
  const poolValues = allowedPoolValues(entry);
  const runtimePool: RuntimePool = poolValues.includes(config.pool as RuntimePool)
    ? (config.pool as RuntimePool)
    : 'auto';
  const effectivePool = runtimePool === 'auto' ? (entry.pool as RuntimePool) : runtimePool;
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
    <Panel className="space-y-4">
      {/* 策略标识 */}
      <div className="space-y-1.5">
        <h2 className="text-sm font-semibold leading-tight text-slate-100">{entry.name}</h2>
        <div className="flex flex-wrap gap-1.5">
          <Tag tone="accent">{entry.category}</Tag>
          <Tag>{getExecutionModeLabel(entry.executionMode)}</Tag>
          <Tag tone={entry.assetClass === 'etf' ? 'warn' : 'default'}>
            {getPoolShortLabel(entry.pool)}
          </Tag>
        </div>
      </div>

      {/* 回测区间 */}
      <div className="space-y-2 border-t border-line pt-3">
        <SectionTitle className="mb-0">回测区间</SectionTitle>
        <div className="grid grid-cols-4 gap-1.5">
          {DATE_PRESETS.map(p => (
            <button
              key={p.label}
              type="button"
              className={chipClass(activePreset === p.label)}
              onClick={() => {
                const { start, end } = getPresetDates(p.months);
                setConfig(prev => ({ ...prev, start_date: start, end_date: end }));
              }}
            >
              {p.label}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="space-y-1">
            <label className="label-caps">起始</label>
            <input
              type="date"
              min={DATE_MIN}
              max={TODAY}
              className={cn(inputClass, 'num')}
              value={config.start_date}
              onChange={e => setConfig({ ...config, start_date: e.target.value })}
            />
          </div>
          <div className="space-y-1">
            <label className="label-caps">结束</label>
            <input
              type="date"
              min={DATE_MIN}
              max={TODAY}
              className={cn(inputClass, 'num')}
              value={config.end_date}
              onChange={e => setConfig({ ...config, end_date: e.target.value })}
            />
          </div>
        </div>
      </div>

      {/* 初始资金 */}
      <div className="space-y-2 border-t border-line pt-3">
        <SectionTitle className="mb-0">初始资金</SectionTitle>
        <div className="grid grid-cols-4 gap-1.5">
          {CAPITAL_PRESETS.map(v => (
            <button
              key={v}
              type="button"
              className={cn(chipClass(config.initial_capital === v), 'num')}
              onClick={() => setConfig({ ...config, initial_capital: v })}
            >
              {(v / 10000).toFixed(0)}万
            </button>
          ))}
        </div>
      </div>

      {/* 数据池路由 */}
      <div className="space-y-2 border-t border-line pt-3">
        <SectionTitle
          className="mb-0"
          right={
            <Tag tone="accent">
              <Lock className="h-3 w-3" />
              资产锁定
            </Tag>
          }
        >
          数据池路由
        </SectionTitle>
        <div className="panel-nested space-y-2 p-3">
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-slate-500">实际生效池</span>
            <span className="font-medium text-slate-200">{getPoolLabel(effectivePool)}</span>
          </div>
          <div className="flex items-center justify-between text-[11px]">
            <span className="text-slate-500">发送给后端</span>
            <span className="num text-slate-300">{runtimePool}</span>
          </div>
          <div className="grid grid-cols-2 gap-1.5 pt-1">
            {poolValues.map(value => (
              <button
                key={value}
                type="button"
                className={cn(chipClass(runtimePool === value), 'px-2 text-left')}
                onClick={() => setConfig(prev => withPoolSelectionBudget(prev, value))}
              >
                {value === 'auto' ? '系统自动匹配' : getPoolLabel(value)}
              </button>
            ))}
          </div>
          {runtimePool === 'all' && (
            <div className="flex items-center justify-between rounded-ctl border border-accent/25 bg-accent/10 px-2.5 py-1.5 text-[11px]">
              <span className="text-accent">全市场轻量预筛上限</span>
              <span className="num font-semibold text-slate-100">
                {config.max_symbols ?? BACKTEST_MAX_SYMBOLS}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* 仓位与权重 */}
      <details className="group border-t border-line pt-3 [&_summary::-webkit-details-marker]:hidden">
        <summary className="label-caps cursor-pointer select-none outline-none group-open:text-slate-300">
          仓位与权重管理
        </summary>
        <div className="space-y-2.5 pt-2.5">
          <div className="grid grid-cols-2 gap-2">
            <div className="space-y-1">
              <label className="label-caps">最大持仓数</label>
              <select
                className={inputClass}
                value={config.max_positions}
                onChange={e => setConfig({ ...config, max_positions: parseInt(e.target.value) })}
              >
                <option value={1}>1 只</option>
                <option value={3}>3 只</option>
                <option value={5}>5 只</option>
                <option value={8}>8 只</option>
                <option value={10}>10 只</option>
              </select>
            </div>
            <div className="space-y-1">
              <label className="label-caps">权重模式</label>
              <select
                className={inputClass}
                value={config.weight_mode}
                onChange={e => setConfig({ ...config, weight_mode: e.target.value })}
              >
                <option value="equal">等权分配</option>
                <option value="score">按分数加权</option>
                <option value="risk_parity">风险平价</option>
              </select>
            </div>
          </div>
          <div className="space-y-1">
            <label className="label-caps">最大持仓天数 (留空不限制)</label>
            <input
              type="number"
              min="1"
              placeholder="如: 5"
              className={cn(inputClass, 'num')}
              value={config.max_hold_days || ''}
              onChange={e => setConfig({ ...config, max_hold_days: e.target.value ? parseInt(e.target.value) : undefined })}
            />
          </div>
        </div>
      </details>

      {/* 高级风控 */}
      <details className="group border-t border-line pt-3 [&_summary::-webkit-details-marker]:hidden">
        <summary className="label-caps cursor-pointer select-none outline-none group-open:text-slate-300">
          高级风控参数
        </summary>
        <div className="space-y-2.5 pt-2.5">
          <div className="space-y-1">
            <div className="flex justify-between">
              <label className="label-caps">个股止损线</label>
              <span className="num text-[11px] text-down">{(config.stop_loss * 100).toFixed(0)}%</span>
            </div>
            <input
              type="range"
              min="-0.15"
              max="-0.03"
              step="0.01"
              className="w-full accent-accent"
              value={config.stop_loss}
              onChange={e => setConfig({ ...config, stop_loss: parseFloat(e.target.value) })}
            />
          </div>
          <div className="space-y-1">
            <div className="flex items-center justify-between gap-3">
              <label className="label-caps flex items-center gap-2">
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5 rounded border-line bg-bg2 accent-accent"
                  checked={config.take_profit != null}
                  onChange={e => setConfig({
                    ...config,
                    take_profit: e.target.checked ? (config.take_profit ?? 0.2) : undefined,
                  })}
                />
                个股止盈线
              </label>
              <span className="num text-[11px] text-up">
                {config.take_profit != null ? `${(config.take_profit * 100).toFixed(0)}%` : '关闭'}
              </span>
            </div>
            <input
              type="range"
              min="0.05"
              max="0.5"
              step="0.01"
              className="w-full accent-accent disabled:opacity-40"
              disabled={config.take_profit == null}
              value={config.take_profit ?? 0.2}
              onChange={e => setConfig({ ...config, take_profit: parseFloat(e.target.value) })}
            />
          </div>
          <div className="space-y-1">
            <div className="flex justify-between">
              <label className="label-caps">单边滑点设定</label>
              <span className="num text-[11px] text-slate-300">{(config.slippage_rate * 100).toFixed(2)}%</span>
            </div>
            <input
              type="range"
              min="0.0001"
              max="0.005"
              step="0.0001"
              className="w-full accent-accent"
              value={config.slippage_rate}
              onChange={e => setConfig({ ...config, slippage_rate: parseFloat(e.target.value) })}
            />
          </div>
        </div>
      </details>

      {dateRangeInvalid && (
        <div className="rounded-ctl border border-up/30 bg-up/10 px-3 py-2 text-[11px] font-medium text-up-soft">
          起始日期不能晚于结束日期。
        </div>
      )}

      <div className="space-y-2 border-t border-line pt-3">
        <button
          type="button"
          onClick={onRun}
          disabled={loading || dateRangeInvalid}
          className="flex w-full items-center justify-center gap-2 rounded-ctl bg-accent py-2.5 text-xs font-semibold text-white transition-colors hover:bg-accent/85 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>正在提取行情数据...</span>
            </>
          ) : (
            <>
              <Play className="h-3.5 w-3.5 fill-current" />
              <span>启动仿真回测</span>
            </>
          )}
        </button>
        <button
          type="button"
          onClick={onSwitchStrategy}
          className="w-full rounded-ctl border border-line py-2 text-[11px] font-medium text-slate-400 transition-colors hover:bg-bg3 hover:text-slate-200"
        >
          切换策略算法
        </button>
      </div>
    </Panel>
  );
}
