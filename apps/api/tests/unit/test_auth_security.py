"""Argon2id 密码安全原语单元测试。"""

from argon2 import PasswordHasher

from app.modules.auth.security import PasswordManager


def test_same_password_produces_distinct_argon2id_hashes() -> None:
    """随机盐应让同一密码每次产生不同的 Argon2id 摘要。"""
    manager = PasswordManager()

    first = manager.hash("a-correct-long-password")
    second = manager.hash("a-correct-long-password")

    assert first != second
    assert first.startswith("$argon2id$")
    assert second.startswith("$argon2id$")
    assert manager.verify(first, "a-correct-long-password") is True


def test_wrong_password_and_malformed_hash_are_rejected() -> None:
    """密码不匹配或数据库摘要损坏时应统一返回验证失败。"""
    manager = PasswordManager()
    password_hash = manager.hash("a-correct-long-password")

    assert manager.verify(password_hash, "another-long-password") is False
    assert manager.verify("not-an-argon2-hash", "a-correct-long-password") is False


def test_current_hash_does_not_need_rehash() -> None:
    """使用当前参数生成的摘要不应触发无意义的重复更新。"""
    manager = PasswordManager()
    password_hash = manager.hash("a-correct-long-password")

    assert manager.needs_rehash(password_hash) is False


def test_legacy_parameters_are_detected_for_rehash() -> None:
    """参数低于当前策略的旧摘要应在成功登录后安排升级。"""
    weak_hasher = PasswordHasher(time_cost=1, memory_cost=8_192, parallelism=1)
    legacy_hash = weak_hasher.hash("a-correct-long-password")

    assert PasswordManager().needs_rehash(legacy_hash) is True
