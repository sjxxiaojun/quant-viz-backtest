import React from 'react';
import { cn } from '../../utils';

export interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
}

/** 空态占位: 图标 + 标题 + 说明 + 可选操作 */
export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-2 rounded-panel border border-dashed border-line px-6 py-10 text-center',
        className,
      )}
    >
      {icon != null && <div className="text-slate-600">{icon}</div>}
      <div className="text-sm font-medium text-slate-300">{title}</div>
      {description && <div className="max-w-md text-xs text-slate-500">{description}</div>}
      {action != null && <div className="mt-2">{action}</div>}
    </div>
  );
}
