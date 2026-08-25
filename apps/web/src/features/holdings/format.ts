/** 整理后端十进制字符串，不使用 JavaScript 浮点运算。 */
export function formatDecimal(value: string): string {
  const [rawInteger, rawFraction = ''] = value.split('.', 2);
  const negative = rawInteger.startsWith('-');
  const integerDigits = rawInteger.replace('-', '').replace(/^0+(?=\d)/, '');
  const integer = integerDigits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const fraction = rawFraction.replace(/0+$/, '');
  return `${negative ? '-' : ''}${integer}${fraction ? `.${fraction}` : ''}`;
}

/** 为人民币金额添加符号并保留后端十进制精度。 */
export function formatCurrency(value: string | null): string {
  return value === null ? '—' : `¥${formatDecimal(value)}`;
}

/** 为收益金额添加明确正负号，避免只依赖颜色表达涨跌。 */
export function formatSignedCurrency(value: string | null): string {
  if (value === null) return '—';
  const zero = /^-?0(?:\.0+)?$/.test(value);
  return `${!value.startsWith('-') && !zero ? '+' : ''}¥${formatDecimal(value)}`;
}

/** 把后端收益率比值移动两位小数后显示为百分比。 */
export function formatRate(value: string | null): string {
  if (value === null) return '—';
  const negative = value.startsWith('-');
  const unsigned = value.replace('-', '');
  const [integer, fraction = ''] = unsigned.split('.', 2);
  const digits = `${integer}${fraction.padEnd(2, '0')}`;
  const split = integer.length + 2;
  const percentInteger = digits.slice(0, split).replace(/^0+(?=\d)/, '') || '0';
  const percentFraction = digits.slice(split).replace(/0+$/, '');
  const zero = /^0(?:\.0+)?$/.test(unsigned);
  const formatted = `${negative ? '-' : zero ? '' : '+'}${percentInteger}${percentFraction ? `.${percentFraction}` : ''}`;
  return `${formatted}%`;
}

/** 根据十进制字符串符号返回收益、亏损或中性样式。 */
export function valueTone(value: string | null): string {
  if (value === null || /^-?0(?:\.0+)?$/.test(value)) return '';
  return value.startsWith('-') ? 'value-tone value-tone--loss' : 'value-tone value-tone--gain';
}
