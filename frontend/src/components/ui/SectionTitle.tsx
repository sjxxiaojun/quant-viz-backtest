import React from 'react';
import { cn } from '../../utils';

export interface SectionTitleProps {
  children: React.ReactNode;
  /** 标题右侧插槽 (状态、操作按钮等) */
  right?: React.ReactNode;
  className?: string;
}

/** 面板区块标题: 小号大写字距标签 */
export function SectionTitle({ children, right, className }: SectionTitleProps) {
  return (
    <div className={cn('mb-3 flex items-center justify-between gap-2', className)}>
      <h3 className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">
        {children}
      </h3>
      {right != null && <div className="flex items-center gap-2">{right}</div>}
    </div>
  );
}
