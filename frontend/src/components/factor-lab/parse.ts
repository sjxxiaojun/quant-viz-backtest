/**
 * Factor Lab 响应解析工具（表驱动）。
 * 目标：后端字段的运行时收敛只声明一次字段表，避免逐字段手写防御代码。
 */
import { isRecord } from '../../api/guards';

export { isRecord };

export function toNum(value: unknown, fallback = 0): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

export function toStr(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim() ? value : fallback;
}

export function toStrArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)) : [];
}

/** 取第一个非 undefined 的别名字段 (兼容后端字段改名历史) */
export function firstOf(source: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    if (source[key] !== undefined) return source[key];
  }
  return undefined;
}

/** 数组逐项解析并丢弃无效项 */
export function mapItems<T>(source: unknown, parse: (item: unknown, index: number) => T | null): T[] {
  if (!Array.isArray(source)) return [];
  const items: T[] = [];
  source.forEach((entry, index) => {
    const parsed = parse(entry, index);
    if (parsed !== null) items.push(parsed);
  });
  return items;
}

/**
 * 字段规则:
 * - str / num / bool: 必填语义, 缺省回退 '' / 0 / false
 * - str? / num? / bool?: 字段缺失时保持 undefined (前端以 undefined 区分“后端未返回”)
 * - str|null / num|null: null 与缺失统一收敛为 null
 * - str[]: 字符串数组, 非数组回退 []
 */
export type FieldRule =
  | 'str'
  | 'str?'
  | 'str|null'
  | 'num'
  | 'num?'
  | 'num|null'
  | 'bool'
  | 'bool?'
  | 'str[]';

function coerce(value: unknown, rule: FieldRule): unknown {
  switch (rule) {
    case 'str':
      return toStr(value);
    case 'str?':
      return value === undefined ? undefined : toStr(value);
    case 'str|null':
      return value == null ? null : toStr(value);
    case 'num':
      return toNum(value);
    case 'num?':
      return value === undefined ? undefined : toNum(value);
    case 'num|null':
      return value == null ? null : toNum(value);
    case 'bool':
      return Boolean(value);
    case 'bool?':
      return value === undefined ? undefined : Boolean(value);
    case 'str[]':
      return toStrArray(value);
  }
}

/**
 * 按字段表把未知对象收敛为目标结构。
 * 字段表与目标类型一一对应, 运行时逐字段做类型收敛, 因此最终断言是安全的。
 */
export function parseFields<T>(source: unknown, spec: Record<string, FieldRule>): T {
  const record = isRecord(source) ? source : {};
  const out: Record<string, unknown> = {};
  Object.entries(spec).forEach(([key, rule]) => {
    out[key] = coerce(record[key], rule);
  });
  return out as T;
}

/** parseFields 的可空版本: 源不是对象时返回 null */
export function parseFieldsOrNull<T>(source: unknown, spec: Record<string, FieldRule>): T | null {
  if (!isRecord(source)) return null;
  return parseFields<T>(source, spec);
}

/** 数值字典: {factor: 0.12, ...} */
export function toNumberRecord(source: unknown): Record<string, number> | undefined {
  if (!isRecord(source)) return undefined;
  return Object.entries(source).reduce<Record<string, number>>((acc, [key, value]) => {
    acc[key] = toNum(value);
    return acc;
  }, {});
}
