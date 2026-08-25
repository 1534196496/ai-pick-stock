"""投资账户模块公开的不可变领域记录。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class InvestmentAccountRecord:
    """表示属于当前用户的单个投资账户。"""

    id: UUID
    user_id: UUID
    name: str
    base_currency: str
    sort_order: int
    version: int
    created_at: datetime
    updated_at: datetime
