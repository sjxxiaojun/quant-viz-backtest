/** 状态/时间等展示辅助 (纯函数, 与组件解耦) */
import type { AIWorkMessage, AutomationRun } from './types';
import type { TagTone } from '../ui';

/**
 * 运行状态 → 文本色。注意: 状态色使用 ok/warn/accent, 失败态复用 up(红) 家族,
 * 数值涨跌一律走 changeToneClass, 两者不会同时出现在同一数字上。
 */
export function statusToneClass(status?: string): string {
  if (status === 'success' || status === 'ready' || status === 'executed') return 'text-ok';
  if (status === 'running') return 'text-accent';
  if (status === 'partial' || status === 'degraded' || status === 'skipped' || status === 'dry_run') {
    return 'text-warn';
  }
  if (status === 'failed' || status === 'blocked' || status === 'rejected') return 'text-up-soft';
  return 'text-slate-400';
}

/** AI 消息 → Tag 语义 tone */
export function messageTagTone(message?: AIWorkMessage): TagTone {
  if (message?.level === 'error' || ['failed', 'rejected', 'blocked'].includes(message?.status || '')) {
    return 'up';
  }
  if (message?.level === 'warn' || ['partial', 'skipped', 'degraded'].includes(message?.status || '')) {
    return 'warn';
  }
  if (message?.status === 'running') return 'accent';
  return 'ok';
}

export function workItemTagTone(status?: string): TagTone {
  if (status === 'executed' || status === 'planned') return 'ok';
  if (status === 'failed' || status === 'rejected') return 'up';
  return 'default';
}

export function formatAutomationTime(value?: string | null): string {
  if (!value) return '--';
  return value.slice(0, 16).replace('T', ' ');
}

/**
 * 找出最近一次尚未被后续成功运行覆盖的异常任务:
 * 按时间倒序扫描, 同 job_type 出现过成功/跳过即视为已恢复。
 */
export function findUnresolvedProblemRun(runs?: AutomationRun[]): AutomationRun | undefined {
  const recoveredJobTypes = new Set<string>();
  for (const run of runs || []) {
    if (['failed', 'partial'].includes(run.status)) {
      if (!recoveredJobTypes.has(run.job_type)) return run;
      continue;
    }
    if (['success', 'dry_run', 'executed', 'skipped'].includes(run.status)) {
      recoveredJobTypes.add(run.job_type);
    }
  }
  return undefined;
}
