interface ParsedDecimal {
  coefficient: bigint;
  scale: number;
}

/** 把正十进制输入解析为整数系数和小数位数。 */
function parsePositive(value: string): ParsedDecimal | null {
  if (!/^\d+(?:\.\d{0,8})?$/.test(value) || /^0+(?:\.0*)?$/.test(value)) return null;
  const [integer, fraction = ''] = value.split('.', 2);
  return {
    coefficient: BigInt(`${integer}${fraction}`),
    scale: fraction.length,
  };
}

/** 把可正可负且允许为零的十进制输入解析为整数系数和小数位数。 */
function parseSigned(value: string): ParsedDecimal | null {
  if (!/^-?\d+(?:\.\d{0,8})?$/.test(value)) return null;
  const negative = value.startsWith('-');
  const unsigned = value.replace('-', '');
  const [integer, fraction = ''] = unsigned.split('.', 2);
  const coefficient = BigInt(`${integer}${fraction}`);
  return {
    coefficient: negative ? -coefficient : coefficient,
    scale: fraction.length,
  };
}

/** 按八位小数四舍五入整数系数。 */
function roundScale(coefficient: bigint, sourceScale: number, targetScale = 8): bigint {
  if (sourceScale <= targetScale) return coefficient * 10n ** BigInt(targetScale - sourceScale);
  const divisor = 10n ** BigInt(sourceScale - targetScale);
  const quotient = coefficient / divisor;
  const remainder = coefficient % divisor;
  return quotient + (remainder * 2n >= divisor ? 1n : 0n);
}

/** 把固定八位系数还原成便于预览的十进制字符串。 */
function formatScaled(coefficient: bigint, scale = 8): string {
  const negative = coefficient < 0n;
  const digits = (negative ? -coefficient : coefficient).toString().padStart(scale + 1, '0');
  const integer = digits.slice(0, -scale);
  const fraction = digits.slice(-scale).replace(/0+$/, '');
  return `${negative ? '-' : ''}${integer}${fraction ? `.${fraction}` : ''}`;
}

/** 使用 BigInt 计算两个正十进制字符串的乘积。 */
export function multiplyDecimal(first: string, second: string): string | null {
  const left = parsePositive(first);
  const right = parsePositive(second);
  if (left === null || right === null) return null;
  const coefficient = roundScale(
    left.coefficient * right.coefficient,
    left.scale + right.scale,
  );
  return formatScaled(coefficient);
}

/** 使用 BigInt 计算两个正十进制字符串的商。 */
export function divideDecimal(dividend: string, divisor: string): string | null {
  const left = parsePositive(dividend);
  const right = parsePositive(divisor);
  if (left === null || right === null || right.coefficient === 0n) return null;
  const numerator = left.coefficient * 10n ** BigInt(right.scale + 8);
  const denominator = right.coefficient * 10n ** BigInt(left.scale);
  const quotient = numerator / denominator;
  const remainder = numerator % denominator;
  return formatScaled(quotient + (remainder * 2n >= denominator ? 1n : 0n));
}

/** 使用 BigInt 计算正金额减去可正可负收益后的总成本。 */
export function subtractDecimal(minuend: string, subtrahend: string): string | null {
  const left = parsePositive(minuend);
  const right = parseSigned(subtrahend);
  if (left === null || right === null) return null;
  const scale = Math.max(left.scale, right.scale);
  const leftCoefficient = left.coefficient * 10n ** BigInt(scale - left.scale);
  const rightCoefficient = right.coefficient * 10n ** BigInt(scale - right.scale);
  return formatScaled(roundScale(leftCoefficient - rightCoefficient, scale));
}
