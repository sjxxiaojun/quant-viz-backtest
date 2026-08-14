import React from 'react';
import { changeToneClass, cn, formatSignedPercent } from '../../utils';

export interface StatProps {
  label: string;
  value: React.ReactNode;
  /** 涨跌比率 (0.12 = +12%), 自动按红涨绿跌着色 */
  delta?: number | null;
  /** 值本身按 delta 语义着色 (用于收益率这类主数值) */
  toneByDelta?: boolean;
  hint?: string;
  className?: string;
}

/** 指标块: 标签 + 等宽数字主值 + 可选涨跌角标 */
export function Stat({ label, value, delta, toneByDelta = false, hint, className }: StatProps) {
  return (
    <div className={cn('min-w-0', className)}>
      <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500" title={hint}>
        {label}
      </div>
      <div className="mt-1 flex items-baseline gap-2">
        <span
          className={cn(
            'num text-lg font-semibold leading-tight',
            toneByDelta && delta != null ? changeToneClass(delta) : 'text-slate-100',
          )}
        >
          {value}
        </span>
        {delta != null && !toneByDelta && (
          <span className={cn('num text-[11px] font-medium', changeToneClass(delta))}>
            {formatSignedPercent(delta)}
          </span>
        )}
      </div>
    </div>
  );
}
