import { Activity, Bot, ClipboardList, FlaskConical, Play, Shield, type LucideIcon } from 'lucide-react';
import { cn } from '../../utils';
import { EmptyState, Panel, SectionTitle, Tag } from '../ui';
import type { AutomationJobKind, AutomationStatus } from './types';
import {
  findUnresolvedProblemRun,
  formatAutomationTime,
  messageTagTone,
  statusToneClass,
  workItemTagTone,
} from './presenters';

interface AutomationPanelProps {
  status: AutomationStatus | null;
  error: string | null;
  runningJob: AutomationJobKind | null;
  onRunJob: (kind: AutomationJobKind) => void;
}

const JOB_ACTIONS: Array<{ kind: AutomationJobKind; label: string; Icon: LucideIcon }> = [
  { kind: 'snapshot', label: '抓盘中快照', Icon: Activity },
  { kind: 'eodUpdate', label: '收盘补数', Icon: Shield },
  { kind: 'virtualTrade', label: '追赶模拟盘', Icon: Play },
  { kind: 'aiCycle', label: '运行 AI cycle', Icon: Bot },
  { kind: 'aiSimulationCare', label: 'AI 托管模拟池', Icon: ClipboardList },
  { kind: 'aiFactorLabCare', label: 'AI 照料因子实验', Icon: FlaskConical },
];

/** 自动化与 AI 运行层: 概览指标 + 任务按钮 + 消息流 + 托管日志 */
export function AutomationPanel({ status, error, runningJob, onRunJob }: AutomationPanelProps) {
  const freshness = status?.data_freshness;
  const latestRun = status?.recent_runs?.[0];
  const activeEodUpdate = Boolean(
    status?.recent_runs?.some((run) => run.job_type === 'eod_update' && run.status === 'running'),
  );
  const latestProblemRun = findUnresolvedProblemRun(status?.recent_runs);
  const latestSnapshot = status?.recent_snapshots?.[0];
  const latestDecision = status?.ai_decisions?.[0];
  const latestWorkLog = status?.ai_work_logs?.[0];
  const latestMessage = status?.ai_work_messages?.[0];
  const nextJob = status?.scheduler?.next_jobs?.[0];
  const messages = status?.ai_work_messages || [];
  const workLogs = status?.ai_work_logs || [];

  return (
    <Panel className="space-y-4">
      <SectionTitle
        right={
          <div className="flex flex-wrap justify-end gap-1.5">
            {JOB_ACTIONS.map(({ kind, label, Icon }) => {
              const disabled = runningJob !== null || (kind === 'eodUpdate' && activeEodUpdate);
              const buttonLabel = kind === 'eodUpdate' && activeEodUpdate ? '补数运行中' : label;
              return (
                <button
                  key={kind}
                  type="button"
                  onClick={() => onRunJob(kind)}
                  disabled={disabled}
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-ctl border px-2.5 py-1.5 text-[11px] font-medium transition-colors',
                    runningJob === kind
                      ? 'border-accent/40 bg-accent/10 text-accent'
                      : 'border-line bg-bg2 text-slate-300 hover:border-accent/40 hover:text-slate-100',
                    disabled && runningJob !== kind && 'cursor-not-allowed opacity-40',
                  )}
                >
                  <Icon className="h-3 w-3" />
                  {runningJob === kind ? '执行中...' : buttonLabel}
                </button>
              );
            })}
          </div>
        }
      >
        自动化与 AI 运行层 · 数据补数 / 模拟盘追赶 / AI 白名单动作
      </SectionTitle>

      {error && (
        <div className="rounded-ctl border border-up/30 bg-up/10 px-3 py-2 text-xs text-up-soft">
          {error}
        </div>
      )}

      {/* 概览指标行 */}
      <div className="grid grid-cols-2 gap-2 xl:grid-cols-4">
        <Panel level={2} padded={false} className="p-3">
          <div className="label-caps">数据新鲜度</div>
          <div className={cn('num mt-1 text-lg font-semibold', statusToneClass(freshness?.status))}>
            {freshness?.score != null ? `${freshness.score.toFixed(1)}%` : '--'}
          </div>
          <div className="mt-0.5 text-[11px] text-slate-400">
            目标 {freshness?.target_date || '--'} · {freshness?.status || 'unknown'}
          </div>
          <div className="num mt-0.5 text-[10px] text-slate-500">
            A股 {freshness?.a_share?.fresh_count ?? 0}/{freshness?.a_share?.checked_count ?? 0}
            (本地 {freshness?.a_share?.total_local ?? 0}) · ETF {freshness?.etf?.fresh_count ?? 0}/
            {freshness?.etf?.checked_count ?? 0}(本地 {freshness?.etf?.total_local ?? 0})
          </div>
        </Panel>

        <Panel level={2} padded={false} className="p-3">
          <div className="label-caps">调度器</div>
          <div
            className={cn(
              'mt-1 text-lg font-semibold',
              status?.scheduler?.running ? 'text-ok' : 'text-warn',
            )}
          >
            {status?.scheduler?.enabled ? (status.scheduler.running ? '运行中' : '已启用') : '未启用'}
          </div>
          <div className="num mt-0.5 text-[11px] text-slate-400">
            下次 {nextJob ? `${nextJob.work_type || nextJob.job_type} · ${nextJob.run_at.slice(5, 16).replace('T', ' ')}` : '--'}
          </div>
          <div className="mt-0.5 text-[10px] text-slate-500">
            最近任务 {latestRun ? `${latestRun.job_type} / ${latestRun.status}` : '暂无'}
          </div>
        </Panel>

        <Panel level={2} padded={false} className="p-3">
          <div className="label-caps">盘中快照</div>
          <div className="num mt-1 text-lg font-semibold text-accent">
            {latestSnapshot?.row_count ?? 0} 条
          </div>
          <div className="num mt-0.5 text-[11px] text-slate-400">
            {latestSnapshot?.captured_at || '尚未抓取'}
          </div>
          <div className="mt-0.5 text-[10px] text-slate-500">
            {latestSnapshot?.source || '--'} · {latestSnapshot?.market_session || '--'}
          </div>
        </Panel>

        <Panel level={2} padded={false} className="p-3">
          <div className="label-caps">AI 决策</div>
          <div className={cn('mt-1 text-lg font-semibold', statusToneClass(latestDecision?.status))}>
            {latestDecision?.status || '暂无'}
          </div>
          <div className="mt-0.5 line-clamp-2 text-[11px] text-slate-400">
            {latestDecision?.summary || '等待外部 AI 或本地 guardrail 产生日报。'}
          </div>
          <div className="mt-0.5 text-[10px] text-slate-500">
            {latestDecision?.actions?.map((action) => action.type).filter(Boolean).join(' · ') || '--'}
          </div>
        </Panel>
      </div>

      {/* AI 消息流 */}
      <Panel level={2} padded={false} className="overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2">
          <span className="label-caps">AI 消息 · 时间 / 内容 / 结果</span>
          <span className={cn('text-[11px] font-medium', statusToneClass(latestMessage?.status))}>
            {latestMessage ? `${latestMessage.work_type} / ${latestMessage.status}` : '暂无消息'}
          </span>
        </div>
        {messages.length ? (
          <div className="divide-y divide-line">
            {messages.slice(0, 12).map((message) => (
              <div
                key={message.message_id}
                className="grid grid-cols-1 gap-1.5 px-3 py-2 text-xs lg:grid-cols-[190px_1fr_220px] lg:gap-3"
              >
                <div>
                  <div className="font-medium text-slate-200">
                    {message.title || `${message.action_type || 'AI 动作'} / ${message.status}`}
                  </div>
                  <div className="num mt-0.5 text-[10px] text-slate-500">
                    {formatAutomationTime(message.created_at)} · {message.trigger || '--'}
                  </div>
                </div>
                <div className="leading-5 text-slate-300">{message.body || 'AI 已记录一次操作。'}</div>
                <div className="flex flex-wrap content-start gap-1 lg:justify-end">
                  <Tag tone={messageTagTone(message)}>{message.status}</Tag>
                  <Tag>{message.work_type}</Tag>
                  {message.action_type && <Tag>{message.action_type}</Tag>}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="px-3 py-4 text-xs text-slate-500">
            等待 AI 首次运行。之后每一次动作都会在这里按时间记录，包括执行内容、状态和摘要。
          </div>
        )}
      </Panel>

      {/* AI 托管任务总结 */}
      <Panel level={2} padded={false} className="overflow-hidden">
        <div className="flex items-center justify-between gap-3 border-b border-line px-3 py-2">
          <span className="label-caps">AI 托管任务总结</span>
          <span className={cn('text-[11px] font-medium', statusToneClass(latestWorkLog?.status))}>
            {latestWorkLog ? `${latestWorkLog.work_type} / ${latestWorkLog.status}` : '暂无托管日志'}
          </span>
        </div>
        {workLogs.length ? (
          <div className="divide-y divide-line">
            {workLogs.slice(0, 5).map((log) => (
              <div
                key={log.work_id}
                className="grid grid-cols-1 gap-1.5 px-3 py-2 text-xs lg:grid-cols-[190px_1fr_220px] lg:gap-3"
              >
                <div>
                  <div className="font-medium text-slate-200">{log.title || log.work_type}</div>
                  <div className="num mt-0.5 text-[10px] text-slate-500">
                    {formatAutomationTime(log.started_at)} · {log.trigger || '--'}
                  </div>
                </div>
                <div className="leading-5 text-slate-300">
                  {log.summary || log.error || '任务已记录，等待总结。'}
                </div>
                <div className="flex flex-wrap content-start gap-1 lg:justify-end">
                  {(log.work_items || []).slice(0, 4).map((item, index) => (
                    <Tag key={`${log.work_id}-${item.action || index}`} tone={workItemTagTone(item.status)}>
                      {item.action || 'action'} · {item.status || '--'}
                    </Tag>
                  ))}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="px-3 py-4 text-xs text-slate-500">
            等待 AI 托管任务首次运行，完成后会在这里按轮次记录工作总结。
          </div>
        )}
      </Panel>

      {latestProblemRun && (
        <div className="rounded-ctl border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
          最近未恢复异常：{latestProblemRun.job_type} / {latestProblemRun.status}
          {latestProblemRun.started_at ? ` · ${formatAutomationTime(latestProblemRun.started_at)}` : ''}
          {latestProblemRun.error ? ` · ${latestProblemRun.error}` : ''}
        </div>
      )}

      {!status && !error && (
        <EmptyState
          icon={<Bot className="h-6 w-6" />}
          title="自动化状态尚未加载"
          description="等待 /api/automation/status 返回后展示调度器、数据新鲜度与 AI 工作流。"
        />
      )}
    </Panel>
  );
}
