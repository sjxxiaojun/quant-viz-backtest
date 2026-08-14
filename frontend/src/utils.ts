import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/* ============================================================
   数字/金额统一 formatter — 全站唯一口径
   ============================================================ */

const WAN = 10_000;
const YI = 100_000_000;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** 千分位数字, 如 1,234,567.89 */
export function formatNumber(value: number | null | undefined, digits = 2): string {
  if (!isFiniteNumber(value)) return '--';
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

/**
 * 中文金额格式化 (万/亿), 保留符号。
 * 1.23亿 / 4,567.89万 / 9,876 (小于1万时按千分位)
 */
export function formatAmountCN(value: number | null | undefined, digits = 2): string {
  if (!isFiniteNumber(value)) return '--';
  const sign = value < 0 ? '-' : '';
  const abs = Math.abs(value);
  if (abs >= YI) return `${sign}${formatNumber(abs / YI, digits)}亿`;
  if (abs >= WAN) return `${sign}${formatNumber(abs / WAN, digits)}万`;
  return `${sign}${formatNumber(abs, abs >= 100 ? 0 : digits)}`;
}

/**
 * 百分比格式化。默认输入为比率 (0.1234 -> 12.34%)。
 * 输入已经是百分数时传 { from: 'percent' }。
 */
export function formatPercent(
  value: number | null | undefined,
  options: { digits?: number; signed?: boolean; from?: 'ratio' | 'percent' } = {},
): string {
  if (!isFiniteNumber(value)) return '--';
  const { digits = 2, signed = false, from = 'ratio' } = options;
  const pct = from === 'ratio' ? value * 100 : value;
  const sign = signed && pct > 0 ? '+' : '';
  return `${sign}${pct.toFixed(digits)}%`;
}

/** 带符号百分比 (比率输入): +12.34% / -5.60% */
export function formatSignedPercent(ratio: number | null | undefined, digits = 2): string {
  return formatPercent(ratio, { digits, signed: true });
}

/** 带符号数值: +1.23 / -0.45 */
export function formatSignedNumber(value: number | null | undefined, digits = 2): string {
  if (!isFiniteNumber(value)) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(digits)}`;
}

/* ============================================================
   A股涨跌语义 — 红涨绿跌唯一真理
   ============================================================ */

/** 涨跌文本颜色类: 正数红(up)、负数绿(down)、零/无效中性灰 */
export function changeToneClass(value: number | null | undefined): string {
  if (!isFiniteNumber(value) || value === 0) return 'text-slate-400';
  return value > 0 ? 'text-up' : 'text-down';
}

/** 涨跌颜色 (hex), 供 ECharts 等非 class 场景使用 */
export function changeColorHex(value: number | null | undefined): string {
  if (!isFiniteNumber(value) || value === 0) return '#94a3b8';
  return value > 0 ? '#f5483d' : '#16a34a';
}
