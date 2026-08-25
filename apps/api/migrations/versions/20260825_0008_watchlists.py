"""创建用户隔离的自选分组和观察标的表。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260825_0008"
down_revision: str | None = "20260825_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建立默认分组、组内唯一、排序和乐观锁约束。"""
    op.create_table(
        "watchlist_groups",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column(
            "is_default",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "name = btrim(name) AND char_length(name) BETWEEN 1 AND 80",
            name="ck_watchlist_groups_name",
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_watchlist_groups_sort_order"),
        sa.CheckConstraint("version >= 1", name="ck_watchlist_groups_version"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_watchlist_groups_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_watchlist_groups"),
        sa.UniqueConstraint("user_id", "name", name="uq_watchlist_groups_user_name"),
    )
    op.create_index(
        "uq_watchlist_groups_one_default",
        "watchlist_groups",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )
    op.create_index(
        "ix_watchlist_groups_user_sort",
        "watchlist_groups",
        ["user_id", "sort_order", "created_at", "id"],
        unique=False,
    )
    op.execute(
        "INSERT INTO watchlist_groups (user_id, name, is_default, sort_order) "
        "SELECT id, '默认分组', true, 0 FROM users"
    )

    op.create_table(
        "watchlist_items",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.Column("instrument_id", sa.Uuid(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "note IS NULL OR (note = btrim(note) AND char_length(note) BETWEEN 1 AND 500)",
            name="ck_watchlist_items_note",
        ),
        sa.CheckConstraint("sort_order >= 0", name="ck_watchlist_items_sort_order"),
        sa.CheckConstraint("version >= 1", name="ck_watchlist_items_version"),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["watchlist_groups.id"],
            name="fk_watchlist_items_group_id_watchlist_groups",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name="fk_watchlist_items_instrument_id_instruments",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_watchlist_items"),
        sa.UniqueConstraint(
            "group_id",
            "instrument_id",
            name="uq_watchlist_items_group_instrument",
        ),
    )
    op.create_index(
        "ix_watchlist_items_group_sort",
        "watchlist_items",
        ["group_id", "sort_order", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_watchlist_items_instrument",
        "watchlist_items",
        ["instrument_id"],
        unique=False,
    )


def downgrade() -> None:
    """移除观察标的和自选分组表。"""
    op.drop_index("ix_watchlist_items_instrument", table_name="watchlist_items")
    op.drop_index("ix_watchlist_items_group_sort", table_name="watchlist_items")
    op.drop_table("watchlist_items")
    op.drop_index("ix_watchlist_groups_user_sort", table_name="watchlist_groups")
    op.drop_index("uq_watchlist_groups_one_default", table_name="watchlist_groups")
    op.drop_table("watchlist_groups")
