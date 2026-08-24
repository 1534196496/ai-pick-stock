"""后台任务进程入口测试。"""

from unittest.mock import Mock

import pytest

from app.jobs.__main__ import run_worker


def test_worker_validates_configuration_before_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Worker 应先完成必需配置校验，再进入等待调度任务的状态。"""
    monkeypatch.setenv(
        "AIPICKSTOCK_DATABASE_URL",
        "postgresql+psycopg://app:app@localhost:5432/app",
    )
    wait = Mock()

    run_worker(wait=wait)

    wait.assert_called_once_with()
