"""自选模块公开的不可变领域记录。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class WatchlistGroupRecord:
    """表示属于单个用户的自选分组。"""

    id: UUID
    user_id: UUID
    name: str
    is_default: bool
    sort_order: int
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class WatchlistItemRecord:
    """表示分组中的单个观察标的及用户备注。"""

    id: UUID
    group_id: UUID
    instrument_id: UUID
    note: str | None
    sort_order: int
    version: int
    created_at: datetime
    updated_at: datetime
