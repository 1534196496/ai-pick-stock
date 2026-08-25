"""持仓十进制精度、范围和舍入规则。"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

SCALE = Decimal("0.00000001")
MAX_AMOUNT = Decimal("9999999999999999.99999999")
MAX_QUANTITY = Decimal("99999999999999999999.99999999")


class DecimalRuleError(ValueError):
    """表示财务值不满足有限、正数、精度或范围规则。"""


def require_positive_input(value: Decimal, *, maximum: Decimal, field: str) -> Decimal:
    """校验用户输入为正有限值且最多八位小数，不做静默截断。"""
    if not value.is_finite() or value <= 0:
        raise DecimalRuleError(f"{field}必须是大于零的有限十进制数")
    try:
        normalized = value.quantize(SCALE, rounding=ROUND_HALF_UP)
    except InvalidOperation as error:
        raise DecimalRuleError(f"{field}超出可保存范围") from error
    if normalized != value:
        raise DecimalRuleError(f"{field}最多支持 8 位小数")
    if normalized > maximum:
        raise DecimalRuleError(f"{field}超出可保存范围")
    return normalized


def require_signed_input(value: Decimal, *, maximum: Decimal, field: str) -> Decimal:
    """校验允许正负和零的有限用户输入，并拒绝超过八位小数。"""
    if not value.is_finite():
        raise DecimalRuleError(f"{field}必须是有限十进制数")
    try:
        normalized = value.quantize(SCALE, rounding=ROUND_HALF_UP)
    except InvalidOperation as error:
        raise DecimalRuleError(f"{field}超出可保存范围") from error
    if normalized != value:
        raise DecimalRuleError(f"{field}最多支持 8 位小数")
    if abs(normalized) > maximum:
        raise DecimalRuleError(f"{field}超出可保存范围")
    return normalized


def calculate_decimal(value: Decimal, *, maximum: Decimal, field: str) -> Decimal:
    """把服务端计算结果按八位小数四舍五入并校验正数范围。"""
    if not value.is_finite():
        raise DecimalRuleError(f"{field}计算结果无效")
    try:
        normalized = value.quantize(SCALE, rounding=ROUND_HALF_UP)
    except InvalidOperation as error:
        raise DecimalRuleError(f"{field}计算结果超出范围") from error
    if normalized <= 0:
        raise DecimalRuleError(f"{field}计算结果必须大于零")
    if normalized > maximum:
        raise DecimalRuleError(f"{field}计算结果超出范围")
    return normalized


def round_decimal(value: Decimal, *, field: str) -> Decimal:
    """把允许为零或负数的有限计算结果按八位小数四舍五入。"""
    if not value.is_finite():
        raise DecimalRuleError(f"{field}计算结果无效")
    try:
        return value.quantize(SCALE, rounding=ROUND_HALF_UP)
    except InvalidOperation as error:
        raise DecimalRuleError(f"{field}计算结果超出范围") from error
