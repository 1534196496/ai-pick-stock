"""登录、当前会话与退出 API 契约测试。"""

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_auth_repository
from app.main import create_app
from app.modules.auth.domain import (
    SecurityEventRecord,
    SessionPrincipal,
    SessionRecord,
    UserCredentials,
    UserIdentity,
)
from app.modules.auth.enums import SecurityEventType, UserStatus
from app.modules.auth.security import PasswordManager

DUMMY_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/app"


class FakeSessionRepository:
    """在内存中模拟用户、摘要会话和认证审计事件。"""

    def __init__(self) -> None:
        """初始化按邮箱、用户 ID 和令牌摘要建立的索引。"""
        self.users_by_email: dict[str, UserCredentials] = {}
        self.users_by_id: dict[UUID, UserCredentials] = {}
        self.sessions_by_hash: dict[str, SessionRecord] = {}
        self.events: list[SecurityEventRecord] = []

    def seed_user(self, email: str, password: str) -> UserCredentials:
        """使用真实 Argon2id 策略准备可登录测试用户。"""
        now = datetime.now(UTC)
        credentials = UserCredentials(
            identity=UserIdentity(
                id=uuid4(),
                email_normalized=email,
                status=UserStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
            password_hash=PasswordManager().hash(password),
        )
        self.users_by_email[email] = credentials
        self.users_by_id[credentials.identity.id] = credentials
        return credentials

    async def get_credentials_by_email(self, email_normalized: str) -> UserCredentials | None:
        """按规范化邮箱读取登录凭据。"""
        return self.users_by_email.get(email_normalized)

    async def update_password_hash(
        self,
        *,
        user_id: UUID,
        password_hash: str,
        changed_at: datetime,
    ) -> UserCredentials | None:
        """替换旧参数密码摘要并同步两个用户索引。"""
        current = self.users_by_id.get(user_id)
        if current is None:
            return None
        updated = UserCredentials(
            identity=replace(current.identity, updated_at=changed_at),
            password_hash=password_hash,
        )
        self.users_by_id[user_id] = updated
        self.users_by_email[updated.identity.email_normalized] = updated
        return updated

    async def create_session(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
        created_at: datetime | None = None,
    ) -> SessionRecord:
        """仅以内存键保存令牌摘要，不接收原始令牌持久化字段。"""
        record = SessionRecord(
            id=uuid4(),
            user_id=user_id,
            created_at=created_at or datetime.now(UTC),
            expires_at=expires_at,
            revoked_at=None,
        )
        self.sessions_by_hash[token_hash] = record
        return record

    async def get_session_principal(
        self,
        *,
        token_hash: str,
        now: datetime,
    ) -> SessionPrincipal | None:
        """按与真实查询相同的有效期、撤销和用户状态规则解析会话。"""
        session = self.sessions_by_hash.get(token_hash)
        if session is None or session.revoked_at is not None or session.expires_at <= now:
            return None
        credentials = self.users_by_id.get(session.user_id)
        if credentials is None or credentials.identity.status is not UserStatus.ACTIVE:
            return None
        return SessionPrincipal(session=session, identity=credentials.identity)

    async def revoke_session(self, *, session_id: UUID, revoked_at: datetime) -> bool:
        """首次撤销返回真，重复撤销保持幂等并返回假。"""
        for token_hash, session in self.sessions_by_hash.items():
            if session.id == session_id and session.revoked_at is None:
                self.sessions_by_hash[token_hash] = replace(session, revoked_at=revoked_at)
                return True
        return False

    async def record_security_event(
        self,
        *,
        user_id: UUID | None,
        event_type: SecurityEventType,
        subject_hash: str,
        request_id: str,
        created_at: datetime | None = None,
    ) -> SecurityEventRecord:
        """保存去敏事件供会话行为断言。"""
        event = SecurityEventRecord(
            id=uuid4(),
            user_id=user_id,
            event_type=event_type,
            subject_hash=subject_hash,
            request_id=request_id,
            created_at=created_at or datetime.now(UTC),
        )
        self.events.append(event)
        return event


@pytest.fixture
def session_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, FakeSessionRepository]]:
    """创建使用开发 Cookie 和内存 Repository 的 API 客户端。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", DUMMY_DATABASE_URL)
    monkeypatch.setenv("AIPICKSTOCK_ENVIRONMENT", "development")
    repository = FakeSessionRepository()
    application = create_app()
    application.dependency_overrides[get_auth_repository] = lambda: repository

    with TestClient(application) as client:
        client.get("/api/v1/health/live")
        client.headers.update(
            {
                "Origin": "http://testserver",
                "X-CSRF-Token": client.cookies["aipickstock_csrf"],
            }
        )
        yield client, repository


def test_login_sets_cookie_and_current_session_returns_user(
    session_client: tuple[TestClient, FakeSessionRepository],
) -> None:
    """正确凭据应建立 HttpOnly 会话，并可在刷新请求中恢复用户。"""
    client, repository = session_client
    repository.seed_user("owner@example.com", "a-correct-long-password")

    login = client.post(
        "/api/v1/auth/sessions",
        json={"email": " OWNER@EXAMPLE.COM ", "password": "a-correct-long-password"},
    )
    current = client.get("/api/v1/auth/session")

    assert login.status_code == 200
    assert login.json()["email"] == "owner@example.com"
    assert current.status_code == 200
    assert current.json()["email"] == "owner@example.com"
    assert "aipickstock_session=" in login.headers["set-cookie"]
    assert "HttpOnly" in login.headers["set-cookie"]
    assert "SameSite=lax" in login.headers["set-cookie"]
    assert "Secure" not in login.headers["set-cookie"]
    assert len(repository.sessions_by_hash) == 1
    assert next(iter(repository.sessions_by_hash)) not in login.headers["set-cookie"]


def test_login_rotates_existing_browser_session(
    session_client: tuple[TestClient, FakeSessionRepository],
) -> None:
    """同一浏览器再次登录应撤销旧会话并生成不同的新会话。"""
    client, repository = session_client
    repository.seed_user("owner@example.com", "a-correct-long-password")
    body = {"email": "owner@example.com", "password": "a-correct-long-password"}

    first = client.post("/api/v1/auth/sessions", json=body)
    first_cookie = first.cookies["aipickstock_session"]
    second = client.post("/api/v1/auth/sessions", json=body)
    second_cookie = second.cookies["aipickstock_session"]

    sessions = list(repository.sessions_by_hash.values())
    assert first.status_code == second.status_code == 200
    assert first_cookie != second_cookie
    assert len(sessions) == 2
    assert sum(record.revoked_at is not None for record in sessions) == 1
    assert [event.event_type for event in repository.events].count(
        SecurityEventType.SESSION_REVOKED
    ) == 1


def test_invalid_credentials_do_not_reveal_account_existence(
    session_client: tuple[TestClient, FakeSessionRepository],
) -> None:
    """不存在邮箱和错误密码应返回完全一致的状态与响应。"""
    client, repository = session_client
    repository.seed_user("owner@example.com", "a-correct-long-password")

    wrong_password = client.post(
        "/api/v1/auth/sessions",
        json={"email": "owner@example.com", "password": "wrong-long-password"},
    )
    missing_user = client.post(
        "/api/v1/auth/sessions",
        json={"email": "missing@example.com", "password": "wrong-long-password"},
    )

    assert wrong_password.status_code == missing_user.status_code == 401
    for response in (wrong_password, missing_user):
        assert response.json()["error"] == {
            "code": "INVALID_CREDENTIALS",
            "message": "邮箱或密码错误",
            "requestId": response.headers["X-Request-ID"],
        }
    assert len(repository.sessions_by_hash) == 0


def test_logout_is_idempotent_and_invalidates_current_session(
    session_client: tuple[TestClient, FakeSessionRepository],
) -> None:
    """退出应立即使会话失效，并允许客户端安全重试。"""
    client, repository = session_client
    repository.seed_user("owner@example.com", "a-correct-long-password")
    client.post(
        "/api/v1/auth/sessions",
        json={"email": "owner@example.com", "password": "a-correct-long-password"},
    )

    first_logout = client.delete("/api/v1/auth/session")
    second_logout = client.delete("/api/v1/auth/session")
    current = client.get("/api/v1/auth/session")

    assert first_logout.status_code == second_logout.status_code == 204
    assert current.status_code == 401
    assert current.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
    assert sum(
        event.event_type is SecurityEventType.SESSION_REVOKED for event in repository.events
    ) == 1


def test_production_login_uses_host_bound_secure_cookie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """生产登录必须设置 Host 前缀、Secure、HttpOnly 和 SameSite。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", DUMMY_DATABASE_URL)
    monkeypatch.setenv("AIPICKSTOCK_ENVIRONMENT", "production")
    repository = FakeSessionRepository()
    repository.seed_user("owner@example.com", "a-correct-long-password")
    application = create_app()
    application.dependency_overrides[get_auth_repository] = lambda: repository

    with TestClient(application, base_url="https://testserver") as client:
        client.get("/api/v1/health/live")
        client.headers.update(
            {
                "Origin": "https://testserver",
                "X-CSRF-Token": client.cookies["__Host-aipickstock_csrf"],
            }
        )
        response = client.post(
            "/api/v1/auth/sessions",
            json={"email": "owner@example.com", "password": "a-correct-long-password"},
        )

    cookie = response.headers["set-cookie"]
    assert response.status_code == 200
    assert "__Host-aipickstock_session=" in cookie
    assert "Max-Age=2592000" in cookie
    assert "Path=/" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Secure" in cookie
    assert "Domain=" not in cookie
