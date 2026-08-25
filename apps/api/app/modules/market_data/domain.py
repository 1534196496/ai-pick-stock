"""行情模块对服务层公开的不可变读取记录。"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from app.modules.market_data.enums import PriceType, SyncJobType, SyncStatus


class DataFreshness(StrEnum):
    """表示本地数据是否仍在约定的新鲜时间窗口内。"""

    FRESH = "FRESH"
    STALE = "STALE"


@dataclass(frozen=True, slots=True)
class PriceRecord:
    """表示一个资产某种价格口径下的最新有效快照。"""

    instrument_id: UUID
    price_type: PriceType
    value: Decimal
    as_of_date: date | None
    as_of_at: datetime | None
    fetched_at: datetime
    source: str


@dataclass(frozen=True, slots=True)
class SyncRunRecord:
    """表示一种同步任务最近一次运行的公开状态。"""

    job_type: SyncJobType
    status: SyncStatus
    source: str
    started_at: datetime
    finished_at: datetime | None
    succeeded_count: int
    failed_count: int
