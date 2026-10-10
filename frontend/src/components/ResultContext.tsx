import type { BacktestResult } from '../types';
import { Panel } from './ui';

export function ResultContext({ result }: { result: BacktestResult | null }) {
  if (!result) return null;
  return <Panel><div className="flex flex-wrap gap-4 text-sm"><span>行情截至 {result.data_as_of ?? '未标注'}</span><span>规则 {result.engine_version ?? '旧口径'}</span><span>成交 {result.strategy_behavior?.execution_mode ?? '未标注'}</span><span>完整成交 {result.trades_total ?? result.trades.length} 笔</span></div>
    {result.quality_notes?.map(note => <p key={note} className="mt-2 text-xs text-amber-300">{note}</p>)}
    <details className="mt-3 text-xs text-slate-400"><summary>实际生效参数与数据凭证</summary><pre className="overflow-auto">{JSON.stringify({ request: result.request, snapshot: result.data_snapshot_id, strategy_version: result.strategy_version }, null, 2)}</pre></details>
  </Panel>;
}
