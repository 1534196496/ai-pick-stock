"""持仓录入方式与成本输入方式枚举。"""

from enum import StrEnum


class PositionInputMode(StrEnum):
    """区分股票份额、基金金额和基金份额三种录入语义。"""

    STOCK_SHARES = "STOCK_SHARES"
    FUND_AMOUNT = "FUND_AMOUNT"
    FUND_SHARES = "FUND_SHARES"


class CostInputMode(StrEnum):
    """表示用户直接输入总成本或平均成本。"""

    TOTAL_COST = "TOTAL_COST"
    AVERAGE_COST = "AVERAGE_COST"
