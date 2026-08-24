"""用户注册 API 契约测试。"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_auth_repository
from app.main import create_app
from app.modules.auth.domain import SecurityEventRecord, UserCredentials, UserIdentity
from app.modules.auth.enums import SecurityEventType, UserStatus

DUMMY_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/app"


class FakeAuthRepository:
    """为 API 测试保存最小认证状态且不访问真实数据库。"""

    def __init__(self) -> None:
        """初始化按规范化邮箱索引的用户和安全事件集合。"""
        self.users: dict[str, UserCredentials] = {}
        self.events: list[SecurityEventRecord] = []

    async def get_credentials_by_email(self, email_normalized: str) -> UserCredentials | None:
        """按规范化邮箱读取测试用户。"""
        return self.users.get(email_normalized)

    async def create_user(
        self,
        *,
        email_normalized: str,
        password_hash: str,
    ) -> UserCredentials | None:
        """模拟数据库唯一约束并保存密码摘要。"""
        if email_normalized in self.users:
            return None
        now = datetime.now(UTC)
        credentials = UserCredentials(
            identity=UserIdentity(
                id=uuid4(),
                email_normalized=email_normalized,
                status=UserStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            ),
            password_hash=password_hash,
        )
        self.users[email_normalized] = credentials
        return credentials

    async def record_security_event(
        self,
        *,
        user_id: UUID | None,
        event_type: SecurityEventType,
        subject_hash: str,
        request_id: str,
        created_at: datetime | None = None,
    ) -> SecurityEventRecord:
        """保存去敏安全事件供断言。"""
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
def registration_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, FakeAuthRepository]:
    """创建注入内存 Repository 的注册 API 客户端。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", DUMMY_DATABASE_URL)
    repository = FakeAuthRepository()
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


def test_registration_normalizes_email_and_never_returns_password(
    registration_client: tuple[TestClient, FakeAuthRepository],
) -> None:
    """注册成功应返回规范化身份，且响应不含密码或摘要字段。"""
    client, repository = registration_client

    response = client.post(
        "/api/v1/auth/registrations",
        json={"email": " Owner@Example.COM ", "password": "a-correct-long-password"},
        headers={"X-Request-ID": "req_registration_success"},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["email"] == "owner@example.com"
    assert payload["status"] == "ACTIVE"
    assert "createdAt" in payload
    assert "password" not in payload
    assert "passwordHash" not in payload
    assert repository.users["owner@example.com"].password_hash.startswith("$argon2id$")
    assert repository.events[0].event_type is SecurityEventType.REGISTRATION_SUCCEEDED
    assert repository.events[0].subject_hash != "owner@example.com"


@pytest.mark.parametrize(
    ("body", "expected_code", "expected_field"),
    [
        (
            {"email": "not-an-email", "password": "a-correct-long-password"},
            "INVALID_EMAIL",
            "email",
        ),
        (
            {"email": "owner@example.com", "password": "too-short"},
            "WEAK_PASSWORD",
            "password",
        ),
    ],
)
def test_registration_validation_errors_use_stable_envelope(
    registration_client: tuple[TestClient, FakeAuthRepository],
    body: dict[str, str],
    expected_code: str,
    expected_field: str,
) -> None:
    """非法邮箱与弱密码应使用相同错误外壳和稳定错误码。"""
    client, repository = registration_client

    response = client.post("/api/v1/auth/registrations", json=body)

    assert response.status_code == 422
    assert response.json() == {
        "error": {
            "code": expected_code,
            "message": (
                "请输入有效的邮箱地址"
                if expected_code == "INVALID_EMAIL"
                else "密码长度必须为 12–128 个字符"
            ),
            "details": {"field": expected_field},
            "requestId": response.headers["X-Request-ID"],
        }
    }
    assert repository.users == {}


def test_duplicate_email_returns_conflict_with_same_error_envelope(
    registration_client: tuple[TestClient, FakeAuthRepository],
) -> None:
    """重复邮箱应忽略大小写，并使用统一错误结构返回冲突。"""
    client, _ = registration_client
    first = client.post(
        "/api/v1/auth/registrations",
        json={"email": "owner@example.com", "password": "a-correct-long-password"},
    )

    duplicate = client.post(
        "/api/v1/auth/registrations",
        json={"email": "OWNER@EXAMPLE.COM", "password": "another-long-password"},
    )

    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json() == {
        "error": {
            "code": "EMAIL_ALREADY_REGISTERED",
            "message": "该邮箱已注册",
            "details": {"field": "email"},
            "requestId": duplicate.headers["X-Request-ID"],
        }
    }
