"""投资账户 API 请求与响应契约。"""

from datetime import datetime
from uuid import UUID

from pydantic import Field, model_validator

from app.api.schemas import ApiModel


class InvestmentAccountResponse(ApiModel):
    """返回当前用户可见的投资账户。"""

    id: UUID
    name: str
    base_currency: str
    sort_order: int
    version: int
    created_at: datetime
    updated_at: datetime


class InvestmentAccountListResponse(ApiModel):
    """返回稳定分页账户列表。"""

    items: list[InvestmentAccountResponse]
    page: int
    page_size: int
    total: int


class CreateInvestmentAccountRequest(ApiModel):
    """接收待规范化的新账户名称。"""

    name: str


class UpdateInvestmentAccountRequest(ApiModel):
    """使用版本号选择性修改名称或排序。"""

    version: int = Field(ge=1)
    name: str | None = None
    sort_order: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def require_change(self) -> "UpdateInvestmentAccountRequest":
        """拒绝只携带版本而没有实际变更的 PATCH。"""
        if self.name is None and self.sort_order is None:
            raise ValueError("至少提供一个待修改字段")
        return self
