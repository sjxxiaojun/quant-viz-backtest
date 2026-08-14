import React from 'react';
import { cn } from '../../utils';

export interface SkeletonProps {
  className?: string;
}

/** 单个骨架块 (自行控制尺寸) */
export function Skeleton({ className }: SkeletonProps) {
  return <div className={cn('animate-pulse rounded-ctl bg-bg3', className)} />;
}

export interface SkeletonLinesProps {
  /** 行数, 默认 3 */
  lines?: number;
  className?: string;
}

/** 多行文本骨架 */
export function SkeletonLines({ lines = 3, className }: SkeletonLinesProps) {
  return (
    <div className={cn('space-y-2', className)}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={cn('h-3', i === lines - 1 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  );
}
