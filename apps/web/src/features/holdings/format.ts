export interface DecimalParts {
  negative: boolean;
  integer: string;
  fraction: string;
}

/** 解析后端 Decimal 字符串，同时兼容数据库零值等科学计数法表示。 */
export function parseDecimalParts(value: string): DecimalParts | null {
  const matched = /^([+-]?)(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/.exec(value);
  if (matched === null) return null;

  const [, sign, integer, fraction = '', rawExponent = '0'] = matched;
  const exponent = Number(rawExponent);
  if (!Number.isSafeInteger(exponent) || Math.abs(exponent) > 10_000) return null;

  const digits = `${integer}${fraction}`;
  if (/^0+$/.test(digits)) {
    return { negative: false, integer: '0', fraction: '' };
  }

  const decimalIndex = integer.length + exponent;
  const expandedInteger = decimalIndex <= 0
    ? '0'
    : decimalIndex >= digits.length
      ? `${digits}${'0'.repeat(decimalIndex - digits.length)}`
      : digits.slice(0, decimalIndex);
  const expandedFraction = decimalIndex <= 0
    ? `${'0'.repeat(-decimalIndex)}${digits}`
    : decimalIndex >= digits.length
      ? ''
      : digits.slice(decimalIndex);

  return {
    negative: sign === '-',
    integer: expandedInteger.replace(/^0+(?=\d)/, ''),
    fraction: expandedFraction,
  };
}

/** 将十进制组成部分还原为不含科学计数法的字符串。 */
function decimalPartsToString(parts: DecimalParts): string {
  return `${parts.negative ? '-' : ''}${parts.integer}${parts.fraction ? `.${parts.fraction}` : ''}`;
}

/** 判断已解析的十进制值是否为零。 */
function isZeroDecimal(parts: DecimalParts): boolean {
  return /^0+$/.test(parts.integer) && (parts.fraction === '' || /^0+$/.test(parts.fraction));
}

/** 按指定精度四舍五入后端十进制字符串，不使用 JavaScript 浮点运算。 */
export function formatDecimal(
  value: string,
  maximumFractionDigits = 4,
  minimumFractionDigits = 0,
): string {
  const parts = parseDecimalParts(value);
  if (parts === null) return '—';

  const { negative, integer: integerDigits, fraction: rawFraction } = parts;
  const base = 10n ** BigInt(maximumFractionDigits);
  const keptFraction = rawFraction.slice(0, maximumFractionDigits)
    .padEnd(maximumFractionDigits, '0');
  let scaled = BigInt(integerDigits || '0') * base + BigInt(keptFraction || '0');
  if ((rawFraction[maximumFractionDigits] ?? '0') >= '5') scaled += 1n;
  const roundedInteger = (scaled / base).toString();
  let fraction = maximumFractionDigits === 0
    ? ''
    : (scaled % base).toString().padStart(maximumFractionDigits, '0');
  while (fraction.length > minimumFractionDigits && fraction.endsWith('0')) {
    fraction = fraction.slice(0, -1);
  }
  const integer = roundedInteger.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const sign = negative && scaled !== 0n ? '-' : '';
  return `${sign}${integer}${fraction ? `.${fraction}` : ''}`;
}

/** 为人民币金额添加符号并统一保留两位小数。 */
export function formatCurrency(value: string | null): string {
  if (value === null) return '—';
  const amount = formatDecimal(value, 2, 2);
  return amount === '—' ? amount : `¥${amount}`;
}

/** 将表格金额统一保留两位小数，不重复展示页面已经明确的人民币单位。 */
export function formatAmount(value: string | null): string {
  return value === null ? '—' : formatDecimal(value, 2, 2);
}

/** 为收益金额添加明确正负号，避免只依赖颜色表达涨跌。 */
export function formatSignedCurrency(value: string | null): string {
  if (value === null) return '—';
  const parts = parseDecimalParts(value);
  if (parts === null) return '—';
  const amount = formatDecimal(decimalPartsToString({ ...parts, negative: false }), 2, 2);
  const zero = amount === '0.00';
  return `${parts.negative && !zero ? '-' : zero ? '' : '+'}¥${amount}`;
}

/** 为表格收益金额添加正负号，但不重复展示人民币符号。 */
export function formatSignedAmount(value: string | null): string {
  if (value === null) return '—';
  const parts = parseDecimalParts(value);
  if (parts === null) return '—';
  const amount = formatDecimal(decimalPartsToString({ ...parts, negative: false }), 2, 2);
  const zero = amount === '0.00';
  return `${parts.negative && !zero ? '-' : zero ? '' : '+'}${amount}`;
}

/** 把后端收益率比值转成百分比并统一保留两位小数。 */
export function formatRate(value: string | null): string {
  if (value === null) return '—';
  const parts = parseDecimalParts(value);
  if (parts === null) return '—';
  const negative = parts.negative;
  const unsigned = decimalPartsToString({ ...parts, negative: false });
  const [integer, fraction = ''] = unsigned.split('.', 2);
  const digits = `${integer}${fraction}`.padEnd(integer.length + 2, '0');
  const decimalIndex = integer.length + 2;
  const percentInteger = digits.slice(0, decimalIndex).replace(/^0+(?=\d)/, '') || '0';
  const percentFraction = digits.slice(decimalIndex);
  const formatted = formatDecimal(`${percentInteger}.${percentFraction}`, 2, 2);
  const zero = formatted === '0.00';
  return `${negative && !zero ? '-' : zero ? '' : '+'}${formatted}%`;
}

/** 根据十进制字符串符号返回收益、亏损或中性样式。 */
export function valueTone(value: string | null): string {
  if (value === null) return '';
  const parts = parseDecimalParts(value);
  if (parts === null || isZeroDecimal(parts)) return '';
  return parts.negative ? 'value-tone value-tone--loss' : 'value-tone value-tone--gain';
}
