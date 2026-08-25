"""密码重置领域规则单元测试。"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core.security import hash_opaque_token
from app.modules.auth.domain import (
    PasswordResetTokenRecord,
    SecurityEventRecord,
    UserCredentials,
    UserIdentity,
)
from app.modules.auth.enums import SecurityEventType, UserStatus
from app.modules.auth.reset_service import PasswordResetError, PasswordResetService
from app.modules.auth.security import PasswordManager

pytestmark = pytest.mark.anyio


class FakeResetRepository:
    """以内存状态验证令牌单次消费和会话撤销编排。"""

    def __init__(self) -> None:
        """准备用户、摘要令牌、事件和会话计数。"""
        now = datetime.now(UTC)
        identity = UserIdentity(
            id=uuid4(),
            email_normalized="owner@example.com",
            status=UserStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        self.credentials = UserCredentials(
            identity=identity, password_hash=PasswordManager().hash("old-correct-password")
        )
        self.tokens: dict[str, PasswordResetTokenRecord] = {}
        self.events: list[SecurityEventType] = []
        self.revoked_sessions = 0

    async def get_credentials_by_email(self, email_normalized: str) -> UserCredentials | None:
        """仅返回固定测试用户。"""
        return (
            self.credentials
            if email_normalized == self.credentials.identity.email_normalized
            else None
        )

    async def create_password_reset_token(
        self, *, user_id: UUID, token_hash: str, created_at: datetime, expires_at: datetime
    ) -> PasswordResetTokenRecord:
        """保存摘要并返回不含摘要的记录。"""
        record = PasswordResetTokenRecord(
            id=uuid4(), user_id=user_id, created_at=created_at, expires_at=expires_at, used_at=None
        )
        self.tokens[token_hash] = record
        return record

    async def consume_password_reset_token(
        self, *, token_hash: str, used_at: datetime
    ) -> PasswordResetTokenRecord | None:
        """模拟未使用且未过期的原子消费。"""
        record = self.tokens.get(token_hash)
        if record is None or record.used_at is not None or record.expires_at <= used_at:
            return None
        consumed = replace(record, used_at=used_at)
        self.tokens[token_hash] = consumed
        return consumed

    async def update_password_hash(
        self, *, user_id: UUID, password_hash: str, changed_at: datetime
    ) -> UserCredentials | None:
        """更新测试用户密码摘要。"""
        self.credentials = UserCredentials(
            identity=replace(self.credentials.identity, updated_at=changed_at),
            password_hash=password_hash,
        )
        return self.credentials

    async def revoke_user_sessions(self, *, user_id: UUID, revoked_at: datetime) -> int:
        """记录全部会话已被撤销。"""
        self.revoked_sessions += 2
        return 2

    async def record_security_event(
        self,
        *,
        user_id: UUID | None,
        event_type: SecurityEventType,
        subject_hash: str,
        request_id: str,
    ) -> SecurityEventRecord:
        """保存事件类型并返回去敏记录。"""
        self.events.append(event_type)
        return SecurityEventRecord(
            id=uuid4(),
            user_id=user_id,
            event_type=event_type,
            subject_hash=subject_hash,
            request_id=request_id,
            created_at=datetime.now(UTC),
        )


async def test_reset_token_expires_in_30_minutes_and_database_only_receives_hash() -> None:
    """签发结果携带原始令牌，但 Repository 键必须是 SHA-256 摘要。"""
    repository = FakeResetRepository()
    now = datetime(2026, 8, 24, tzinfo=UTC)
    delivery = await PasswordResetService(repository).request_reset(
        email=" OWNER@EXAMPLE.COM ", request_id="req_reset", now=now
    )
    assert delivery is not None
    assert delivery.expires_at == now + timedelta(minutes=30)
    assert list(repository.tokens) == [hash_opaque_token(delivery.token)]
    assert delivery.token not in repository.tokens


async def test_reset_token_is_single_use_and_revokes_existing_sessions() -> None:
    """首次消费成功，第二次统一失败，并替换密码摘要。"""
    repository = FakeResetRepository()
    service = PasswordResetService(repository)
    delivery = await service.request_reset(email="owner@example.com", request_id="req_request")
    assert delivery is not None
    await service.reset_password(
        token=delivery.token, new_password="new-correct-password-123", request_id="req_success"
    )
    with pytest.raises(PasswordResetError):
        await service.reset_password(
            token=delivery.token, new_password="another-password-123", request_id="req_repeat"
        )
    assert PasswordManager().verify(
        repository.credentials.password_hash, "new-correct-password-123"
    )
    assert repository.revoked_sessions == 2
    assert SecurityEventType.PASSWORD_RESET_SUCCEEDED in repository.events


async def test_missing_email_and_expired_token_share_safe_behavior() -> None:
    """不存在邮箱不签发令牌，过期令牌不暴露具体失败原因。"""
    repository = FakeResetRepository()
    service = PasswordResetService(repository)
    assert (
        await service.request_reset(email="missing@example.com", request_id="req_missing") is None
    )
    now = datetime.now(UTC)
    repository.tokens["a" * 64] = PasswordResetTokenRecord(
        id=uuid4(),
        user_id=repository.credentials.identity.id,
        created_at=now - timedelta(hours=1),
        expires_at=now - timedelta(minutes=1),
        used_at=None,
    )
    with pytest.raises(PasswordResetError, match="无效或已过期"):
        await service.reset_password(
            token="not-the-token",
            new_password="new-correct-password-123",
            request_id="req_expired",
            now=now,
        )
