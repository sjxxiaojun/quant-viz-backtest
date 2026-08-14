/**
 * Factor Lab 文案映射与展示格式化（无 React 依赖，可单测）。
 * 涨跌/买卖色一律走 utils 的 A股语义工具；面板底色走 index.css tokens。
 */
import { formatPercent as formatPercentBase } from '../../utils';
import { factorLabPoolOptions } from '../../config/strategies';
import type { FactorLabMetricItem, FactorLabResult, FactorLabRunConfig } from '../../types';

export const STRATEGY_COPY: Record<string, { name: string; shortDesc: string; suitableFor: string }> = {
  ml_factor_ranker: {
    name: '排序策略',
    shortDesc: '把候选股票按综合得分排队，优先拿最强的一组。',
    suitableFor: '适合想先追求收益弹性、能接受一定波动的人。',
  },
  ml_factor_filter: {
    name: '筛选策略',
    shortDesc: '先排除质量不稳的标的，再从剩余股票里挑更稳的一组。',
    suitableFor: '适合更在意回撤控制、希望组合更平滑的人。',
  },
};

/* ---------------- 数值格式化 ---------------- */

export function formatValue(
  value: number | string | null | undefined,
  format: FactorLabMetricItem['format'] = 'number'
): string {
  if (value === null || value === undefined) return '--';
  if (typeof value === 'string') return value;
  if (format === 'percent') return `${(value * 100).toFixed(2)}%`;
  if (format === 'integer') return Math.round(value).toString();
  if (format === 'ratio') return value.toFixed(Math.abs(value) < 1 ? 3 : 2);
  return value.toFixed(2);
}

/** 比率 → 百分比文本 (0.1234 → 12.34%)，无效值返回 -- */
export function fmtPct(value: number | null | undefined): string {
  return formatPercentBase(value);
}

/** 比率绝对值 → 百分比文本 (回撤等只关心幅度的场景) */
export function fmtAbsPct(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '--';
  return formatPercentBase(Math.abs(value));
}

export function formatCompactNumber(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return '--';
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

export function formatCny(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '--';
  return new Intl.NumberFormat('zh-CN', { style: 'currency', currency: 'CNY', maximumFractionDigits: 0 }).format(value);
}

export function formatVersionShort(versionId: string | undefined | null): string {
  if (!versionId) return '--';
  if (versionId.length <= 28) return versionId;
  return `${versionId.slice(0, 18)}…${versionId.slice(-8)}`;
}

export function formatConfigSummary(config: Partial<FactorLabRunConfig> | null | undefined): string {
  if (!config) return '--';
  const poolLabel = config.pool
    ? (factorLabPoolOptions.find((option) => option.value === config.pool)?.label ?? config.pool)
    : null;
  const parts = [
    config.start_date ? `开始 ${config.start_date}` : null,
    config.end_date ? `结束 ${config.end_date}` : null,
    poolLabel ? `股票池 ${poolLabel}` : null,
    config.top_n ? `Top ${config.top_n}` : null,
    config.max_symbols ? `样本上限 ${config.max_symbols} 只` : null,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join('，') : '--';
}

/* ---------------- 领域文案映射 ---------------- */

export function formatStrategyLabel(factor: string | undefined): string {
  if (!factor) return '--';
  return STRATEGY_COPY[factor]?.name ?? factor;
}

const SCORE_SOURCE_MAP: Record<string, string> = {
  walk_forward_composite_score: '滚动样本外综合分',
  walk_forward_score: '滚动样本外模型分',
  composite_score: '综合因子分',
  ml_score: '机器学习分',
  baseline_score: '基线模型分',
  score: '模型分数',
};

export function formatScoreSource(source: string | undefined): string {
  return source ? (SCORE_SOURCE_MAP[source] ?? source) : '后端未返回';
}

export function formatModelBlend(result: FactorLabResult | null): string {
  const recipe = result?.summary.model_recipe ?? result?.research_iteration?.model_recipe;
  if (!recipe) return '融合比例后端未返回';
  return `线性 ${fmtPct(recipe.baseline_weight)} / 非线性 ${fmtPct(recipe.nonlinear_weight)}`;
}

export function formatOosState(value: boolean | undefined): string {
  if (value === true) return '是';
  if (value === false) return '否';
  return '未返回';
}

export function signalState(value: number | undefined): { label: string; active: boolean } {
  if (value === 1) return { label: '触发', active: true };
  if (value === 0 || value === undefined) return { label: '观察', active: false };
  return { label: '未知', active: false };
}

const FOCUS_POINT_MAP: Record<string, string> = {
  turnover: '更看重换手节奏是否稳定，避免组合频繁大换仓。',
  turnover_stability: '更看重换手节奏是否稳定，避免组合频繁大换仓。',
  drawdown: '重点盯回撤控制，防止收益不错但过程过于难熬。',
  max_drawdown: '重点盯回撤控制，防止收益不错但过程过于难熬。',
  cost: '重点看交易成本是否侵蚀收益。',
  cost_drag: '重点看交易成本是否侵蚀收益。',
  coverage: '重点看有效样本覆盖是否足够，避免结果只靠少量股票。',
  win_rate: '重点看胜率是否稳定，不只看少数大赚样本。',
  quality: '重点看信号质量是否稳定，避免一段时间失真。',
  regime: '重点看不同市场环境下表现是否分化明显。',
  liquidity: '重点看流动性约束，避免选到难成交的股票。',
};

export function explainFocusPoint(point: string): string {
  const raw = point.trim();
  return FOCUS_POINT_MAP[raw.toLowerCase()] || raw;
}

const FACTOR_NAME_MAP: Record<string, string> = {
  open_gap: '开盘跳空',
  intraday_ret: '日内涨跌',
  ma_gap_20d: '20日均线距离',
  drawdown_20d: '20日回撤',
  amplitude: '振幅',
  turnover_rate: '换手率',
  turnover_z20: '换手异常度',
  amount_ratio_20d: '成交额变化',
  relative_strength_20d: '相对强弱',
  market_breadth_20d: '市场广度',
  market_ret_1d: '大盘当日表现',
  value_pe: '市盈率估值',
  value_pb: '市净率估值',
  value_ps: '市销率估值',
  value_pcf: '现金流估值',
};

export function formatFactorPlainName(feature: string): string {
  const normalized = feature.toLowerCase();
  if (FACTOR_NAME_MAP[normalized]) return FACTOR_NAME_MAP[normalized];
  if (/^mom_\d+d/.test(normalized)) return `${normalized.match(/\d+/)?.[0] ?? ''}日价格动量`;
  if (/^reversal_\d+d/.test(normalized)) return `${normalized.match(/\d+/)?.[0] ?? ''}日反转`;
  if (/^volatility_\d+d/.test(normalized)) return `${normalized.match(/\d+/)?.[0] ?? ''}日波动率`;
  if (/^volume_ratio_\d+d/.test(normalized)) return `${normalized.match(/\d+/)?.[0] ?? ''}日成交量变化`;
  if (normalized.endsWith('_rank')) return `${formatFactorPlainName(normalized.replace(/_rank$/, ''))}排名`;
  return feature.replace(/_/g, ' ');
}

export function explainFeature(feature: string): string {
  const normalized = feature.toLowerCase();
  if (normalized.includes('mom') || normalized.includes('relative_strength')) return '看股票最近是不是比其他股票更强。';
  if (normalized.includes('reversal')) return '看短期下跌后是否有反弹特征。';
  if (normalized.includes('volatility') || normalized.includes('amplitude')) return '看价格波动是否过大或过小。';
  if (normalized.includes('turnover') || normalized.includes('volume') || normalized.includes('amount')) return '看成交是否活跃，避免信号只停留在纸面上。';
  if (normalized.includes('value') || normalized.includes('pe') || normalized.includes('pb')) return '看价格相对基本面是否便宜或昂贵。';
  if (normalized.includes('gap') || normalized.includes('intraday')) return '看当天开盘和盘中价格行为是否透露短期情绪。';
  if (normalized.includes('market')) return '看整体市场环境是否支持这个信号。';
  return '模型认为这个指标对股票排序有解释力。';
}

const CANDIDATE_STATUS_LABELS: Record<string, string> = {
  production: '当前生产规则',
  draft: '待验证候选',
  research_pass: '研究层通过',
  shadow: '影子观察',
  approved: '已审批',
  active: '已纳入',
  retired: '已回滚',
  rejected: '已拒绝',
  ready_to_promote: '可提升候选',
  research_only: '研究观察',
  no_promotion: '暂不晋级',
  promoted: '本轮入模',
  watch: '观察候选',
  skipped: '样本不足',
  tested_this_run: '本轮已测',
  included_this_run: '本轮入模',
};

export function getCandidateStatusLabel(status: string | undefined): string {
  return CANDIDATE_STATUS_LABELS[status ?? ''] ?? (status || '--');
}

export function getScenarioPlainText(scenario: string): string {
  if (scenario === 'bull') return '假设市场整体偏强，重点看策略能否跟上机会。';
  if (scenario === 'bear') return '假设市场整体走弱，重点看回撤和生存率。';
  return '假设市场来回震荡，重点看是否被成本和换手磨损。';
}

/* ---------------- 语义色 (设计 token) ---------------- */

export type ReliabilityStatus = 'good' | 'warn' | 'bad' | 'neutral';

export function getReliabilityTone(status: ReliabilityStatus): string {
  const tones: Record<ReliabilityStatus, string> = {
    good: 'border-ok/25 bg-ok/10 text-ok',
    warn: 'border-warn/25 bg-warn/10 text-warn',
    bad: 'border-rose-500/25 bg-rose-500/10 text-rose-300',
    neutral: 'border-line bg-bg2 text-slate-300',
  };
  return tones[status];
}

export function getVerdictTone(level: 'strong' | 'watch' | 'weak'): string {
  const tones = {
    strong: 'border-ok/25 bg-ok/10 text-ok',
    watch: 'border-accent/25 bg-accent/10 text-accent',
    weak: 'border-warn/25 bg-warn/10 text-warn',
  };
  return tones[level];
}

export function getPromotionTone(status: string | undefined): string {
  if (status === 'active' || status === 'approved' || status === 'research_pass') return 'border-ok/25 bg-ok/10 text-ok';
  if (status === 'shadow') return 'border-accent/25 bg-accent/10 text-accent';
  if (status === 'no_promotion') return 'border-warn/25 bg-warn/10 text-warn';
  return 'border-line bg-bg2 text-slate-300';
}

/** A股语义: 牛市红(up)、熊市绿(down)、震荡中性 */
export function getScenarioTone(scenario: string): string {
  if (scenario === 'bull') return 'border-up/25 bg-up/10 text-up-soft';
  if (scenario === 'bear') return 'border-down/25 bg-down/10 text-down-soft';
  return 'border-accent/25 bg-accent/10 text-accent';
}

/* ---------------- 通用控件样式 ---------------- */

export const BTN_BASE =
  'inline-flex items-center gap-1.5 rounded-ctl border px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40';
export const BTN_PRIMARY = `${BTN_BASE} border-accent/40 bg-accent/15 text-accent hover:bg-accent/25`;
export const BTN_NEUTRAL = `${BTN_BASE} border-line bg-bg2 text-slate-300 hover:bg-bg3 hover:text-slate-100`;
export const BTN_OK = `${BTN_BASE} border-ok/30 bg-ok/10 text-ok hover:bg-ok/20`;
export const BTN_WARN = `${BTN_BASE} border-warn/30 bg-warn/10 text-warn hover:bg-warn/20`;
