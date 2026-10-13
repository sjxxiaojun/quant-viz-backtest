import { ShieldCheck, Loader2 } from 'lucide-react';
export function FactorTaskState({
  runningStatus,
  needsBackfill,
  readinessMessages,
}: {
  runningStatus: string | null;
  needsBackfill: boolean;
  readinessMessages: string[];
}) {
  return (
    <div className="rounded-panel border border-amber-400/20 bg-amber-400/10 p-4 space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex items-center gap-2 text-sm font-semibold text-amber-100">
          <ShieldCheck className="w-4 h-4" />
          数据准备情况
        </div>
        {runningStatus && (
          <span className="inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-xs font-semibold text-cyan-100">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            {runningStatus}
          </span>
        )}
        {needsBackfill && (
          <span className="inline-flex rounded-full border border-amber-300/20 bg-amber-300/10 px-3 py-1 text-xs font-semibold text-amber-100">
            包含历史补数，可能较慢
          </span>
        )}
      </div>
      <div className="space-y-2 text-sm text-amber-50/90">
        {readinessMessages.map((message) => (
          <p key={message}>{message}</p>
        ))}
      </div>
    </div>
  );
}
