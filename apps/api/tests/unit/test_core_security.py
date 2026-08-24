"""通用随机令牌、摘要与 Cookie 策略单元测试。"""

import base64
from datetime import timedelta

import pytest

from app.core.security import create_session_cookie_policy, generate_opaque_token, hash_opaque_token


def test_opaque_tokens_are_unique_and_contain_256_bits_of_entropy() -> None:
    """每个不透明令牌都应独立生成并携带至少 32 字节随机数据。"""
    first = generate_opaque_token()
    second = generate_opaque_token()

    decoded = base64.urlsafe_b64decode(first + "=" * (-len(first) % 4))

    assert first != second
    assert len(decoded) == 32


def test_token_hash_is_deterministic_without_retaining_original_value() -> None:
    """持久化摘要应可查询匹配，但不能包含令牌原文。"""
    token = generate_opaque_token()

    digest = hash_opaque_token(token)

    assert digest == hash_opaque_token(token)
    assert len(digest) == 64
    assert token not in digest
    assert set(digest) <= set("0123456789abcdef")


def test_token_hash_rejects_empty_value() -> None:
    """空令牌不应产生一个看似有效的数据库查询摘要。"""
    with pytest.raises(ValueError, match="令牌不能为空"):
        hash_opaque_token("")


def test_production_cookie_is_host_bound_and_transport_secure() -> None:
    """生产会话 Cookie 应启用浏览器可提供的关键安全属性。"""
    policy = create_session_cookie_policy(
        production=True,
        lifetime=timedelta(days=30),
    )

    assert policy.name == "__Host-aipickstock_session"
    assert policy.response_options() == {
        "max_age": 2_592_000,
        "secure": True,
        "httponly": True,
        "samesite": "lax",
        "path": "/",
    }


def test_development_cookie_supports_local_http_without_weakening_other_flags() -> None:
    """本地 HTTP 仅关闭 Secure，仍保持 HttpOnly、SameSite 与根路径限制。"""
    policy = create_session_cookie_policy(
        production=False,
        lifetime=timedelta(hours=1),
    )

    assert policy.name == "aipickstock_session"
    assert policy.response_options() == {
        "max_age": 3_600,
        "secure": False,
        "httponly": True,
        "samesite": "lax",
        "path": "/",
    }


def test_cookie_lifetime_must_be_positive() -> None:
    """无效生命周期应在写响应前被拒绝。"""
    with pytest.raises(ValueError, match="Cookie 有效期必须大于 0 秒"):
        create_session_cookie_policy(production=True, lifetime=timedelta(0))
