"""价格口径与同步任务状态枚举。"""

from enum import StrEnum


class PriceType(StrEnum):
    """严格区分股票价格、官方单位净值和盘中估算净值。"""

    STOCK_LAST = "STOCK_LAST"
    FUND_OFFICIAL_NAV = "FUND_OFFICIAL_NAV"
    FUND_ESTIMATED_NAV = "FUND_ESTIMATED_NAV"


class SyncJobType(StrEnum):
    """标识 Worker 执行的独立同步任务。"""

    INSTRUMENT_MASTER = "INSTRUMENT_MASTER"
    STOCK_PRICES = "STOCK_PRICES"
    FUND_OFFICIAL_NAV = "FUND_OFFICIAL_NAV"
    FUND_ESTIMATED_NAV = "FUND_ESTIMATED_NAV"


class SyncStatus(StrEnum):
    """表示同步任务完整生命周期。"""

    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
