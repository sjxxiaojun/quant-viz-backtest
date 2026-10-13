import React from 'react';

interface StatusBadgeProps {
  sysStatus: {
    data_coverage?: string;
    market_status?: string;
  } | null;
}

export function StatusBadge({ sysStatus }: StatusBadgeProps) {
  if (!sysStatus) return null;

  return (
    <section className="bg-blue-500/5 border border-blue-500/10 rounded-2xl p-6 space-y-4">
      <div className="flex items-center justify-between text-[10px] font-bold text-blue-400 uppercase tracking-widest">
        <span>数据底座</span>
        <span className="text-slate-400">按实际数据核验</span>
      </div>
      <div className="space-y-2 text-[11px]">
        <div className="space-y-1"><span className="text-slate-500">覆盖</span><p className="text-slate-300">{sysStatus.data_coverage}</p></div>
        <div className="flex justify-between"><span className="text-slate-500 italic">状态</span><span className="text-emerald-400 font-bold">{sysStatus.market_status}</span></div>
      </div>
    </section>
  );
}
