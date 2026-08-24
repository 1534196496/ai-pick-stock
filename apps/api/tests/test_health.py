"""API 健康检查与配置边界测试。"""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.main import create_app

DUMMY_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/app"


def test_live_returns_fixed_healthy_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """进程正常时应返回稳定且可供编排系统识别的响应。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", DUMMY_DATABASE_URL)

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_settings_require_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺少数据库地址时应在启动阶段快速失败。"""
    monkeypatch.delenv("AIPICKSTOCK_DATABASE_URL", raising=False)

    with pytest.raises(ValidationError), TestClient(create_app()):
        pass


def test_settings_reject_non_psycopg_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """数据库地址必须显式使用 PostgreSQL 的 psycopg 3 驱动。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", "sqlite:///local.db")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_ready_reports_available_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """数据库探测成功时就绪接口应返回稳定成功契约。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", DUMMY_DATABASE_URL)

    async def database_is_ready(_: AsyncEngine) -> bool:
        """为接口测试提供不访问网络的可用数据库探测结果。"""
        return True

    with TestClient(create_app(database_probe=database_is_ready)) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok"}}


def test_ready_reports_unavailable_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """数据库不可用时就绪接口应返回 503 且不泄露连接细节。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", DUMMY_DATABASE_URL)

    async def database_is_unavailable(_: AsyncEngine) -> bool:
        """为接口测试提供不访问网络的不可用数据库探测结果。"""
        return False

    with TestClient(create_app(database_probe=database_is_unavailable)) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"database": "unavailable"},
    }
