import type { Position } from './api';
import { parseDecimalParts, type DecimalParts } from './format';

export const positionSortOptions = [
  { key: 'MARKET_VALUE', label: '持仓金额' },
  { key: 'TODAY_PROFIT', label: '今日收益金额' },
  { key: 'TODAY_RETURN_RATE', label: '今日收益率' },
  { key: 'HOLDING_PROFIT', label: '持仓收益金额' },
  { key: 'HOLDING_RETURN_RATE', label: '持仓收益率' },
] as const;

export type PositionSortKey = (typeof positionSortOptions)[number]['key'];
export type PositionSortDirection = 'asc' | 'desc';

export interface PositionSort {
  key: PositionSortKey;
  direction: PositionSortDirection;
}

export const defaultPositionSort: PositionSort = {
  key: 'MARKET_VALUE',
  direction: 'desc',
};

/** 按页面展示口径排序持仓，并将缺失值稳定放在末尾。 */
export function sortPositions(items: Position[], sort: PositionSort): Position[] {
  return items
    .map((position, index) => ({ position, index, value: positionSortValue(position, sort.key) }))
    .sort((left, right) => {
      if (left.value === null && right.value === null) return left.index - right.index;
      if (left.value === null) return 1;
      if (right.value === null) return -1;
      const comparison = compareFinancialDecimal(left.value, right.value);
      if (comparison === 0) return left.index - right.index;
      return sort.direction === 'asc' ? comparison : -comparison;
    })
    .map(({ position }) => position);
}

/** 从浏览器读取指定资产类型的排序偏好，无有效配置时使用持仓金额降序。 */
export function readPositionSort(assetType: 'STOCK' | 'FUND'): PositionSort {
  if (typeof window === 'undefined') return defaultPositionSort;
  try {
    const rawValue = window.localStorage.getItem(storageKey(assetType));
    if (rawValue === null) return defaultPositionSort;
    const value = JSON.parse(rawValue) as Partial<PositionSort>;
    if (!isPositionSortKey(value.key) || !isPositionSortDirection(value.direction)) {
      return defaultPositionSort;
    }
    return { key: value.key, direction: value.direction };
  } catch {
    return defaultPositionSort;
  }
}

/** 在浏览器保存指定资产类型的排序偏好，不影响服务端数据。 */
export function savePositionSort(
  assetType: 'STOCK' | 'FUND',
  sort: PositionSort,
): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(storageKey(assetType), JSON.stringify(sort));
  } catch {
    // 浏览器禁用本地存储时仍保留当前会话内的排序状态。
  }
}

/** 读取与持仓列表当前展示完全一致的排序值。 */
function positionSortValue(position: Position, key: PositionSortKey): string | null {
  const official = position.valuation;
  const estimate = position.estimatedValuation;
  const todayValuation = official?.todayProfit != null
    ? official
    : estimate?.todayProfit != null
      ? estimate
      : null;
  const activeValuation = todayValuation ?? estimate ?? official;

  switch (key) {
    case 'MARKET_VALUE':
      return official?.marketValue ?? null;
    case 'TODAY_PROFIT':
      return todayValuation?.todayProfit ?? null;
    case 'TODAY_RETURN_RATE':
      return todayValuation?.price.changeRate ?? null;
    case 'HOLDING_PROFIT':
      return activeValuation?.holdingProfit ?? null;
    case 'HOLDING_RETURN_RATE':
      return activeValuation?.returnRate ?? null;
  }
}

/** 精确比较两个十进制财务字符串，避免浮点转换影响临界排序。 */
function compareFinancialDecimal(left: string, right: string): number {
  const leftParts = parseDecimalParts(left);
  const rightParts = parseDecimalParts(right);
  if (leftParts === null || rightParts === null) return 0;
  const scale = Math.max(leftParts.fraction.length, rightParts.fraction.length);
  const leftScaled = scaledDecimal(leftParts, scale);
  const rightScaled = scaledDecimal(rightParts, scale);
  return leftScaled < rightScaled ? -1 : leftScaled > rightScaled ? 1 : 0;
}

/** 按统一小数位数生成用于精确比较的整数。 */
function scaledDecimal(
  value: DecimalParts,
  scale: number,
): bigint {
  const digits = `${value.integer}${value.fraction.padEnd(scale, '0')}`.replace(/^0+(?=\d)/, '');
  const amount = BigInt(digits || '0');
  return value.negative ? -amount : amount;
}

/** 判断本地配置是否为当前支持的排序字段。 */
function isPositionSortKey(value: unknown): value is PositionSortKey {
  return positionSortOptions.some((option) => option.key === value);
}

/** 判断本地配置是否为有效排序方向。 */
function isPositionSortDirection(value: unknown): value is PositionSortDirection {
  return value === 'asc' || value === 'desc';
}

/** 为股票和基金生成互不干扰的本地排序配置键。 */
function storageKey(assetType: 'STOCK' | 'FUND'): string {
  return `holdings-sort-v1-${assetType.toLowerCase()}`;
}
