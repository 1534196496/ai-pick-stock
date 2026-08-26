"""自选分组与观察标的持久化模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
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


class WatchlistGroup(Base):
    """保存同时承载持仓和自选标的的用户组合分组。"""

    __tablename__ = "portfolio_groups"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_portfolio_groups_user_name"),
        CheckConstraint(
            "name = btrim(name) AND char_length(name) BETWEEN 1 AND 80",
            name="ck_portfolio_groups_name",
        ),
        CheckConstraint("sort_order >= 0", name="ck_portfolio_groups_sort_order"),
        CheckConstraint("version >= 1", name="ck_portfolio_groups_version"),
        Index(
            "uq_portfolio_groups_one_default",
            "user_id",
            unique=True,
            postgresql_where=text("is_default"),
        ),
        Index("ix_portfolio_groups_user_sort", "user_id", "sort_order", "created_at", "id"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WatchlistItem(Base):
    """保存分组中的唯一观察标的、备注、排序和乐观锁版本。"""

    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint(
            "group_id",
            "instrument_id",
            name="uq_watchlist_items_group_instrument",
        ),
        CheckConstraint(
            "note IS NULL OR (note = btrim(note) AND char_length(note) BETWEEN 1 AND 500)",
            name="ck_watchlist_items_note",
        ),
        CheckConstraint("sort_order >= 0", name="ck_watchlist_items_sort_order"),
        CheckConstraint("version >= 1", name="ck_watchlist_items_version"),
        Index("ix_watchlist_items_group_sort", "group_id", "sort_order", "created_at", "id"),
        Index("ix_watchlist_items_instrument", "instrument_id"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    group_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("portfolio_groups.id", ondelete="RESTRICT"),
        nullable=False,
    )
    instrument_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("instruments.id", ondelete="RESTRICT"),
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
