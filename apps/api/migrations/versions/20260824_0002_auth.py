"""创建认证用户、会话与安全事件表。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0002"
down_revision: str | None = "20260824_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_status_type = sa.Enum(
    "ACTIVE",
    "DISABLED",
    name="user_status",
    native_enum=False,
    create_constraint=False,
)

security_event_type = sa.Enum(
    "REGISTRATION_SUCCEEDED",
    "LOGIN_SUCCEEDED",
    "LOGIN_FAILED",
    "SESSION_REVOKED",
    "PASSWORD_RESET_REQUESTED",
    "PASSWORD_RESET_SUCCEEDED",
    name="security_event_type",
    native_enum=False,
    create_constraint=False,
)


def upgrade() -> None:
    """建立认证数据结构及数据库级安全约束。"""
    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email_normalized", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column(
            "status",
            user_status_type,
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "email_normalized = lower(btrim(email_normalized)) "
            "AND char_length(email_normalized) BETWEEN 3 AND 320",
            name="ck_users_email_normalized",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'DISABLED')",
            name="user_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email_normalized", name="uq_users_email_normalized"),
    )

    op.create_table(
        "sessions",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sessions_token_hash_sha256",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_sessions_expires_after_creation",
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_sessions_revoked_after_creation",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_sessions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index(
        "ix_sessions_user_expires",
        "sessions",
        ["user_id", "expires_at"],
        unique=False,
    )

    op.create_table(
        "security_events",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", security_event_type, nullable=False),
        sa.Column("subject_hash", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "subject_hash ~ '^[0-9a-f]{64}$'",
            name="ck_security_events_subject_hash_sha256",
        ),
        sa.CheckConstraint(
            "event_type IN ("
            "'REGISTRATION_SUCCEEDED', 'LOGIN_SUCCEEDED', 'LOGIN_FAILED', "
            "'SESSION_REVOKED', 'PASSWORD_RESET_REQUESTED', 'PASSWORD_RESET_SUCCEEDED'"
            ")",
            name="security_event_type",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_security_events_user_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_security_events"),
    )
    op.create_index(
        "ix_security_events_user_created",
        "security_events",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_security_events_subject_created",
        "security_events",
        ["subject_hash", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """按外键依赖顺序移除认证数据结构。"""
    op.drop_index("ix_security_events_subject_created", table_name="security_events")
    op.drop_index("ix_security_events_user_created", table_name="security_events")
    op.drop_table("security_events")
    op.drop_index("ix_sessions_user_expires", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("users")
