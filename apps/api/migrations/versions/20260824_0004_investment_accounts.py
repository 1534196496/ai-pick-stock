"""创建用户隔离的投资账户表。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0004"
down_revision: str | None = "20260824_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建立账户唯一、排序与乐观锁约束，并为已有用户补默认账户。"""
    op.create_table(
        "investment_accounts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("base_currency", sa.String(length=3), server_default="CNY", nullable=False),
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
            name="ck_investment_accounts_name",
        ),
        sa.CheckConstraint("base_currency = 'CNY'", name="ck_investment_accounts_currency"),
        sa.CheckConstraint("sort_order >= 0", name="ck_investment_accounts_sort_order"),
        sa.CheckConstraint("version >= 1", name="ck_investment_accounts_version"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_investment_accounts_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_investment_accounts"),
        sa.UniqueConstraint("user_id", "name", name="uq_investment_accounts_user_name"),
    )
    op.create_index(
        "ix_investment_accounts_user_sort",
        "investment_accounts",
        ["user_id", "sort_order", "created_at"],
        unique=False,
    )
    op.execute(
        """
        INSERT INTO investment_accounts (user_id, name, base_currency, sort_order, version)
        SELECT id, '默认账户', 'CNY', 0, 1 FROM users
        ON CONFLICT (user_id, name) DO NOTHING
        """
    )


def downgrade() -> None:
    """移除投资账户结构。"""
    op.drop_index("ix_investment_accounts_user_sort", table_name="investment_accounts")
    op.drop_table("investment_accounts")
