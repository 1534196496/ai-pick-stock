"""认证模块的 Argon2id 密码摘要与验证策略。"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.profiles import RFC_9106_LOW_MEMORY

_DEFAULT_PASSWORD_HASHER = PasswordHasher.from_parameters(RFC_9106_LOW_MEMORY)


class PasswordManager:
    """使用固定 RFC 9106 Argon2id 参数封装密码摘要生命周期。"""

    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        """允许测试注入参数，同时让生产默认策略只初始化一次。"""
        self._hasher = hasher or _DEFAULT_PASSWORD_HASHER

    def hash(self, password: str) -> str:
        """使用独立随机盐生成不可逆 Argon2id 密码摘要。"""
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        """验证密码并将不匹配或损坏摘要统一处理为失败。"""
        try:
            return self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        """判断成功登录后是否应升级旧版 Argon2 参数。"""
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return False
