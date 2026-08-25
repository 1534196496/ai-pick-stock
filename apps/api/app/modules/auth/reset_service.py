"""密码重置令牌签发、消费和会话撤销用例。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.core.security import generate_opaque_token, hash_opaque_token, hash_sensitive_value
from app.modules.auth.domain import PasswordResetTokenRecord, SecurityEventRecord, UserCredentials
from app.modules.auth.enums import SecurityEventType
from app.modules.auth.security import PasswordManager
from app.modules.auth.service import AuthService, RegistrationError

RESET_TOKEN_LIFETIME = timedelta(minutes=30)


class PasswordResetRepositoryContract(Protocol):
    """限定密码重置服务可使用的持久化能力。"""

    async def get_credentials_by_email(self, email_normalized: str) -> UserCredentials | None: ...
    async def create_password_reset_token(
        self, *, user_id: UUID, token_hash: str, created_at: datetime, expires_at: datetime
    ) -> PasswordResetTokenRecord: ...
    async def consume_password_reset_token(
        self, *, token_hash: str, used_at: datetime
    ) -> PasswordResetTokenRecord | None: ...
    async def update_password_hash(
        self, *, user_id: UUID, password_hash: str, changed_at: datetime
    ) -> UserCredentials | None: ...
    async def revoke_user_sessions(self, *, user_id: UUID, revoked_at: datetime) -> int: ...
    async def record_security_event(
        self,
        *,
        user_id: UUID | None,
        event_type: SecurityEventType,
        subject_hash: str,
        request_id: str,
    ) -> SecurityEventRecord: ...


@dataclass(frozen=True, slots=True)
class PasswordResetDelivery:
    """仅在邮件适配边界短暂携带原始令牌。"""

    email: str
    token: str
    expires_at: datetime


class PasswordResetError(Exception):
    """表示不区分不存在、过期或已使用的统一令牌失败。"""

    def __init__(
        self, code: str = "INVALID_OR_EXPIRED_RESET_TOKEN", message: str = "重置链接无效或已过期"
    ) -> None:
        """固定公开错误，避免暴露令牌状态。"""
        super().__init__(message)
        self.code = code
        self.message = message


class PasswordResetService:
    """签发短期摘要令牌，并以原子消费完成密码轮换。"""

    def __init__(
        self,
        repository: PasswordResetRepositoryContract,
        password_manager: PasswordManager | None = None,
    ) -> None:
        """注入持久化和密码策略。"""
        self._repository = repository
        self._password_manager = password_manager or PasswordManager()

    async def request_reset(
        self, *, email: str, request_id: str, now: datetime | None = None
    ) -> PasswordResetDelivery | None:
        """无论邮箱是否存在都记录去敏事件，仅为现有用户签发令牌。"""
        current = now or datetime.now(UTC)
        normalized = AuthService._normalize_login_email(email)
        credentials = (
            await self._repository.get_credentials_by_email(normalized) if normalized else None
        )
        subject = normalized or AuthService._safe_invalid_subject(email)
        await self._repository.record_security_event(
            user_id=credentials.identity.id if credentials else None,
            event_type=SecurityEventType.PASSWORD_RESET_REQUESTED,
            subject_hash=hash_sensitive_value(subject),
            request_id=request_id,
        )
        if credentials is None:
            return None
        token = generate_opaque_token()
        expires_at = current + RESET_TOKEN_LIFETIME
        await self._repository.create_password_reset_token(
            user_id=credentials.identity.id,
            token_hash=hash_opaque_token(token),
            created_at=current,
            expires_at=expires_at,
        )
        return PasswordResetDelivery(
            email=credentials.identity.email_normalized, token=token, expires_at=expires_at
        )

    async def reset_password(
        self, *, token: str, new_password: str, request_id: str, now: datetime | None = None
    ) -> None:
        """单次消费令牌、更新密码、撤销会话并记录成功事件。"""
        try:
            AuthService._validate_password(new_password)
        except RegistrationError as error:
            raise PasswordResetError(code=error.code, message=error.message) from error
        current = now or datetime.now(UTC)
        if not token:
            raise PasswordResetError
        record = await self._repository.consume_password_reset_token(
            token_hash=hash_opaque_token(token), used_at=current
        )
        if record is None:
            raise PasswordResetError
        await self._repository.update_password_hash(
            user_id=record.user_id,
            password_hash=self._password_manager.hash(new_password),
            changed_at=current,
        )
        await self._repository.revoke_user_sessions(user_id=record.user_id, revoked_at=current)
        await self._repository.record_security_event(
            user_id=record.user_id,
            event_type=SecurityEventType.PASSWORD_RESET_SUCCEEDED,
            subject_hash=hash_sensitive_value(str(record.user_id)),
            request_id=request_id,
        )
