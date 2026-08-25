"""投资账户 Repository 与注册默认账户的 PostgreSQL 集成测试。"""

import os
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService
from app.modules.portfolios.repository import InvestmentAccountRepository

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    """数据库测试统一使用 asyncio 后端。"""
    return "asyncio"


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """连接隔离 PostgreSQL 并按外键顺序清理测试数据。"""
    database_url = os.getenv("AIPICKSTOCK_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("未配置 AIPICKSTOCK_TEST_DATABASE_URL，跳过 PostgreSQL 集成测试")
    if not urlsplit(database_url).path.removeprefix("/").endswith("_test"):
        pytest.fail("集成测试只允许连接名称以 _test 结尾的数据库")
    engine = create_async_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    cleanup = text(
        "TRUNCATE investment_accounts, password_reset_tokens, "
        "security_events, sessions, users CASCADE"
    )
    async with engine.begin() as connection:
        await connection.execute(cleanup)
    try:
        yield factory
    finally:
        async with engine.begin() as connection:
            await connection.execute(cleanup)
        await engine.dispose()


async def test_registration_creates_default_account_in_same_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """注册服务成功后必须立即存在默认人民币账户。"""
    async with session_factory.begin() as session:
        auth_repository = AuthRepository(session)
        account_repository = InvestmentAccountRepository(session)
        identity = await AuthService(
            auth_repository,
            account_initializer=account_repository,
        ).register(
            email="owner@example.com",
            password="correct-register-password",
            request_id="req_account_default",
        )
        accounts, total = await account_repository.list_for_user(user_id=identity.id)
    assert total == 1
    assert accounts[0].name == "默认账户"
    assert accounts[0].base_currency == "CNY"


async def test_account_names_are_unique_per_user_and_reads_are_isolated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """同用户重复名称失败，不同用户可同名且不能跨用户读取。"""
    async with session_factory.begin() as session:
        auth_repository = AuthRepository(session)
        first = await auth_repository.create_user(
            email_normalized="first@example.com",
            password_hash="$argon2id$first",
        )
        second = await auth_repository.create_user(
            email_normalized="second@example.com",
            password_hash="$argon2id$second",
        )
        repository = InvestmentAccountRepository(session)
        first_account = await repository.create_for_user(
            user_id=first.identity.id,
            name="证券账户",
            sort_order=1,
        )
        duplicate = await repository.create_for_user(
            user_id=first.identity.id,
            name="证券账户",
            sort_order=2,
        )
        second_account = await repository.create_for_user(
            user_id=second.identity.id,
            name="证券账户",
            sort_order=1,
        )
        cross_user = await repository.get_for_user(
            user_id=second.identity.id,
            account_id=first_account.id,
        )
    assert first_account is not None
    assert duplicate is None
    assert second_account is not None
    assert cross_user is None
