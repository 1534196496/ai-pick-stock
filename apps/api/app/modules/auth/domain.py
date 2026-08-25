"""认证模块对服务层公开的不可变领域记录。"""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.auth.enums import SecurityEventType, UserStatus


@dataclass(frozen=True, slots=True)
class UserIdentity:
    """表示不包含密码摘要的用户公开身份。"""

    id: UUID
    email_normalized: str
    status: UserStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class UserCredentials:
    """仅供认证服务验证密码使用的身份与摘要组合。"""

    identity: UserIdentity
    password_hash: str


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """表示不暴露令牌或令牌摘要的会话状态。"""

    id: UUID
    user_id: UUID
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class SessionPrincipal:
    """表示由有效会话解析出的当前用户主体。"""

    session: SessionRecord
    identity: UserIdentity


@dataclass(frozen=True, slots=True)
class SecurityEventRecord:
    """表示已经去除敏感原文的认证审计记录。"""

    id: UUID
    user_id: UUID | None
    event_type: SecurityEventType
    subject_hash: str
    request_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PasswordResetTokenRecord:
    """表示不暴露令牌摘要的密码重置状态。"""

    id: UUID
    user_id: UUID
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None
