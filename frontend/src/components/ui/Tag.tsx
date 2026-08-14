import React from 'react';
import { cn } from '../../utils';

export type TagTone = 'default' | 'accent' | 'up' | 'down' | 'warn' | 'ok';

const toneClasses: Record<TagTone, string> = {
  default: 'border-line text-slate-400 bg-bg2',
  accent: 'border-accent/30 text-accent bg-accent/10',
  up: 'border-up/30 text-up-soft bg-up/10',
  down: 'border-down/30 text-down-soft bg-down/10',
  warn: 'border-warn/30 text-warn bg-warn/10',
  ok: 'border-ok/30 text-ok bg-ok/10',
};

export interface TagProps {
  children: React.ReactNode;
  tone?: TagTone;
  className?: string;
  title?: string;
}

/** 小型语义标签 */
export function Tag({ children, tone = 'default', className, title }: TagProps) {
  return (
    <span
      title={title}
      className={cn(
        'inline-flex items-center gap-1 whitespace-nowrap rounded-ctl border px-1.5 py-0.5 text-[10px] font-medium leading-none',
        toneClasses[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
