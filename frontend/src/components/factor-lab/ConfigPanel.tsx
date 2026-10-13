import React from 'react';
import { Calendar, Database, BarChart3 } from 'lucide-react';
import { cn } from '../../utils';
import { factorLabPoolOptions } from '../../config/strategies';
import type { FactorLabRunConfig } from '../../types';
// 日期边界常量放在 normalize.ts(纯逻辑模块): 组件文件只导出组件, 否则 Fast Refresh 失效。
import { DEFAULT_END_DATE, DEFAULT_START_DATE, isFactorLabPool } from './normalize';

const TOP_N_OPTIONS = [3, 5, 10, 20] as const;
const SAMPLE_SIZE_OPTIONS = [180, 300, 500] as const;

const INPUT_CLASS =
  'num w-full rounded-ctl border border-line bg-bg2 px-2 py-1.5 text-xs text-slate-200 outline-none focus:border-accent/50';

const OPTION_BTN =
  'rounded-ctl border px-2 py-1.5 text-[11px] font-medium transition-colors';

function optionBtnClass(selected: boolean): string {
  return cn(
    OPTION_BTN,
    selected
      ? 'border-accent/50 bg-accent/15 text-accent'
      : 'border-line bg-bg2 text-slate-400 hover:bg-bg3 hover:text-slate-200'
  );
}

interface ConfigPanelProps {
  config: FactorLabRunConfig;
  onChange: (patch: Partial<FactorLabRunConfig>) => void;
  dateRangeInvalid: boolean;
}

/** 运行参数配置面板: 回看区间 / 股票池 / 持仓数量 / 样本预算 */
export function ConfigPanel({ config, onChange, dateRangeInvalid }: ConfigPanelProps) {
  return (
    <div className="space-y-3"><div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      <div className="rounded-ctl border border-line bg-bg2 p-3">
        <div className="mb-2 flex items-center gap-1.5 text-slate-400">
          <Calendar className="h-3.5 w-3.5" />
          <span className="label-caps">回看时间</span>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <label className="block">
            <span className="text-[10px] text-slate-500">开始日期</span>
            <input
              type="date"
              value={config.start_date}
              min={DEFAULT_START_DATE}
              max={DEFAULT_END_DATE}
              onChange={(event) => onChange({ start_date: event.target.value })}
              className={cn(INPUT_CLASS, 'mt-1')}
            />
          </label>
          <label className="block">
            <span className="text-[10px] text-slate-500">结束日期</span>
            <input
              type="date"
              value={config.end_date}
              min={DEFAULT_START_DATE}
              max={DEFAULT_END_DATE}
              onChange={(event) => onChange({ end_date: event.target.value })}
              className={cn(INPUT_CLASS, 'mt-1')}
            />
          </label>
        </div>
        {dateRangeInvalid ? (
          <p className="mt-2 text-[11px] text-rose-400">请填写有效的起止日期，开始日期不能晚于结束日期。</p>
        ) : (
          <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
            区间越长越能覆盖不同市场阶段；运行前自动检查是否需要补数。
          </p>
        )}
      </div>

      <div className="rounded-ctl border border-line bg-bg2 p-3">
        <div className="mb-2 flex items-center gap-1.5 text-slate-400">
          <Database className="h-3.5 w-3.5" />
          <span className="label-caps">股票池范围</span>
        </div>
        <div className="space-y-1.5">
          {factorLabPoolOptions.map((option) => {
            const selected = config.pool === option.value;
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => {
                  if (isFactorLabPool(option.value)) onChange({ pool: option.value });
                }}
                className={cn(optionBtnClass(selected), 'w-full text-left')}
              >
                <span className="font-semibold">{option.label}</span>
                <span className={cn('ml-2 text-[10px]', selected ? 'opacity-80' : 'text-slate-500')}>
                  {option.description}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="rounded-ctl border border-line bg-bg2 p-3">
        <div className="mb-2 flex items-center gap-1.5 text-slate-400">
          <BarChart3 className="h-3.5 w-3.5" />
          <span className="label-caps">持仓与样本</span>
        </div>
        <div>
          <span className="text-[10px] text-slate-500">每次保留前几只股票</span>
          <div className="mt-1 grid grid-cols-4 gap-1.5">
            {TOP_N_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => onChange({ top_n: option })}
                className={optionBtnClass(config.top_n === option)}
              >
                Top {option}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-3">
          <span className="text-[10px] text-slate-500">研究样本预算</span>
          <div className="mt-1 grid grid-cols-3 gap-1.5">
            {SAMPLE_SIZE_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => onChange({ max_symbols: option })}
                className={optionBtnClass(config.max_symbols === option)}
              >
                {option} 只
              </button>
            ))}
          </div>
          <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
            持仓越少组合越集中；全市场会先做轻量预筛，再把预算内样本送进深度实验。
          </p>
        </div>
      </div>
    </div><div className="space-y-2 rounded-md border border-line bg-bg2 p-3 text-xs">
      <label className="flex gap-2 text-amber-300"><input type="checkbox" checked={config.price_mode==='approximate_adjusted'} onChange={e=>onChange({price_mode:e.target.checked ? 'approximate_adjusted' : 'strict_raw'})}/>允许复权价近似研究（默认严格未复权成交数据）</label>
      <label className="flex gap-2 text-slate-300"><input type="checkbox" checked={config.enable_hist_gradient_boosting ?? false} onChange={e=>onChange({enable_hist_gradient_boosting:e.target.checked})}/>加入 HistGradientBoosting 候选（只在历史验证窗口选择融合权重）</label>
    </div></div>
  );
}
