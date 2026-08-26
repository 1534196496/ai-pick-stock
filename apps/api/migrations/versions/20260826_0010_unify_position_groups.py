"""使用统一分组承载持仓与自选。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260826_0010"
down_revision: str | None = "20260826_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """迁移账户持仓至统一分组，并移除旧账户结构。"""
    op.add_column("positions", sa.Column("group_id", sa.Uuid(), nullable=True))
    op.execute(
        """
        INSERT INTO watchlist_groups (user_id, name, is_default, sort_order, version)
        SELECT a.user_id, a.name, false, a.sort_order + 1, 1
        FROM investment_accounts a
        WHERE a.name <> '默认账户'
          AND NOT EXISTS (
            SELECT 1 FROM watchlist_groups g
            WHERE g.user_id = a.user_id AND g.name = a.name
          )
        """
    )
    op.execute(
        """
        UPDATE positions p
        SET group_id = COALESCE(
          (
            SELECT g.id FROM watchlist_groups g
            JOIN investment_accounts a ON a.id = p.account_id
            WHERE g.user_id = a.user_id
              AND a.name = '默认账户'
              AND g.is_default = true
            LIMIT 1
          ),
          (
            SELECT g.id FROM watchlist_groups g
            JOIN investment_accounts a ON a.id = p.account_id
            WHERE g.user_id = a.user_id AND g.name = a.name
            LIMIT 1
          )
        )
        """
    )
    op.alter_column("positions", "group_id", nullable=False)
    op.drop_index("ix_positions_account_created", table_name="positions")
    op.drop_constraint(
        "uq_positions_account_instrument",
        "positions",
        type_="unique",
    )
    op.drop_constraint(
        "fk_positions_account_id_investment_accounts",
        "positions",
        type_="foreignkey",
    )
    op.drop_column("positions", "account_id")
    op.create_foreign_key(
        "fk_positions_group_id_watchlist_groups",
        "positions",
        "watchlist_groups",
        ["group_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_positions_group_instrument",
        "positions",
        ["group_id", "instrument_id"],
    )
    op.create_index(
        "ix_positions_group_created",
        "positions",
        ["group_id", "created_at", "id"],
        unique=False,
    )
    op.drop_index("ix_investment_accounts_user_sort", table_name="investment_accounts")
    op.drop_table("investment_accounts")


def downgrade() -> None:
    """按分组重建兼容账户，并把持仓迁回账户。"""
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
        SELECT user_id, name, 'CNY', sort_order, 1 FROM watchlist_groups
        """
    )
    op.add_column("positions", sa.Column("account_id", sa.Uuid(), nullable=True))
    op.execute(
        """
        UPDATE positions p
        SET account_id = a.id
        FROM watchlist_groups g
        JOIN investment_accounts a
          ON a.user_id = g.user_id AND a.name = g.name
        WHERE p.group_id = g.id
        """
    )
    op.alter_column("positions", "account_id", nullable=False)
    op.drop_index("ix_positions_group_created", table_name="positions")
    op.drop_constraint("uq_positions_group_instrument", "positions", type_="unique")
    op.drop_constraint(
        "fk_positions_group_id_watchlist_groups",
        "positions",
        type_="foreignkey",
    )
    op.drop_column("positions", "group_id")
    op.create_foreign_key(
        "fk_positions_account_id_investment_accounts",
        "positions",
        "investment_accounts",
        ["account_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_positions_account_instrument",
        "positions",
        ["account_id", "instrument_id"],
    )
    op.create_index(
        "ix_positions_account_created",
        "positions",
        ["account_id", "created_at", "id"],
        unique=False,
    )
