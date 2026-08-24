"""统一 API 错误与请求 ID 契约测试。"""

from collections.abc import Iterator

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.errors import ApiError
from app.main import create_app

DUMMY_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/app"


class ExamplePayload(BaseModel):
    """为边界校验测试提供一个必填字符串字段。"""

    name: str


@pytest.fixture
def error_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """创建包含预期异常、校验异常和未知异常测试路由的客户端。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", DUMMY_DATABASE_URL)
    application = create_app()

    @application.get("/api/v1/test/expected-error")
    async def expected_error() -> None:
        """抛出允许公开的测试业务错误。"""
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="EXAMPLE_CONFLICT",
            message="示例资源冲突",
            details={"field": "name"},
        )

    @application.get("/api/v1/test/unexpected-error")
    async def unexpected_error() -> None:
        """抛出包含敏感文本的未知异常以验证响应脱敏。"""
        raise RuntimeError("database password=do-not-leak")

    @application.post("/api/v1/test/validation")
    async def validate_payload(payload: ExamplePayload) -> ExamplePayload:
        """回显已通过边界校验的测试载荷。"""
        return payload

    with TestClient(application, raise_server_exceptions=False) as client:
        yield client


def test_expected_error_has_stable_envelope_and_request_id(error_client: TestClient) -> None:
    """预期错误应保留业务码、细节和同一个请求追踪标识。"""
    response = error_client.get(
        "/api/v1/test/expected-error",
        headers={"X-Request-ID": "req_expected_error"},
    )

    assert response.status_code == 409
    assert response.headers["X-Request-ID"] == "req_expected_error"
    assert response.json() == {
        "error": {
            "code": "EXAMPLE_CONFLICT",
            "message": "示例资源冲突",
            "details": {"field": "name"},
            "requestId": "req_expected_error",
        }
    }


def test_framework_404_uses_same_error_envelope(error_client: TestClient) -> None:
    """不存在路由也应返回统一结构而不是框架默认 detail。"""
    response = error_client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "请求的资源不存在",
            "requestId": response.headers["X-Request-ID"],
        }
    }


def test_validation_error_does_not_echo_invalid_input(error_client: TestClient) -> None:
    """请求校验错误只公开字段和类型，不回显用户原始输入。"""
    error_client.get("/api/v1/health/live")
    token = error_client.cookies["aipickstock_csrf"]
    response = error_client.post(
        "/api/v1/test/validation",
        json={"name": ["secret-input"]},
        headers={"Origin": "http://testserver", "X-CSRF-Token": token},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"] == {
        "fields": [{"field": "name", "type": "string_type"}]
    }
    assert "secret-input" not in response.text


def test_unexpected_error_never_leaks_internal_exception(error_client: TestClient) -> None:
    """未知异常应返回固定 500 文案且不包含异常消息。"""
    response = error_client.get("/api/v1/test/unexpected-error")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "服务器暂时无法处理请求",
            "requestId": response.headers["X-Request-ID"],
        }
    }
    assert "password" not in response.text
    assert "do-not-leak" not in response.text


def test_invalid_request_id_is_replaced_with_server_value(error_client: TestClient) -> None:
    """含控制字符或过长的请求标识不得原样进入响应。"""
    response = error_client.get(
        "/api/v1/health/live",
        headers={"X-Request-ID": "x" * 65},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"].startswith("req_")
    assert response.headers["X-Request-ID"] != "x" * 65
