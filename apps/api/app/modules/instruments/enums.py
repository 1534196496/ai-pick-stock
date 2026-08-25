"""资产身份与市场边界的稳定枚举。"""

from enum import StrEnum


class AssetType(StrEnum):
    """区分一期支持的股票与基金。"""

    STOCK = "STOCK"
    FUND = "FUND"


class Market(StrEnum):
    """表示资产所属市场，允许后续只新增枚举值。"""

    CN = "CN"


class Exchange(StrEnum):
    """区分 A 股交易所与中国公募基金登记域。"""

    SSE = "SSE"
    SZSE = "SZSE"
    BSE = "BSE"
    FUND_CN = "FUND_CN"


class Currency(StrEnum):
    """表示权威财务值的币种。"""

    CNY = "CNY"
