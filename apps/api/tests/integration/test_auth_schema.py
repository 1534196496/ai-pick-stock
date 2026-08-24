"""认证模块数据库结构与约束集成测试。"""

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import Connection
from sqlalchemy import CheckConstraint, UniqueConstraint

from app.core.database import Base
from app.modules.auth.models import SecurityEvent, Session, User


def test_auth_models_register_required_tables_and_constraints() -> None:
    """认证模型应注册完整表结构并避免任何明文令牌字段。"""
    assert {User.__tablename__, Session.__tablename__, SecurityEvent.__tablename__} <= set(
        Base.metadata.tables
    )

    user_columns = User.__table__.columns
    session_columns = Session.__table__.columns
    event_columns = SecurityEvent.__table__.columns

    assert "password" not in user_columns
    assert "password_hash" in user_columns
    assert "token" not in session_columns
    assert "token_hash" in session_columns
    assert "subject_hash" in event_columns

    timestamp_columns = (
        user_columns["created_at"],
        user_columns["updated_at"],
        session_columns["created_at"],
        session_columns["expires_at"],
        session_columns["revoked_at"],
        event_columns["created_at"],
    )
    assert all(column.type.timezone is True for column in timestamp_columns)

    user_unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in User.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    session_unique_columns = {
        tuple(constraint.columns.keys())
        for constraint in Session.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    check_names = {
        constraint.name
        for table in (User.__table__, Session.__table__, SecurityEvent.__table__)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }

    assert ("email_normalized",) in user_unique_columns
    assert ("token_hash",) in session_unique_columns
    assert {
        "ck_users_email_normalized",
        "ck_sessions_token_hash_sha256",
        "ck_sessions_expires_after_creation",
        "ck_security_events_subject_hash_sha256",
    } <= check_names


@pytest.fixture
def database_connection() -> Iterator[Connection[tuple[Any, ...]]]:
    """连接由测试编排器准备并已迁移到最新版本的 PostgreSQL。"""
    database_url = os.getenv("AIPICKSTOCK_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("未配置 AIPICKSTOCK_TEST_DATABASE_URL，跳过 PostgreSQL 集成测试")
    if not urlsplit(database_url).path.removeprefix("/").endswith("_test"):
        pytest.fail("集成测试只允许连接名称以 _test 结尾的数据库")

    with psycopg.connect(database_url.replace("+psycopg", ""), autocommit=True) as connection:
        connection.execute("TRUNCATE security_events, sessions, users CASCADE")
        try:
            yield connection
        finally:
            connection.execute("TRUNCATE security_events, sessions, users CASCADE")


def test_database_rejects_non_normalized_and_duplicate_email(
    database_connection: Connection[tuple[Any, ...]],
) -> None:
    """数据库应拒绝未规范化邮箱及忽略大小写后的重复主体。"""
    now = datetime.now(UTC)
    user_id = uuid4()
    database_connection.execute(
        """
        INSERT INTO users (id, email_normalized, password_hash, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (user_id, "owner@example.com", "argon2id-hash", "ACTIVE", now, now),
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        database_connection.execute(
            """
            INSERT INTO users (id, email_normalized, password_hash, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (uuid4(), " Owner@Example.com ", "argon2id-hash", "ACTIVE", now, now),
        )

    with pytest.raises(psycopg.errors.UniqueViolation):
        database_connection.execute(
            """
            INSERT INTO users (id, email_normalized, password_hash, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (uuid4(), "owner@example.com", "argon2id-hash", "ACTIVE", now, now),
        )


def test_database_accepts_only_hashed_session_tokens(
    database_connection: Connection[tuple[Any, ...]],
) -> None:
    """会话应只接受固定长度的小写 SHA-256 十六进制摘要。"""
    now = datetime.now(UTC)
    user_id = uuid4()
    database_connection.execute(
        """
        INSERT INTO users (id, email_normalized, password_hash, status, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (user_id, f"{user_id}@example.com", "argon2id-hash", "ACTIVE", now, now),
    )

    database_connection.execute(
        """
        INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (uuid4(), user_id, "a" * 64, now, now + timedelta(days=30)),
    )

    with pytest.raises(psycopg.errors.CheckViolation):
        database_connection.execute(
            """
            INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (uuid4(), user_id, "raw-session-token", now, now + timedelta(days=30)),
        )

    with pytest.raises(psycopg.errors.CheckViolation):
        database_connection.execute(
            """
            INSERT INTO sessions (id, user_id, token_hash, created_at, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (uuid4(), user_id, "b" * 64, now, now - timedelta(seconds=1)),
        )


def test_database_uses_timezone_aware_timestamps(
    database_connection: Connection[tuple[Any, ...]],
) -> None:
    """认证表的全部时间字段都应使用带时区的 PostgreSQL 类型。"""
    rows = database_connection.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name IN ('users', 'sessions', 'security_events')
          AND (column_name LIKE '%_at' OR column_name IN ('created_at', 'updated_at'))
        ORDER BY table_name, column_name
        """
    ).fetchall()

    assert rows
    assert all(row[2] == "timestamp with time zone" for row in rows)
