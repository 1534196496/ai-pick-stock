"""Origin、CSRF 双提交 Cookie 与认证限流契约测试。"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.middleware import RateLimitDecision
from app.main import create_app

DUMMY_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/app"


class RejectingRateLimiter:
    """记录去敏键并拒绝请求，用于验证认证限流接入点。"""

    def __init__(self) -> None:
        """初始化最近一次限流参数。"""
        self.keys: tuple[str, ...] = ()

    async def check(
        self,
        *,
        keys: tuple[str, ...],
        limit: int,
        window_seconds: int,
    ) -> RateLimitDecision:
        """保存维度并返回固定的等待时间。"""
        self.keys = keys
        assert limit == 10
        assert window_seconds == 60
        return RateLimitDecision(False, 17)


@pytest.fixture
def csrf_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """创建带简单写路由的安全中间件测试客户端。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", DUMMY_DATABASE_URL)
    application = create_app()

    @application.post("/api/v1/test/write")
    async def write() -> dict[str, bool]:
        """返回固定结果，证明请求已通过安全中间件。"""
        return {"saved": True}

    with TestClient(application) as client:
        yield client


def test_safe_request_issues_csrf_cookie_without_exposing_body(csrf_client: TestClient) -> None:
    """安全请求应引导客户端取得 CSRF Cookie，正文仍保持原契约。"""
    response = csrf_client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert csrf_client.cookies["aipickstock_csrf"]
    assert "HttpOnly" not in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]


def test_write_request_without_csrf_header_is_rejected(csrf_client: TestClient) -> None:
    """即使 Cookie 已存在，缺少双提交请求头的写请求也必须拒绝。"""
    csrf_client.get("/api/v1/health/live")
    response = csrf_client.post(
        "/api/v1/test/write",
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_TOKEN_INVALID"
    assert response.json()["error"]["requestId"] == response.headers["X-Request-ID"]


def test_write_request_from_untrusted_origin_is_rejected(csrf_client: TestClient) -> None:
    """匹配的 CSRF Token 不能替代可信 Origin 校验。"""
    csrf_client.get("/api/v1/health/live")
    token = csrf_client.cookies["aipickstock_csrf"]
    response = csrf_client.post(
        "/api/v1/test/write",
        headers={"Origin": "https://attacker.example", "X-CSRF-Token": token},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"


def test_matching_origin_cookie_and_header_allow_write(csrf_client: TestClient) -> None:
    """同源请求携带匹配双提交令牌时应进入业务路由。"""
    csrf_client.get("/api/v1/health/live")
    token = csrf_client.cookies["aipickstock_csrf"]
    response = csrf_client.post(
        "/api/v1/test/write",
        headers={"Origin": "http://testserver", "X-CSRF-Token": token},
    )

    assert response.status_code == 200
    assert response.json() == {"saved": True}


def test_auth_rate_limit_uses_ip_and_hashed_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """认证限流应在业务逻辑前按 IP 和邮箱摘要拒绝，响应给出重试时间。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", DUMMY_DATABASE_URL)
    limiter = RejectingRateLimiter()
    application = create_app(rate_limiter=limiter)

    with TestClient(application) as client:
        client.get("/api/v1/health/live")
        token = client.cookies["aipickstock_csrf"]
        response = client.post(
            "/api/v1/auth/sessions",
            json={"email": " Owner@Example.COM ", "password": "not-logged-or-stored"},
            headers={"Origin": "http://testserver", "X-CSRF-Token": token},
        )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "17"
    assert response.json()["error"]["code"] == "AUTH_RATE_LIMITED"
    assert len(limiter.keys) == 2
    assert any(":ip:" in key for key in limiter.keys)
    assert any(":subject:" in key for key in limiter.keys)
    assert all("owner@example.com" not in key.lower() for key in limiter.keys)
