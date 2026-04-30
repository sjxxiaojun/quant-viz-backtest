import {
  TrendingUp, BarChart3, Play, BrainCircuit,
  Target, ShieldCheck, Zap, Factory, Flame, Activity
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export type StrategyPool = 'core' | 'blackhorse' | 'etf' | 'power_energy';
export type StrategyAssetClass = 'a_share' | 'etf';
export type RuntimePool = 'auto' | 'core' | 'blackhorse' | 'etf' | 'all' | 'power_energy';

export interface StrategyMeta {
  name: string;
  desc: string;
  icon: LucideIcon;
  category: string;
  tags: string[];
  color: string;
  pool: StrategyPool;
  assetClass: StrategyAssetClass;
}

export interface PoolOption {
  value: string;
  label: string;
}

export interface FactorLabPoolOption extends PoolOption {
  accent: 'blue' | 'violet' | 'cyan';
  description: string;
}

const poolLabelMap: Record<RuntimePool, string> = {
  auto: '系统自动匹配',
  core: 'A股核心池 (Core 15)',
  blackhorse: 'A股弹性池 (Blackhorse 15)',
  etf: 'ETF 精选池',
  power_energy: '电力与储能板块 (Power 15)',
  all: '本地全市场数据池',
};

export const colorMap: Record<string, { bgBlur: string; textBg: string; text: string; border?: string; bg?: string }> = {
  rose:    { bgBlur: 'bg-rose-500',    textBg: 'bg-rose-500/10',    text: 'text-rose-400', border: 'border-rose-500/20', bg: 'bg-rose-500/10' },
  violet:  { bgBlur: 'bg-violet-500',  textBg: 'bg-violet-500/10',  text: 'text-violet-400', border: 'border-violet-500/20', bg: 'bg-violet-500/10' },
  emerald: { bgBlur: 'bg-emerald-500', textBg: 'bg-emerald-500/10', text: 'text-emerald-400', border: 'border-emerald-500/20', bg: 'bg-emerald-500/10' },
  amber:   { bgBlur: 'bg-amber-500',   textBg: 'bg-amber-500/10',   text: 'text-amber-400', border: 'border-amber-500/20', bg: 'bg-amber-500/10' },
  cyan:    { bgBlur: 'bg-cyan-500',    textBg: 'bg-cyan-500/10',    text: 'text-cyan-400', border: 'border-cyan-500/20', bg: 'bg-cyan-500/10' },
  indigo:  { bgBlur: 'bg-indigo-500',  textBg: 'bg-indigo-500/10',  text: 'text-indigo-400', border: 'border-indigo-500/20', bg: 'bg-indigo-500/10' },
  sky:     { bgBlur: 'bg-sky-500',     textBg: 'bg-sky-500/10',     text: 'text-sky-400', border: 'border-sky-500/20', bg: 'bg-sky-500/10' },
  fuchsia: { bgBlur: 'bg-fuchsia-500', textBg: 'bg-fuchsia-500/10', text: 'text-fuchsia-400', border: 'border-fuchsia-500/20', bg: 'bg-fuchsia-500/10' },
  orange:  { bgBlur: 'bg-orange-500',  textBg: 'bg-orange-500/10',  text: 'text-orange-400', border: 'border-orange-500/20', bg: 'bg-orange-500/10' },
  blue:    { bgBlur: 'bg-blue-500',    textBg: 'bg-blue-500/10',    text: 'text-blue-400', border: 'border-blue-500/20', bg: 'bg-blue-500/10' },
};

export const factorLabStrategyMeta: StrategyMeta = {
  name: "策略体检报告 (Factor Lab)",
  desc: "用真实历史数据检查一套 ML 选股打分规则是否值得观察：看高分股票有没有更好、风险多大、成本吃掉多少。",
  icon: BrainCircuit,
  category: "策略体检",
  tags: ["结论解读", "风险检查", "ML 选股"],
  color: "blue",
  pool: "core",
  assetClass: "a_share"
};

export const factorLabPoolOptions: FactorLabPoolOption[] = [
  {
    value: 'core',
    label: '核心蓝筹池',
    accent: 'blue',
    description: '适合做稳定性验证，样本质量更整齐。',
  },
  {
    value: 'blackhorse',
    label: '弹性成长池',
    accent: 'violet',
    description: '更偏高波动标的，便于观察排序模型在进攻场景下的区分度。',
  },
  {
    value: 'all',
    label: 'A股全市场',
    accent: 'cyan',
    description: '覆盖面最大，适合最终做泛化能力与样本覆盖率检查。',
  },
];

export const strategyInfo: Record<string, StrategyMeta> = {
  power_energy: {
    name: "电力与储能 (Regime Switching)",
    desc: "电力与储能板块专属策略。融合低波、反转、深度价值及回归因子。根据近期市场表现自适应进攻与防御。",
    icon: Zap, category: "行业轮动", tags: ["板块轮动", "高收益", "低回撤"], color: "blue", pool: "power_energy", assetClass: "a_share"
  },
  blackhorse: {
    name: "动量猎手 (Blackhorse)",
    desc: "进攻先锋：价格动量加速度分析 + 价量协同确认。专抓中小盘黑马裁行，光量放大至均量 2 倍以上才入场，严格过滤融断强度不足的标的。",
    icon: Zap, category: "动量类", tags: ["动量加速度", "高爆发", "进攻"], color: "rose", pool: "blackhorse", assetClass: "a_share"
  },
  ai_adaptive: {
    name: "自适应双模策略 (Adaptive)",
    desc: "波动率驱动的市场环境切换机制。低波期跟趋势，高波期抚超卖反弹。全部基于滚动波动率实时计算，无前视偏差。",
    icon: BrainCircuit, category: "自适应类", tags: ["市场切换", "波动率驱动"], color: "violet", pool: "core", assetClass: "a_share"
  },
  ai_ml: {
    name: "防御多因子模型 (Defense)",
    desc: "正交化因子加权评分：低波动率(42%) + 深度价値(22%) + 成交活跃度(8%)。权重基于因子有效性经验标定，严格过滤 PE/PB=0 标的的异常値。",
    icon: ShieldCheck, category: "多因子类", tags: ["低波动", "价値因子", "底仓"], color: "emerald", pool: "core", assetClass: "a_share"
  },
  bottom_fishing: {
    name: "ETF 技术抗底 (进攻版)",
    desc: "纯技术因子的 ETF 抵底模型。波动率(42%) + 布林带下轨偏离度(36%) + 反动量因子(22%)。ETF 无 PE/PB，因此改用纯价格模型。",
    icon: Zap, category: "ETF专属", tags: ["超卢据制", "抗底", "ETF专属"], color: "rose", pool: "etf", assetClass: "etf"
  },
  bottom_fishing_stable: {
    name: "ETF 技术抗底 (稳定版)",
    desc: "在进攻版基础上提高入场门槛 (score>1.3 且 RSI<35)。使用纯技术因子，使得该策略对 ETF 池完全适用。",
    icon: ShieldCheck, category: "ETF专属", tags: ["极低回撤", "稳健", "资产配置"], color: "emerald", pool: "etf", assetClass: "etf"
  },
  overnight: {
    name: "一夜持股 (Signal Factory)",
    desc: "来自 acodex 核心信号。锁定 14:50 分具有强力承接、主力资金净流入且价格位于 20 日高位的标的。赚取次日竞价溢价。",
    icon: Zap, category: "信号工厂 (高共识)", tags: ["短线接力", "隔夜溢价", "情绪流"], color: "violet", pool: "blackhorse", assetClass: "a_share"
  },
  weak_to_strong: {
    name: "弱转强 (Signal Factory)",
    desc: "识别开盘低开后、在 30 分钟内迅速放量收复失地并突破前高的高辨识度结构。捕捉分歧转一致的爆发性机会。",
    icon: Flame, category: "信号工厂 (高共识)", tags: ["反转爆点", "盘中博弈", "高灵敏"], color: "amber", pool: "blackhorse", assetClass: "a_share"
  },
  limit_up_doji: {
    name: "涨停后十字星",
    desc: "捕捉昨日封板、今日缩量收平的经典'空中加油'形态。判定主力洗盘意图，博取次日的二波启动脉冲。",
    icon: Factory, category: "信号工厂 (高共识)", tags: ["形态博弈", "趋势延续"], color: "cyan", pool: "blackhorse", assetClass: "a_share"
  },
  sector_alpha: {
    name: "行业优选 (Alpha)",
    desc: "多因子截面 Z-Score 标准化评分系统。综合 PB 倒数、20 日波性与价格位置。在行业内部寻找被低估的 Alpha 溢价。",
    icon: Target, category: "经典量化", tags: ["估值修复", "机构逻辑"], color: "indigo", pool: "core", assetClass: "a_share"
  },
  turtle: {
    name: "海龟法则 (高频版)",
    desc: "复刻自经典的唐奇安通道。入场：5日价格突破新高；离场：2日下穿新低。已针对 A 股目前的波动环境进行了大幅高频化改良。",
    icon: Play, category: "经典量化", tags: ["趋势跟随", "波段操作"], color: "sky", pool: "core", assetClass: "a_share"
  },
  hfmr: {
    name: "高频均值回归 (HFMR)",
    desc: "基于 RSI6 极致超卖与布林带下轨触碰。捕捉非理性杀跌后的物理性反弹。适合目前短线情绪极度撕裂的市场。",
    icon: Activity, category: "经典量化", tags: ["超卖捕捉", "高换手"], color: "fuchsia", pool: "core", assetClass: "a_share"
  },
  reversal: {
    name: "超跌反转 (Reversal)",
    desc: "寻找 5 日内跌幅超过 2% 且成交量突然放大至均值 1.5 倍以上的品种。逻辑在于捕捉抛盘耗尽后的第一波回流。",
    icon: BarChart3, category: "经典量化", tags: ["放量反弹", "底部确认"], color: "orange", pool: "core", assetClass: "a_share"
  },
  atm: {
    name: "趋势增强 (ATM Filter)",
    desc: "多维过滤器：MA60 多空分界线 + MACD 动量确认 + RSI 活跃区间。最稳健的右侧交易模型。",
    icon: TrendingUp, category: "经典量化", tags: ["右侧交易", "顺势而为"], color: "emerald", pool: "core", assetClass: "a_share"
  }
};

export function getStrategyMeta(factor: string): StrategyMeta {
  return strategyInfo[factor] || strategyInfo.bottom_fishing;
}

export function getDefaultPoolForStrategy(factor: string): StrategyPool {
  return getStrategyMeta(factor).pool;
}

export function getStrategyAssetClass(factor: string): StrategyAssetClass {
  return getStrategyMeta(factor).assetClass;
}

export function getRuntimePoolForStrategy(): RuntimePool {
  return 'auto';
}

export function coerceRuntimePoolForStrategy(factor: string, pool: string | undefined | null): RuntimePool {
  const normalizedPool = (pool ?? 'auto') as RuntimePool;
  if (isPoolCompatibleWithStrategy(factor, normalizedPool)) {
    return normalizedPool;
  }
  return 'auto';
}

export function getPoolLabel(pool: RuntimePool): string {
  return poolLabelMap[pool];
}

export function getAssetClassLabel(assetClass: StrategyAssetClass): string {
  return assetClass === 'etf' ? 'ETF' : 'A股';
}

export function getLockedPoolLabel(factor: string, pool: RuntimePool = 'auto'): string {
  if (pool !== 'auto') {
    return getPoolLabel(pool);
  }
  return getPoolLabel(getStrategyMeta(factor).pool);
}

export function getLockedPoolDescription(factor: string, pool: RuntimePool = 'auto'): string {
  const strategy = getStrategyMeta(factor);
  if (strategy.assetClass === 'etf') {
    if (pool === 'all') {
      return 'ETF 资产类别已锁定，当前会读取 ETF 全市场数据池；后端会继续拦截 A股标的。';
    }
    return 'ETF 资产类别已锁定，当前会在 ETF 精选池内运行；你也可以切到 ETF 全市场。';
  }

  if (pool === 'core') {
    return '当前策略已切到 A股核心池，后端会继续做资产类别校验，不会混入 ETF。';
  }
  if (pool === 'blackhorse') {
    return '当前策略已切到 A股弹性成长池，后端会继续做资产类别校验，不会混入 ETF。';
  }
  if (pool === 'all') {
    return '当前策略已切到 A股全市场数据池，后端会继续做资产类别校验，不会混入 ETF。';
  }
  if (strategy.pool === 'blackhorse') {
    return '当前策略默认走 A股弹性成长池；你可以切到其他 A股数据池，后端会继续做资产类别校验。';
  }
  return '当前策略默认走 A股核心池；你可以切到其他 A股数据池，后端会继续做资产类别校验。';
}

export function isPoolCompatibleWithStrategy(factor: string, pool: string): boolean {
  if (pool === 'auto') return true;
  const assetClass = getStrategyAssetClass(factor);
  const strategyMeta = getStrategyMeta(factor);
  
  if (assetClass === 'etf') {
    return pool === 'etf' || pool === 'all';
  }
  
  if (strategyMeta.pool === 'power_energy') {
    return pool === 'power_energy' || pool === 'all';
  }
  
  return pool === 'core' || pool === 'blackhorse' || pool === 'all';
}

export function getAllowedPoolOptions(factor: string): PoolOption[] {
  const assetClass = getStrategyAssetClass(factor);
  const strategyMeta = getStrategyMeta(factor);
  
  if (assetClass === 'etf') {
    return [
      { value: 'auto', label: '系统自动匹配 (ETF 推荐)' },
      { value: 'etf', label: '主流 ETF 精选池' },
      { value: 'all', label: 'ETF 全市场 (本地 etf 数据池)' },
    ];
  }

  if (strategyMeta.pool === 'power_energy') {
    return [
      { value: 'auto', label: '系统自动匹配 (电力与储能专属)' },
      { value: 'power_energy', label: '电力与储能板块 (Power 15)' },
      { value: 'all', label: 'A股全市场 (本地数据池)' },
    ];
  }

  return [
    { value: 'auto', label: '系统自动匹配 (按策略默认池)' },
    { value: 'core', label: '核心蓝筹池 (Core 15)' },
    { value: 'blackhorse', label: '弹性成长池 (Blackhorse 15)' },
    { value: 'all', label: 'A股全市场 (本地数据池)' },
  ];
}
