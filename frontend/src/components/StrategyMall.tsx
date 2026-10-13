import { AlertTriangle, ChevronRight } from 'lucide-react';
import { EmptyState, Panel, SectionTitle, Skeleton, Tag } from './ui';
import { useStrategyCatalog } from '../hooks/useStrategyCatalog';
import {
  getExecutionModeLabel,
  getHoldingPolicyLabel,
  getPoolShortLabel,
  groupByCategory,
  type StrategyCatalogEntry,
} from '../api/strategyCatalog';

interface StrategyMallProps {
  onRun: (factor: string) => void;
}

function StrategyRow({ entry, onRun }: { entry: StrategyCatalogEntry; onRun: (id: string) => void }) {
  return (
    <button
      type="button"
      onClick={() => onRun(entry.id)}
      className="group flex w-full flex-col gap-1.5 rounded-ctl border border-line bg-bg2 px-3 py-2.5 text-left transition-colors hover:border-accent/40 hover:bg-bg3"
      title={entry.desc}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[13px] font-semibold text-slate-200 group-hover:text-accent">
          {entry.name}
        </span>
        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-600 transition-transform group-hover:translate-x-0.5 group-hover:text-accent" />
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <Tag tone={entry.assetClass === 'etf' ? 'warn' : 'accent'}>
          {getPoolShortLabel(entry.pool)}
        </Tag>
        <Tag>{getExecutionModeLabel(entry.executionMode)}</Tag>
        <Tag>{getHoldingPolicyLabel(entry.holdingPolicy)}</Tag>
        {entry.requiresArtifact && <Tag tone="warn">依赖模型工件</Tag>}
        {entry.canonicalStrategyId && entry.canonicalStrategyId !== entry.id && <Tag tone="warn">兼容别名 · {entry.canonicalStrategyId}</Tag>}
      </div>
      {entry.desc && (
        <p className="line-clamp-2 text-[11px] leading-relaxed text-slate-500">{entry.desc}</p>
      )}
      {Object.values(entry.factorSemantics ?? {}).map(note => <p key={note} className="text-[10px] text-amber-300/80">{note}</p>)}
    </button>
  );
}

export function StrategyMall({ onRun }: StrategyMallProps) {
  const { catalog, loading, fallbackReason } = useStrategyCatalog();

  if (loading) {
    return (
      <div className="space-y-4">
        <Panel>
          <SectionTitle>策略目录</SectionTitle>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 9 }, (_, i) => (
              <Skeleton key={i} className="h-[76px]" />
            ))}
          </div>
        </Panel>
      </div>
    );
  }

  if (catalog.length === 0) {
    return (
      <EmptyState
        title="策略目录为空"
        description="后端未返回任何策略，请确认服务已启动。"
      />
    );
  }

  const groups = groupByCategory(catalog);

  return (
    <div className="space-y-4">
      {fallbackReason && (
        <div className="flex items-start gap-2 rounded-panel border border-warn/30 bg-warn/10 px-3 py-2 text-[11px] text-warn">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>策略目录接口不可用，当前展示本地内置策略（{fallbackReason}）。</span>
        </div>
      )}
      <div className="flex items-baseline justify-between">
        <h2 className="text-sm font-semibold text-slate-200">策略目录</h2>
        <span className="label-caps">
          共 <span className="num text-slate-300">{catalog.length}</span> 套 · 点击进入仿真控制台
        </span>
      </div>
      <div className="space-y-4">
        {groups.map(([category, entries]) => (
          <Panel key={category} padded={false} className="p-3">
            <SectionTitle
              right={<span className="num text-[10px] text-slate-600">{entries.length}</span>}
            >
              {category}
            </SectionTitle>
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
              {entries.map((entry) => (
                <StrategyRow key={entry.id} entry={entry} onRun={onRun} />
              ))}
            </div>
          </Panel>
        ))}
      </div>
    </div>
  );
}
