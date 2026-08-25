"""统一错误、请求标识和认证限流 API 测试。"""

from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.middleware import AuthenticationRateLimiter, RateLimitDecision
from app.main import create_app

DUMMY_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/app"
SECURE_HEADERS = {
    "Origin": "http://testserver",
    "X-CSRF-Token": "csrf-test-token-1234567890",
}


class RejectingRateLimiter(AuthenticationRateLimiter):
    """模拟认证接口已经达到请求上限。"""

    async def check(self, *, scope: str, client_key: str) -> RateLimitDecision | None:
        """对任意认证请求返回固定重试时间。"""
        return RateLimitDecision(retry_after_seconds=17)


@pytest.fixture
def error_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """创建包含测试异常端点的 API 客户端。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", DUMMY_DATABASE_URL)
    application = create_app()
    router = APIRouter()

    @router.get("/test/internal-error")
    async def internal_error() -> None:
        """触发未处理异常以验证对外脱敏。"""
        raise RuntimeError("database password must never leak")

    application.include_router(router, prefix="/api/v1")
    with TestClient(application, raise_server_exceptions=False) as client:
        yield client


def test_request_id_is_echoed_and_added_to_validation_error(
    error_client: TestClient,
) -> None:
    """合法请求 ID 应贯穿响应头和稳定错误体。"""
    response = error_client.post(
        "/api/v1/auth/sessions",
        json={},
        headers={**SECURE_HEADERS, "X-Request-ID": "req_client_123"},
    )

    assert response.status_code == 422
    assert response.headers["X-Request-ID"] == "req_client_123"
    assert response.json() == {
        "error": {
            "code": "REQUEST_VALIDATION_FAILED",
            "message": "请求参数不符合要求",
            "details": {"fields": ["body.email", "body.password"]},
            "requestId": "req_client_123",
        }
    }


def test_invalid_request_id_is_replaced(error_client: TestClient) -> None:
    """含控制字符或过长的客户端标识不得进入响应和日志上下文。"""
    response = error_client.get(
        "/api/v1/health/live",
        headers={"X-Request-ID": "x" * 65},
    )

    request_id = response.headers["X-Request-ID"]
    assert response.status_code == 200
    assert request_id.startswith("req_")
    assert len(request_id) == 36


def test_internal_exception_does_not_leak_details(error_client: TestClient) -> None:
    """未处理异常只返回通用错误，不暴露内部消息。"""
    response = error_client.get(
        "/api/v1/test/internal-error",
        headers={"X-Request-ID": "req_internal_error"},
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "服务器暂时无法处理请求",
            "requestId": "req_internal_error",
        }
    }
    assert "database password" not in response.text


def test_authentication_rate_limiter_returns_stable_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """认证限流实现可以替换，并通过统一错误契约返回重试时间。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", DUMMY_DATABASE_URL)
    application = create_app(authentication_rate_limiter=RejectingRateLimiter())

    with TestClient(application) as client:
        response = client.post(
            "/api/v1/auth/sessions",
            json={"email": "owner@example.com", "password": "a-correct-long-password"},
            headers=SECURE_HEADERS,
        )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "17"
    assert response.json()["error"]["code"] == "AUTH_RATE_LIMITED"
    assert response.json()["error"]["requestId"].startswith("req_")
