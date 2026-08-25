"""自选分组与观察标的 API 契约。"""

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from app.api.schemas import ApiModel
from app.modules.instruments.schemas import InstrumentResponse


class WatchlistGroupResponse(ApiModel):
    """返回用户可见的自选分组及标的数量。"""

    id: UUID
    name: str
    is_default: bool
    sort_order: int
    item_count: int
    version: int
    created_at: datetime
    updated_at: datetime


class WatchlistGroupListResponse(ApiModel):
    """返回当前用户全部自选分组。"""

    items: list[WatchlistGroupResponse]


class CreateWatchlistGroupRequest(ApiModel):
    """接收待规范化的新自选分组名称。"""

    name: str


class UpdateWatchlistGroupRequest(ApiModel):
    """使用版本号选择性修改分组名称或排序。"""

    version: int = Field(ge=1)
    name: str | None = None
    sort_order: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_change(self) -> "UpdateWatchlistGroupRequest":
        """拒绝空 PATCH 或显式清空分组字段。"""
        editable = {"name", "sort_order"}
        changed = self.model_fields_set & editable
        if not changed:
            raise ValueError("至少提供一个待修改字段")
        if any(getattr(self, field) is None for field in changed):
            raise ValueError("分组字段不能显式清空")
        return self


class WatchlistItemResponse(ApiModel):
    """返回观察标的、所属分组、备注、行情和乐观锁版本。"""

    id: UUID
    group_id: UUID
    instrument: InstrumentResponse
    note: str | None
    sort_order: int
    version: int
    created_at: datetime
    updated_at: datetime


class WatchlistItemListResponse(ApiModel):
    """返回指定分组的稳定分页观察标的列表。"""

    items: list[WatchlistItemResponse]
    page: int
    page_size: int
    total: int


class CreateWatchlistItemRequest(ApiModel):
    """接收待加入分组的标的和可选备注。"""

    instrument_id: UUID
    note: str | None = None


class UpdateWatchlistItemRequest(ApiModel):
    """使用版本号选择性移动、修改备注或调整排序。"""

    version: int = Field(ge=1)
    group_id: UUID | None = None
    note: str | None = None
    sort_order: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_change(self) -> "UpdateWatchlistItemRequest":
        """拒绝没有实际字段的 PATCH，同时允许显式 null 清空备注。"""
        editable = {"group_id", "note", "sort_order"}
        changed = self.model_fields_set & editable
        if not changed:
            raise ValueError("至少提供一个待修改字段")
        if "group_id" in changed and self.group_id is None:
            raise ValueError("目标分组不能显式清空")
        if "sort_order" in changed and self.sort_order is None:
            raise ValueError("排序不能显式清空")
        return self
