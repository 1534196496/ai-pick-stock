"""认证模块数据库访问边界。"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.domain import (
    SecurityEventRecord,
    SessionPrincipal,
    SessionRecord,
    UserCredentials,
    UserIdentity,
)
from app.modules.auth.enums import SecurityEventType, UserStatus
from app.modules.auth.models import SecurityEvent, Session, User


class AuthRepository:
    """封装认证持久化操作，并只向上层返回不可变领域记录。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定由调用方管理事务边界的异步数据库会话。"""
        self._session = session

    async def create_user(
        self,
        *,
        email_normalized: str,
        password_hash: str,
    ) -> UserCredentials | None:
        """原子新增活跃用户；唯一邮箱冲突时返回空且不破坏事务。"""
        statement = (
            insert(User)
            .values(
                email_normalized=email_normalized,
                password_hash=password_hash,
                status=UserStatus.ACTIVE,
            )
            .on_conflict_do_nothing(index_elements=[User.email_normalized])
            .returning(User)
        )
        user = await self._session.scalar(statement)
        return self._to_credentials(user) if user is not None else None

    async def get_credentials_by_email(self, email_normalized: str) -> UserCredentials | None:
        """按唯一规范化邮箱读取登录验证所需记录。"""
        statement = select(User).where(User.email_normalized == email_normalized)
        user = await self._session.scalar(statement)
        return self._to_credentials(user) if user is not None else None

    async def update_password_hash(
        self,
        *,
        user_id: UUID,
        password_hash: str,
        changed_at: datetime,
    ) -> UserCredentials | None:
        """原子更新密码摘要和资料更新时间。"""
        statement = (
            update(User)
            .where(User.id == user_id)
            .values(password_hash=password_hash, updated_at=changed_at)
            .returning(User)
        )
        user = await self._session.scalar(statement)
        return self._to_credentials(user) if user is not None else None

    async def set_user_status(
        self,
        *,
        user_id: UUID,
        status: UserStatus,
        changed_at: datetime,
    ) -> UserIdentity | None:
        """切换用户状态并返回不含密码摘要的身份记录。"""
        statement = (
            update(User)
            .where(User.id == user_id)
            .values(status=status, updated_at=changed_at)
            .returning(User)
        )
        user = await self._session.scalar(statement)
        return self._to_identity(user) if user is not None else None

    async def create_session(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
        created_at: datetime | None = None,
    ) -> SessionRecord:
        """持久化令牌摘要，并且永不接收或返回原始会话令牌。"""
        session_record = Session(
            user_id=user_id,
            token_hash=token_hash,
            created_at=created_at or datetime.now(UTC),
            expires_at=expires_at,
        )
        self._session.add(session_record)
        await self._session.flush()
        return self._to_session_record(session_record)

    async def get_session_principal(
        self,
        *,
        token_hash: str,
        now: datetime,
    ) -> SessionPrincipal | None:
        """解析未撤销、未过期且用户仍活跃的当前会话。"""
        statement = (
            select(Session, User)
            .join(User, User.id == Session.user_id)
            .where(
                Session.token_hash == token_hash,
                Session.revoked_at.is_(None),
                Session.expires_at > now,
                User.status == UserStatus.ACTIVE,
            )
        )
        row = (await self._session.execute(statement)).one_or_none()
        if row is None:
            return None
        session_record, user = row
        return SessionPrincipal(
            session=self._to_session_record(session_record),
            identity=self._to_identity(user),
        )

    async def revoke_session(self, *, session_id: UUID, revoked_at: datetime) -> bool:
        """幂等撤销指定会话，并报告本次是否实际改变状态。"""
        statement = (
            update(Session)
            .where(Session.id == session_id, Session.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
            .returning(Session.id)
        )
        revoked_id = await self._session.scalar(statement)
        return revoked_id is not None

    async def revoke_user_sessions(self, *, user_id: UUID, revoked_at: datetime) -> int:
        """撤销用户全部未撤销会话，并返回实际更新数量。"""
        statement = (
            update(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
            .returning(Session.id)
        )
        revoked_ids = (await self._session.scalars(statement)).all()
        return len(revoked_ids)

    async def record_security_event(
        self,
        *,
        user_id: UUID | None,
        event_type: SecurityEventType,
        subject_hash: str,
        request_id: str,
        created_at: datetime | None = None,
    ) -> SecurityEventRecord:
        """写入只含摘要和请求标识的安全审计事件。"""
        event = SecurityEvent(
            user_id=user_id,
            event_type=event_type,
            subject_hash=subject_hash,
            request_id=request_id,
            created_at=created_at or datetime.now(UTC),
        )
        self._session.add(event)
        await self._session.flush()
        return self._to_security_event_record(event)

    @staticmethod
    def _to_identity(user: User) -> UserIdentity:
        """把用户 ORM 实例裁剪为不含密码摘要的领域身份。"""
        return UserIdentity(
            id=user.id,
            email_normalized=user.email_normalized,
            status=user.status,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    @classmethod
    def _to_credentials(cls, user: User) -> UserCredentials:
        """把用户 ORM 实例转换为仅供认证服务使用的凭据记录。"""
        return UserCredentials(
            identity=cls._to_identity(user),
            password_hash=user.password_hash,
        )

    @staticmethod
    def _to_session_record(session: Session) -> SessionRecord:
        """把会话 ORM 实例转换为不含任何令牌材料的领域记录。"""
        return SessionRecord(
            id=session.id,
            user_id=session.user_id,
            created_at=session.created_at,
            expires_at=session.expires_at,
            revoked_at=session.revoked_at,
        )

    @staticmethod
    def _to_security_event_record(event: SecurityEvent) -> SecurityEventRecord:
        """把安全事件 ORM 实例转换为不可变领域记录。"""
        return SecurityEventRecord(
            id=event.id,
            user_id=event.user_id,
            event_type=event.event_type,
            subject_hash=event.subject_hash,
            request_id=event.request_id,
            created_at=event.created_at,
        )
