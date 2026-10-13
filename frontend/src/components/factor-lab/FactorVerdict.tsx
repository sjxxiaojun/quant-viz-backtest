import { cn } from '../../utils';
import { getVerdictTone, buildUserVerdict } from './presenters';
import type { FactorLabResult } from '../../types';
export function FactorVerdict({
  displayedResult,
  userVerdict,
}: {
  displayedResult: FactorLabResult | null;
  userVerdict: ReturnType<typeof buildUserVerdict> | null;
}) {
  return (
    <article
      className="xl:col-span-7 rounded-panel p-4 backdrop-blur-xl shadow-panel space-y-5"
      style={{
        background: 'rgba(13, 27, 50, 0.5)',
        borderWidth: '1px',
        borderStyle: 'solid',
        borderColor: 'rgba(59, 130, 246, 0.08)',
      }}
    >
      <div className="flex flex-col lg:flex-row lg:items-start lg:justify-between gap-5">
        <div className="space-y-3">
          <div className="text-[11px] font-bold tracking-[0.18em] text-cyan-300">
            本次研究结论
          </div>
          <h3 className="text-xl font-semibold text-slate-100">
            {userVerdict?.title ?? '等待真实研究结果'}
          </h3>
          <p className="text-sm text-slate-300 leading-relaxed max-w-3xl">
            {userVerdict?.summary ??
              '系统会先检查数据，再用历史行情验证这套选股打分规则是否真的有区分度。'}
          </p>
          {displayedResult?.summary.sample_source_note && (
            <p className="text-xs text-slate-500 leading-relaxed max-w-3xl">
              {displayedResult.summary.sample_source_note}
            </p>
          )}
        </div>
        {userVerdict && (
          <div
            className={cn(
              'rounded-panel border px-5 py-4 min-w-[160px]',
              getVerdictTone(userVerdict.level),
            )}
          >
            <div className="text-[10px] font-bold tracking-[0.18em] opacity-80">
              可信度
            </div>
            <div className="mt-2 text-xl font-semibold">
              {userVerdict.score}
            </div>
            <div className="text-xs opacity-80">满分 100</div>
          </div>
        )}
      </div>

      {userVerdict && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="rounded-2xl border border-slate-700/40 bg-slate-950/20 p-4 lg:col-span-2">
            <div className="text-[10px] font-bold tracking-[0.18em] text-slate-500">
              为什么这么判断
            </div>
            <div className="mt-3 space-y-2 text-sm leading-relaxed text-slate-200">
              {userVerdict.reasons.map((reason) => (
                <p key={reason}>{reason}</p>
              ))}
            </div>
          </div>
          <div className="rounded-2xl border border-amber-500/20 bg-amber-500/10 p-4">
            <div className="text-[10px] font-bold tracking-[0.18em] text-amber-200">
              主要风险
            </div>
            <div className="mt-3 space-y-2 text-sm leading-relaxed text-amber-50/90">
              {userVerdict.risks.map((risk) => (
                <p key={risk}>{risk}</p>
              ))}
            </div>
          </div>
        </div>
      )}
      {(displayedResult?.summary.run_difference_note ||
        (displayedResult?.summary.run_difference_reasons ?? []).length > 0) && (
        <div className="rounded-2xl border border-cyan-500/15 bg-cyan-500/5 p-4 text-sm leading-relaxed text-cyan-50/90">
          <div className="font-semibold text-cyan-100">
            {displayedResult?.summary.run_difference_note ||
              '本轮结果已重新训练和重新调权。'}
          </div>
          {(displayedResult?.summary.run_difference_reasons ?? [])
            .slice(0, 3)
            .map((reason) => (
              <p key={reason} className="mt-2 text-xs text-cyan-100/75">
                {reason}
              </p>
            ))}
        </div>
      )}
    </article>
  );
}
