"""资产、价格与同步任务数据库结构测试。"""

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection


@pytest.fixture
def database_connection() -> Iterator[Connection[tuple[Any, ...]]]:
    """连接名称以 _test 结尾且已迁移的 PostgreSQL。"""
    database_url = os.getenv("AIPICKSTOCK_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("未配置 AIPICKSTOCK_TEST_DATABASE_URL，跳过 PostgreSQL 集成测试")
    if not urlsplit(database_url).path.removeprefix("/").endswith("_test"):
        pytest.fail("集成测试只允许连接名称以 _test 结尾的数据库")
    with psycopg.connect(database_url.replace("+psycopg", ""), autocommit=True) as connection:
        connection.execute("TRUNCATE instrument_prices, instruments CASCADE")
        try:
            yield connection
        finally:
            connection.execute("TRUNCATE instrument_prices, instruments CASCADE")


def insert_instrument(
    connection: Connection[tuple[Any, ...]],
    *,
    ticker: str,
    asset_type: str = "STOCK",
    exchange: str = "SSE",
) -> str:
    """插入固定来源资产并返回 UUID 字符串。"""
    instrument_id = str(uuid4())
    connection.execute(
        "INSERT INTO instruments "
        "(id,asset_type,market,exchange,ticker,name,currency,source) "
        "VALUES (%s,%s,'CN',%s,%s,%s,'CNY','fixture')",
        (instrument_id, asset_type, exchange, ticker, f"测试{ticker}"),
    )
    return instrument_id


def test_instrument_identity_is_jointly_unique_without_six_digit_assumption(
    database_connection: Connection[tuple[Any, ...]],
) -> None:
    """联合身份唯一，同时允许非六位未来代码。"""
    insert_instrument(database_connection, ticker="LONG-TICKER-001")
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_instrument(database_connection, ticker="LONG-TICKER-001")
    insert_instrument(
        database_connection, ticker="LONG-TICKER-001", asset_type="FUND", exchange="FUND_CN"
    )


def test_price_types_coexist_and_invalid_financial_values_are_rejected(
    database_connection: Connection[tuple[Any, ...]],
) -> None:
    """官方与估算净值可并存，非正数和缺业务时间被拒绝。"""
    instrument_id = insert_instrument(
        database_connection, ticker="000001", asset_type="FUND", exchange="FUND_CN"
    )
    now = datetime.now(UTC)
    for price_type, value in (
        ("FUND_OFFICIAL_NAV", Decimal("1.23456789")),
        ("FUND_ESTIMATED_NAV", Decimal("1.24000000")),
    ):
        database_connection.execute(
            "INSERT INTO instrument_prices "
            "(instrument_id,price_type,value,as_of_date,fetched_at,source) "
            "VALUES (%s,%s,%s,%s,%s,'fixture')",
            (instrument_id, price_type, value, date(2026, 8, 24), now),
        )
    rows = database_connection.execute(
        "SELECT price_type,value::text FROM instrument_prices ORDER BY price_type"
    ).fetchall()
    assert {row[0] for row in rows} == {"FUND_OFFICIAL_NAV", "FUND_ESTIMATED_NAV"}
    with pytest.raises(psycopg.errors.CheckViolation):
        database_connection.execute(
            "INSERT INTO instrument_prices "
            "(instrument_id,price_type,value,as_of_date,fetched_at,source) "
            "VALUES (%s,'FUND_OFFICIAL_NAV',0,%s,%s,'bad')",
            (instrument_id, date(2026, 8, 23), now),
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        database_connection.execute(
            "INSERT INTO instrument_prices "
            "(instrument_id,price_type,value,fetched_at,source) "
            "VALUES (%s,'FUND_OFFICIAL_NAV',1,%s,'bad')",
            (instrument_id, now),
        )
