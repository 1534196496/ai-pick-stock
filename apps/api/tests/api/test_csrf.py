"""状态变更请求的 Origin 与 CSRF 防护测试。"""

from collections.abc import Iterator

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.main import create_app

DUMMY_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/app"
VALID_BODY = {"email": "owner@example.com", "password": "a-correct-long-password"}


@pytest.fixture
def csrf_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """创建不访问真实数据库即可验证请求前置防护的客户端。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", DUMMY_DATABASE_URL)
    application = create_app()
    router = APIRouter()

    @router.post("/test/mutation")
    async def mutation() -> dict[str, str]:
        """提供不访问数据库的状态变更测试端点。"""
        return {"status": "accepted"}

    application.include_router(router, prefix="/api/v1")
    with TestClient(application) as client:
        yield client


def test_state_changing_request_without_csrf_header_is_rejected(
    csrf_client: TestClient,
) -> None:
    """即使 Origin 同源，缺少自定义 CSRF 请求头也必须拒绝。"""
    response = csrf_client.post(
        "/api/v1/auth/sessions",
        json=VALID_BODY,
        headers={"Origin": "http://testserver"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_TOKEN_REQUIRED"


def test_state_changing_request_without_origin_is_rejected(csrf_client: TestClient) -> None:
    """缺少 Origin 的浏览器状态变更请求不得绕过同源校验。"""
    response = csrf_client.post(
        "/api/v1/auth/sessions",
        json=VALID_BODY,
        headers={"X-CSRF-Token": "csrf-test-token-1234567890"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_REQUIRED"


def test_cross_origin_state_changing_request_is_rejected(csrf_client: TestClient) -> None:
    """攻击者站点即使能构造头值也不能通过服务端 Origin 校验。"""
    response = csrf_client.post(
        "/api/v1/auth/sessions",
        json=VALID_BODY,
        headers={
            "Origin": "https://attacker.example",
            "X-CSRF-Token": "csrf-test-token-1234567890",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"


def test_same_origin_request_with_csrf_header_reaches_endpoint(
    csrf_client: TestClient,
) -> None:
    """同源且带合格随机头的请求应通过安全中间件进入业务端点。"""
    response = csrf_client.post(
        "/api/v1/test/mutation",
        json=VALID_BODY,
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": "csrf-test-token-1234567890",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}


def test_safe_request_does_not_require_csrf_headers(csrf_client: TestClient) -> None:
    """存活检查等安全读取请求无需携带 Origin 或 CSRF 请求头。"""
    response = csrf_client.get("/api/v1/health/live")

    assert response.status_code == 200
