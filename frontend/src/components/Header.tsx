import { cn } from '../utils';
import type { AppView } from '../hooks/useView';
const groups: { label: string; items: [AppView, string][] }[] = [
  { label: '研究', items: [['mall', '策略大厅'], ['console', '回测'], ['dashboard', '绩效'], ['compare', '策略对比'], ['factorLab', '因子研究']] },
  { label: '模拟盘', items: [['virtualTrade', '模拟账户'], ['dailyReport', '日报'], ['overnight', '隔夜观察']] },
  { label: '数据与任务', items: [['tasks', '数据与任务']] },
];
export function Header({ view, setView }: { view: AppView; setView: (view: AppView) => void }) {
  return <header className="space-y-5"><div><h1 className="text-3xl font-black text-blue-500">momo quant pro</h1><p className="text-xs text-slate-500">日线研究与模拟账户 · 数据、规则和结果可追溯</p></div>
    <nav className="flex flex-wrap gap-4">{groups.map(group => <div key={group.label} className="rounded-xl border border-blue-900/30 bg-slate-950/30 p-2"><span className="px-2 text-xs text-slate-500">{group.label}</span>{group.items.map(([key,label]) => <a href={`#${key}`} key={key} onClick={e => { e.preventDefault(); setView(key); }} className={cn('inline-block rounded-lg px-3 py-2 text-xs', view === key ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white')}>{label}</a>)}</div>)}</nav>
  </header>;
}
