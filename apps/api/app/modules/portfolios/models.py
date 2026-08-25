"""投资账户持久化模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Uuid as SqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InvestmentAccount(Base):
    """保存用户自定义的投资账户、排序与乐观锁版本。"""

    __tablename__ = "investment_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_investment_accounts_user_name"),
        CheckConstraint(
            "name = btrim(name) AND char_length(name) BETWEEN 1 AND 80",
            name="ck_investment_accounts_name",
        ),
        CheckConstraint("base_currency = 'CNY'", name="ck_investment_accounts_currency"),
        CheckConstraint("sort_order >= 0", name="ck_investment_accounts_sort_order"),
        CheckConstraint("version >= 1", name="ck_investment_accounts_version"),
        Index("ix_investment_accounts_user_sort", "user_id", "sort_order", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        SqlUuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    base_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="CNY", server_default="CNY"
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
