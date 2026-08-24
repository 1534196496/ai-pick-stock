"""跨模块复用的随机令牌、不可逆摘要与 Cookie 策略。"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal, TypedDict

TOKEN_ENTROPY_BYTES = 32


class SessionCookieOptions(TypedDict):
    """限定写入会话 Cookie 时允许传递的响应参数。"""

    max_age: int
    secure: bool
    httponly: bool
    samesite: Literal["lax"]
    path: Literal["/"]


@dataclass(frozen=True, slots=True)
class SessionCookiePolicy:
    """封装环境相关的会话 Cookie 名称与安全属性。"""

    name: str
    secure: bool
    max_age_seconds: int

    def response_options(self) -> SessionCookieOptions:
        """生成可直接传给 FastAPI 响应对象的安全 Cookie 参数。"""
        return {
            "max_age": self.max_age_seconds,
            "secure": self.secure,
            "httponly": True,
            "samesite": "lax",
            "path": "/",
        }


def generate_opaque_token() -> str:
    """使用系统级安全随机源生成 256 位 URL 安全令牌。"""
    return secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def hash_opaque_token(token: str) -> str:
    """将高熵令牌转换为数据库可查询但不可逆的 SHA-256 摘要。"""
    if not token:
        raise ValueError("令牌不能为空")
    return hash_sensitive_value(token)


def hash_sensitive_value(value: str) -> str:
    """将非空敏感主体转换为可关联审计事件的不可逆摘要。"""
    if not value:
        raise ValueError("敏感值不能为空")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_session_cookie_policy(
    *,
    production: bool,
    lifetime: timedelta,
) -> SessionCookiePolicy:
    """按运行环境创建 Host 绑定的生产策略或本地 HTTP 开发策略。"""
    max_age_seconds = int(lifetime.total_seconds())
    if max_age_seconds <= 0:
        raise ValueError("Cookie 有效期必须大于 0 秒")

    return SessionCookiePolicy(
        name="__Host-aipickstock_session" if production else "aipickstock_session",
        secure=production,
        max_age_seconds=max_age_seconds,
    )
