"""密码重置 Repository 的真实 PostgreSQL 并发边界测试。"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.auth.repository import AuthRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    """数据库测试统一使用 asyncio 后端。"""
    return "asyncio"


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """连接名称以 _test 结尾的隔离 PostgreSQL，并清理认证数据。"""
    database_url = os.getenv("AIPICKSTOCK_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("未配置 AIPICKSTOCK_TEST_DATABASE_URL，跳过 PostgreSQL 集成测试")
    if not urlsplit(database_url).path.removeprefix("/").endswith("_test"):
        pytest.fail("集成测试只允许连接名称以 _test 结尾的数据库")
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE password_reset_tokens, security_events, sessions, users CASCADE")
        )
    try:
        yield factory
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                text("TRUNCATE password_reset_tokens, security_events, sessions, users CASCADE")
            )
        await engine.dispose()


async def test_password_reset_token_can_only_be_consumed_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """相同摘要的连续消费只能有一次返回记录。"""
    now = datetime.now(UTC)
    async with session_factory.begin() as session:
        repository = AuthRepository(session)
        user = await repository.create_user(
            email_normalized="reset@example.com", password_hash="$argon2id$example"
        )
        await repository.create_password_reset_token(
            user_id=user.identity.id,
            token_hash="f" * 64,
            created_at=now,
            expires_at=now + timedelta(minutes=30),
        )
        first = await repository.consume_password_reset_token(
            token_hash="f" * 64, used_at=now + timedelta(seconds=1)
        )
        second = await repository.consume_password_reset_token(
            token_hash="f" * 64, used_at=now + timedelta(seconds=2)
        )
    assert first is not None
    assert second is None
    assert not hasattr(first, "token_hash")
