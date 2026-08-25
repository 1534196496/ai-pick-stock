"""认证模块的用户、会话与安全事件持久化模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Uuid as SqlUuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.modules.auth.enums import SecurityEventType, UserStatus

user_status_type = Enum(
    UserStatus,
    name="user_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda members: [member.value for member in members],
)

security_event_type = Enum(
    SecurityEventType,
    name="security_event_type",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda members: [member.value for member in members],
)


class User(Base):
    """保存规范化登录主体及不可逆密码摘要。"""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email_normalized", name="uq_users_email_normalized"),
        CheckConstraint(
            "email_normalized = lower(btrim(email_normalized)) "
            "AND char_length(email_normalized) BETWEEN 3 AND 320",
            name="ck_users_email_normalized",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'DISABLED')",
            name="user_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        user_status_type,
        nullable=False,
        default=UserStatus.ACTIVE,
        server_default=UserStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Session(Base):
    """保存服务端不透明会话的令牌摘要与有效期。"""

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'",
            name="ck_sessions_token_hash_sha256",
        ),
        CheckConstraint(
            "expires_at > created_at",
            name="ck_sessions_expires_after_creation",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_sessions_revoked_after_creation",
        ),
        Index("ix_sessions_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        SqlUuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PasswordResetToken(Base):
    """保存短期单次密码重置令牌的不可逆摘要。"""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
        CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name="ck_password_reset_tokens_hash_sha256"
        ),
        CheckConstraint(
            "expires_at > created_at", name="ck_password_reset_tokens_expires_after_creation"
        ),
        CheckConstraint(
            "used_at IS NULL OR used_at >= created_at",
            name="ck_password_reset_tokens_used_after_creation",
        ),
        Index("ix_password_reset_tokens_user_expires", "user_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[UUID] = mapped_column(
        SqlUuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SecurityEvent(Base):
    """保存去敏后的认证审计轨迹，不保存密码或令牌原文。"""

    __tablename__ = "security_events"
    __table_args__ = (
        CheckConstraint(
            "subject_hash ~ '^[0-9a-f]{64}$'",
            name="ck_security_events_subject_hash_sha256",
        ),
        CheckConstraint(
            "event_type IN ("
            "'REGISTRATION_SUCCEEDED', 'LOGIN_SUCCEEDED', 'LOGIN_FAILED', "
            "'SESSION_REVOKED', 'PASSWORD_RESET_REQUESTED', 'PASSWORD_RESET_SUCCEEDED'"
            ")",
            name="security_event_type",
        ),
        Index("ix_security_events_user_created", "user_id", "created_at"),
        Index("ix_security_events_subject_created", "subject_hash", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        SqlUuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID | None] = mapped_column(
        SqlUuid,
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    event_type: Mapped[SecurityEventType] = mapped_column(
        security_event_type,
        nullable=False,
    )
    subject_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
