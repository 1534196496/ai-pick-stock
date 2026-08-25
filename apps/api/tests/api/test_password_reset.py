"""密码重置请求、投递与消费 API 契约测试。"""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_auth_repository, get_password_reset_mailer
from app.core.security import hash_opaque_token
from app.main import create_app
from app.modules.auth.domain import (
    PasswordResetTokenRecord,
    SecurityEventRecord,
    UserCredentials,
    UserIdentity,
)
from app.modules.auth.enums import SecurityEventType, UserStatus
from app.modules.auth.security import PasswordManager

DUMMY_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/app"
SECURE_HEADERS = {
    "Origin": "http://testserver",
    "X-CSRF-Token": "csrf-test-token-1234567890",
}


class FakeResetRepository:
    """为 API 测试保存一个用户和单次摘要令牌。"""

    def __init__(self) -> None:
        """创建固定用户并初始化审计与会话状态。"""
        now = datetime.now(UTC)
        identity = UserIdentity(
            id=uuid4(),
            email_normalized="owner@example.com",
            status=UserStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        self.credentials = UserCredentials(
            identity=identity,
            password_hash=PasswordManager().hash("old-correct-password"),
        )
        self.tokens: dict[str, PasswordResetTokenRecord] = {}
        self.events: list[SecurityEventType] = []
        self.revoked = 0

    async def get_credentials_by_email(
        self,
        email_normalized: str,
    ) -> UserCredentials | None:
        """按固定规范化邮箱返回用户。"""
        return self.credentials if email_normalized == "owner@example.com" else None

    async def create_password_reset_token(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        created_at: datetime,
        expires_at: datetime,
    ) -> PasswordResetTokenRecord:
        """仅按摘要索引测试令牌。"""
        record = PasswordResetTokenRecord(
            id=uuid4(),
            user_id=user_id,
            created_at=created_at,
            expires_at=expires_at,
            used_at=None,
        )
        self.tokens[token_hash] = record
        return record

    async def consume_password_reset_token(
        self,
        *,
        token_hash: str,
        used_at: datetime,
    ) -> PasswordResetTokenRecord | None:
        """首次有效消费返回记录，后续返回空。"""
        record = self.tokens.get(token_hash)
        if record is None or record.used_at is not None or record.expires_at <= used_at:
            return None
        record = replace(record, used_at=used_at)
        self.tokens[token_hash] = record
        return record

    async def update_password_hash(
        self,
        *,
        user_id: UUID,
        password_hash: str,
        changed_at: datetime,
    ) -> UserCredentials | None:
        """替换密码摘要。"""
        self.credentials = UserCredentials(
            identity=replace(self.credentials.identity, updated_at=changed_at),
            password_hash=password_hash,
        )
        return self.credentials

    async def revoke_user_sessions(self, *, user_id: UUID, revoked_at: datetime) -> int:
        """记录现有会话被撤销。"""
        self.revoked += 1
        return 1

    async def record_security_event(
        self,
        *,
        user_id: UUID | None,
        event_type: SecurityEventType,
        subject_hash: str,
        request_id: str,
    ) -> SecurityEventRecord:
        """保存去敏事件。"""
        self.events.append(event_type)
        return SecurityEventRecord(
            id=uuid4(),
            user_id=user_id,
            event_type=event_type,
            subject_hash=subject_hash,
            request_id=request_id,
            created_at=datetime.now(UTC),
        )


class CaptureMailer:
    """捕获邮件参数但不访问网络。"""

    def __init__(self) -> None:
        """初始化投递列表。"""
        self.deliveries: list[tuple[str, str]] = []

    async def send_password_reset(self, *, email: str, token: str) -> None:
        """保存邮箱和短暂原始令牌供测试消费。"""
        self.deliveries.append((email, token))


@pytest.fixture
def reset_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, FakeResetRepository, CaptureMailer]:
    """创建注入内存 Repository 和捕获邮件器的客户端。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", DUMMY_DATABASE_URL)
    repository = FakeResetRepository()
    mailer = CaptureMailer()
    application = create_app()
    application.dependency_overrides[get_auth_repository] = lambda: repository
    application.dependency_overrides[get_password_reset_mailer] = lambda: mailer
    return TestClient(application, headers=SECURE_HEADERS), repository, mailer


def test_reset_request_does_not_reveal_email_existence(
    reset_client: tuple[TestClient, FakeResetRepository, CaptureMailer],
) -> None:
    """存在和不存在邮箱的状态与响应完全一致。"""
    client, _, mailer = reset_client
    with client:
        existing = client.post(
            "/api/v1/auth/password-reset-requests",
            json={"email": "owner@example.com"},
        )
        missing = client.post(
            "/api/v1/auth/password-reset-requests",
            json={"email": "missing@example.com"},
        )
    expected = {"message": "如果该邮箱已注册，我们会发送密码重置邮件"}
    assert existing.status_code == missing.status_code == 202
    assert existing.json() == missing.json() == expected
    assert len(mailer.deliveries) == 1


def test_reset_token_changes_password_revokes_sessions_and_is_single_use(
    reset_client: tuple[TestClient, FakeResetRepository, CaptureMailer],
) -> None:
    """邮件令牌成功一次后立即失效，且旧会话被撤销。"""
    client, repository, mailer = reset_client
    with client:
        client.post(
            "/api/v1/auth/password-reset-requests",
            json={"email": "owner@example.com"},
        )
        token = mailer.deliveries[0][1]
        first = client.post(
            "/api/v1/auth/password-resets",
            json={"token": token, "newPassword": "new-correct-password-123"},
        )
        second = client.post(
            "/api/v1/auth/password-resets",
            json={"token": token, "newPassword": "another-password-123"},
        )
    assert first.status_code == 204
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "INVALID_OR_EXPIRED_RESET_TOKEN"
    assert repository.revoked == 1
    assert PasswordManager().verify(
        repository.credentials.password_hash,
        "new-correct-password-123",
    )
    assert hash_opaque_token(token) in repository.tokens


def test_production_ready_requires_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    """生产未配置 SMTP 时 readiness 明确失败而不是静默上线。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", DUMMY_DATABASE_URL)
    monkeypatch.setenv("AIPICKSTOCK_ENVIRONMENT", "production")

    async def ready_database(_: object) -> bool:
        """隔离数据库探测，仅验证 SMTP readiness。"""
        return True

    with TestClient(create_app(database_probe=ready_database)) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {
        "database": "ok",
        "smtp": "unavailable",
    }
