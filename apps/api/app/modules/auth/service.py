"""注册、登录、当前会话与退出用例。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.core.security import generate_opaque_token, hash_opaque_token, hash_sensitive_value
from app.modules.auth.domain import (
    SecurityEventRecord,
    SessionPrincipal,
    SessionRecord,
    UserCredentials,
    UserIdentity,
)
from app.modules.auth.enums import SecurityEventType, UserStatus
from app.modules.auth.security import PasswordManager

_EMAIL_ADAPTER = TypeAdapter(EmailStr)
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128
_DUMMY_PASSWORD_HASH = PasswordManager().hash(generate_opaque_token())


class AuthRepositoryContract(Protocol):
    """限定认证用例可访问的持久化能力。"""

    async def get_credentials_by_email(self, email_normalized: str) -> UserCredentials | None:
        """按规范化邮箱读取现有用户。"""
        ...

    async def create_user(
        self,
        *,
        email_normalized: str,
        password_hash: str,
    ) -> UserCredentials | None:
        """原子创建用户，邮箱冲突时返回空。"""
        ...

    async def record_security_event(
        self,
        *,
        user_id: UUID | None,
        event_type: SecurityEventType,
        subject_hash: str,
        request_id: str,
    ) -> SecurityEventRecord:
        """保存去敏认证安全事件。"""
        ...

    async def update_password_hash(
        self,
        *,
        user_id: UUID,
        password_hash: str,
        changed_at: datetime,
    ) -> UserCredentials | None:
        """升级用户的旧参数密码摘要。"""
        ...

    async def create_session(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
        created_at: datetime | None = None,
    ) -> SessionRecord:
        """创建只持久化令牌摘要的新会话。"""
        ...

    async def get_session_principal(
        self,
        *,
        token_hash: str,
        now: datetime,
    ) -> SessionPrincipal | None:
        """按摘要解析当前有效会话。"""
        ...

    async def revoke_session(self, *, session_id: UUID, revoked_at: datetime) -> bool:
        """幂等撤销指定会话。"""
        ...


class RegistrationError(Exception):
    """表示可安全返回给注册客户端的稳定领域错误。"""

    def __init__(self, *, code: str, message: str, field: str) -> None:
        """记录稳定错误码、中文修正提示和对应字段。"""
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field


class AuthenticationError(Exception):
    """表示不泄露邮箱存在性或账户状态的统一登录失败。"""

    def __init__(self) -> None:
        """固定登录失败文案，避免调用方拼接出可枚举差异。"""
        super().__init__("邮箱或密码错误")
        self.code = "INVALID_CREDENTIALS"
        self.message = "邮箱或密码错误"


@dataclass(frozen=True, slots=True)
class SessionLoginResult:
    """在 HTTP 边界写入 Cookie 前短暂携带新会话原始令牌。"""

    identity: UserIdentity
    token: str
    expires_at: datetime


class AuthService:
    """编排注册校验、密码摘要、唯一写入和安全审计。"""

    def __init__(
        self,
        repository: AuthRepositoryContract,
        password_manager: PasswordManager | None = None,
    ) -> None:
        """注入持久化契约，并允许测试替换密码策略。"""
        self._repository = repository
        self._password_manager = password_manager or PasswordManager()

    async def register(self, *, email: str, password: str, request_id: str) -> UserIdentity:
        """规范化输入并在一个请求事务中创建新用户与审计事件。"""
        email_normalized = self._normalize_email(email)
        self._validate_password(password)

        existing = await self._repository.get_credentials_by_email(email_normalized)
        if existing is not None:
            raise RegistrationError(
                code="EMAIL_ALREADY_REGISTERED",
                message="该邮箱已注册",
                field="email",
            )

        password_hash = self._password_manager.hash(password)
        created = await self._repository.create_user(
            email_normalized=email_normalized,
            password_hash=password_hash,
        )
        if created is None:
            raise RegistrationError(
                code="EMAIL_ALREADY_REGISTERED",
                message="该邮箱已注册",
                field="email",
            )

        await self._repository.record_security_event(
            user_id=created.identity.id,
            event_type=SecurityEventType.REGISTRATION_SUCCEEDED,
            subject_hash=hash_sensitive_value(email_normalized),
            request_id=request_id,
        )
        return created.identity

    async def login(
        self,
        *,
        email: str,
        password: str,
        current_token: str | None,
        request_id: str,
        lifetime: timedelta,
    ) -> SessionLoginResult:
        """统一验证凭据、轮换浏览器旧会话并签发新会话。"""
        now = datetime.now(UTC)
        email_normalized = self._normalize_login_email(email)
        credentials = (
            await self._repository.get_credentials_by_email(email_normalized)
            if email_normalized is not None
            else None
        )

        password_hash = (
            credentials.password_hash if credentials is not None else _DUMMY_PASSWORD_HASH
        )
        password_matches = self._password_manager.verify(password_hash, password)
        if (
            credentials is None
            or credentials.identity.status is not UserStatus.ACTIVE
            or not password_matches
        ):
            await self._repository.record_security_event(
                user_id=credentials.identity.id if credentials is not None else None,
                event_type=SecurityEventType.LOGIN_FAILED,
                subject_hash=hash_sensitive_value(
                    email_normalized or self._safe_invalid_subject(email)
                ),
                request_id=request_id,
            )
            raise AuthenticationError

        if self._password_manager.needs_rehash(credentials.password_hash):
            await self._repository.update_password_hash(
                user_id=credentials.identity.id,
                password_hash=self._password_manager.hash(password),
                changed_at=now,
            )

        if current_token:
            current_principal = await self.authenticate(token=current_token, now=now)
            if current_principal is not None and await self._repository.revoke_session(
                session_id=current_principal.session.id,
                revoked_at=now,
            ):
                await self._repository.record_security_event(
                    user_id=current_principal.identity.id,
                    event_type=SecurityEventType.SESSION_REVOKED,
                    subject_hash=hash_sensitive_value(
                        current_principal.identity.email_normalized
                    ),
                    request_id=request_id,
                )

        token = generate_opaque_token()
        expires_at = now + lifetime
        await self._repository.create_session(
            user_id=credentials.identity.id,
            token_hash=hash_opaque_token(token),
            created_at=now,
            expires_at=expires_at,
        )
        await self._repository.record_security_event(
            user_id=credentials.identity.id,
            event_type=SecurityEventType.LOGIN_SUCCEEDED,
            subject_hash=hash_sensitive_value(credentials.identity.email_normalized),
            request_id=request_id,
        )
        return SessionLoginResult(
            identity=credentials.identity,
            token=token,
            expires_at=expires_at,
        )

    async def authenticate(
        self,
        *,
        token: str | None,
        now: datetime | None = None,
    ) -> SessionPrincipal | None:
        """从 Cookie 原始令牌解析有效会话，不向调用方暴露令牌摘要。"""
        if not token:
            return None
        return await self._repository.get_session_principal(
            token_hash=hash_opaque_token(token),
            now=now or datetime.now(UTC),
        )

    async def logout(
        self,
        *,
        token: str | None,
        request_id: str,
    ) -> None:
        """幂等撤销当前有效会话并记录一次去敏审计事件。"""
        now = datetime.now(UTC)
        principal = await self.authenticate(token=token, now=now)
        if principal is None:
            return
        revoked = await self._repository.revoke_session(
            session_id=principal.session.id,
            revoked_at=now,
        )
        if revoked:
            await self._repository.record_security_event(
                user_id=principal.identity.id,
                event_type=SecurityEventType.SESSION_REVOKED,
                subject_hash=hash_sensitive_value(principal.identity.email_normalized),
                request_id=request_id,
            )

    @staticmethod
    def _normalize_email(email: str) -> str:
        """校验邮箱语法并转换为忽略大小写的唯一数据库形式。"""
        try:
            validated = _EMAIL_ADAPTER.validate_python(email.strip())
        except ValidationError as error:
            raise RegistrationError(
                code="INVALID_EMAIL",
                message="请输入有效的邮箱地址",
                field="email",
            ) from error
        return str(validated).casefold()

    @staticmethod
    def _validate_password(password: str) -> None:
        """执行已确认的 12–128 字符密码长度策略。"""
        if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
            raise RegistrationError(
                code="WEAK_PASSWORD",
                message="密码长度必须为 12–128 个字符",
                field="password",
            )

    @classmethod
    def _normalize_login_email(cls, email: str) -> str | None:
        """登录时复用邮箱规范化，但把语法错误折叠为统一凭据失败。"""
        try:
            return cls._normalize_email(email)
        except RegistrationError:
            return None

    @staticmethod
    def _safe_invalid_subject(email: str) -> str:
        """限制无效输入进入审计摘要前的长度，并为全空输入提供固定主体。"""
        return email.strip().casefold()[:320] or "<invalid-email>"
