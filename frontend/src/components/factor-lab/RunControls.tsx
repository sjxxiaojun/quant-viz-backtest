import React from 'react';
import { Activity, ChevronDown, ChevronUp, Loader2, Play, ShieldCheck } from 'lucide-react';
import { Tag } from '../ui';
import { BTN_NEUTRAL, BTN_OK, BTN_PRIMARY } from './labels';
import type { FactorLabHookState } from '../../types';

interface RunControlsProps {
  expertMode: boolean;
  onToggleExpert: () => void;
  loading: boolean;
  loadingAction: FactorLabHookState['loadingAction'];
  checkingReadiness: boolean;
  dateRangeInvalid: boolean;
  onRun: () => void;
  onLoadLatest: () => void;
  onStress: () => void;
}

/** 标题 + 运行动作按钮 + 运行进度状态 */
export function RunControls({
  expertMode,
  onToggleExpert,
  loading,
  loadingAction,
  checkingReadiness,
  dateRangeInvalid,
  onRun,
  onLoadLatest,
  onStress,
}: RunControlsProps) {
  const runningStatus = checkingReadiness
    ? '检查本地数据'
    : loadingAction === 'run'
      ? '完整研究运行中'
      : loadingAction === 'stress'
        ? '三行情景测评中'
        : loadingAction === 'backtest'
          ? '详细回测刷新中'
          : loadingAction === 'load'
            ? '读取上次报告'
            : null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-3">
        <div>
          <h2 className="text-base font-semibold tracking-tight text-slate-100">
            {expertMode ? 'Factor Lab / 因子实验室' : '策略体检报告'}
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            {expertMode
              ? '完整研究拆解视角：因子排行、滚动验证与详细回测。'
              : '检查这套 ML 选股策略是否值得观察、风险在哪里、信号来自哪些股票。'}
          </p>
        </div>
        {runningStatus && (
          <Tag tone="accent">
            <Loader2 className="h-3 w-3 animate-spin" />
            {runningStatus}
          </Tag>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={onRun} disabled={loading || dateRangeInvalid} className={BTN_PRIMARY}>
          {loadingAction === 'run' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
          开新实验
        </button>
        <button type="button" onClick={onLoadLatest} disabled={loading} className={BTN_NEUTRAL}>
          {loadingAction === 'load' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Activity className="h-3.5 w-3.5" />}
          查看上次报告
        </button>
        <button type="button" onClick={onStress} disabled={loading || dateRangeInvalid} className={BTN_OK}>
          {loadingAction === 'stress' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
          快速情景测评
        </button>
        <button type="button" onClick={onToggleExpert} className={BTN_NEUTRAL}>
          {expertMode ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          {expertMode ? '返回客户视图' : '查看研究细节'}
        </button>
      </div>
    </div>
  );
}
