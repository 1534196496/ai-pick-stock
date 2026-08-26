"""持仓请求、当前状态与交易事实枚举。"""

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


class PositionStatus(StrEnum):
    """表示持仓当前投影是否持有、清仓或等待历史数据补齐。"""

    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PENDING = "PENDING"


class TransactionType(StrEnum):
    """表示会改变持仓或现金结果的交易类型。"""

    OPENING = "OPENING"
    BUY = "BUY"
    SELL = "SELL"
    DIVIDEND = "DIVIDEND"
    FEE = "FEE"
    ADJUSTMENT = "ADJUSTMENT"
    TRANSFER_IN = "TRANSFER_IN"
    TRANSFER_OUT = "TRANSFER_OUT"


class TransactionStatus(StrEnum):
    """表示交易是否已进入持仓投影。"""

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
