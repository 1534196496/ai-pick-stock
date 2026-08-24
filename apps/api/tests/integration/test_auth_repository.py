"""认证 Repository 的真实 PostgreSQL 集成测试。"""

import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.auth.domain import SecurityEventRecord, SessionPrincipal, UserCredentials
from app.modules.auth.enums import SecurityEventType, UserStatus
from app.modules.auth.repository import AuthRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    """认证数据库测试统一使用应用生产路径对应的 asyncio 后端。"""
    return "asyncio"


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """创建隔离的异步会话工厂，并保护非测试数据库不被清理。"""
    database_url = os.getenv("AIPICKSTOCK_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("未配置 AIPICKSTOCK_TEST_DATABASE_URL，跳过 PostgreSQL 集成测试")
    if not urlsplit(database_url).path.removeprefix("/").endswith("_test"):
        pytest.fail("集成测试只允许连接名称以 _test 结尾的数据库")

    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE security_events, sessions, users CASCADE"))
    try:
        yield factory
    finally:
        async with engine.begin() as connection:
            await connection.execute(text("TRUNCATE security_events, sessions, users CASCADE"))
        await engine.dispose()


async def test_create_and_find_user_returns_domain_record(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """新增和查询用户都应返回领域记录而不是 ORM 实例。"""
    async with session_factory.begin() as session:
        repository = AuthRepository(session)
        created = await repository.create_user(
            email_normalized="owner@example.com",
            password_hash="$argon2id$example",
        )

    async with session_factory() as session:
        found = await AuthRepository(session).get_credentials_by_email("owner@example.com")

    assert isinstance(created, UserCredentials)
    assert found == created
    assert found.identity.email_normalized == "owner@example.com"
    assert found.identity.status is UserStatus.ACTIVE
    assert not hasattr(found, "__table__")


async def test_active_session_lookup_and_revocation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """仅有效且未撤销的会话可解析为当前用户主体。"""
    now = datetime.now(UTC)
    async with session_factory.begin() as session:
        repository = AuthRepository(session)
        credentials = await repository.create_user(
            email_normalized="session@example.com",
            password_hash="$argon2id$example",
        )
        created_session = await repository.create_session(
            user_id=credentials.identity.id,
            token_hash="a" * 64,
            expires_at=now + timedelta(days=30),
        )

    async with session_factory.begin() as session:
        repository = AuthRepository(session)
        principal = await repository.get_session_principal(token_hash="a" * 64, now=now)
        revoked = await repository.revoke_session(
            session_id=created_session.id,
            revoked_at=now + timedelta(seconds=1),
        )

    async with session_factory() as session:
        after_revocation = await AuthRepository(session).get_session_principal(
            token_hash="a" * 64,
            now=now + timedelta(seconds=2),
        )

    assert isinstance(principal, SessionPrincipal)
    assert principal.session == created_session
    assert principal.identity.id == credentials.identity.id
    assert revoked is True
    assert after_revocation is None


async def test_expired_and_disabled_user_sessions_are_not_returned(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """过期会话以及已禁用用户的会话都不能建立认证主体。"""
    now = datetime.now(UTC)
    async with session_factory.begin() as session:
        repository = AuthRepository(session)
        expired_user = await repository.create_user(
            email_normalized="expired@example.com",
            password_hash="$argon2id$example",
        )
        disabled_user = await repository.create_user(
            email_normalized="disabled@example.com",
            password_hash="$argon2id$example",
        )
        await repository.create_session(
            user_id=expired_user.identity.id,
            token_hash="b" * 64,
            expires_at=now - timedelta(seconds=1),
            created_at=now - timedelta(days=1),
        )
        await repository.create_session(
            user_id=disabled_user.identity.id,
            token_hash="c" * 64,
            expires_at=now + timedelta(days=1),
        )
        await repository.set_user_status(
            user_id=disabled_user.identity.id,
            status=UserStatus.DISABLED,
            changed_at=now,
        )

    async with session_factory() as session:
        repository = AuthRepository(session)
        expired = await repository.get_session_principal(token_hash="b" * 64, now=now)
        disabled = await repository.get_session_principal(token_hash="c" * 64, now=now)

    assert expired is None
    assert disabled is None


async def test_password_update_bulk_revocation_and_security_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """密码变更、会话批量撤销与审计事件应能纳入同一事务。"""
    now = datetime.now(UTC)
    async with session_factory.begin() as session:
        repository = AuthRepository(session)
        credentials = await repository.create_user(
            email_normalized="security@example.com",
            password_hash="$argon2id$old",
        )
        await repository.create_session(
            user_id=credentials.identity.id,
            token_hash="d" * 64,
            expires_at=now + timedelta(days=1),
            created_at=now,
        )
        updated = await repository.update_password_hash(
            user_id=credentials.identity.id,
            password_hash="$argon2id$new",
            changed_at=now,
        )
        revoked_count = await repository.revoke_user_sessions(
            user_id=credentials.identity.id,
            revoked_at=now,
        )
        event = await repository.record_security_event(
            user_id=credentials.identity.id,
            event_type=SecurityEventType.PASSWORD_RESET_SUCCEEDED,
            subject_hash="e" * 64,
            request_id="req_auth_repository",
            created_at=now,
        )

    assert isinstance(updated, UserCredentials)
    assert updated.password_hash == "$argon2id$new"
    assert revoked_count == 1
    assert isinstance(event, SecurityEventRecord)
    assert event.event_type is SecurityEventType.PASSWORD_RESET_SUCCEEDED
