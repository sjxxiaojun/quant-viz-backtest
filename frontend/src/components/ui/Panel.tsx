import React from 'react';
import { cn } from '../../utils';

export interface PanelProps extends React.HTMLAttributes<HTMLDivElement> {
  /** 1 = 一级面板 (bg1), 2 = 嵌套面板 (bg2) */
  level?: 1 | 2;
  /** 默认带 p-4 内边距; 传 false 自行控制 */
  padded?: boolean;
}

/** 终端面板容器: 分层底色 + 细边框 + 8px 圆角 */
export function Panel({ level = 1, padded = true, className, ...rest }: PanelProps) {
  return (
    <div
      className={cn(
        'border border-line',
        level === 1 ? 'rounded-panel bg-bg1' : 'rounded-ctl bg-bg2',
        padded && 'p-4',
        className,
      )}
      {...rest}
    />
  );
}
