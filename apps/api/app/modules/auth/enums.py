"""认证模块跨层共享的稳定枚举。"""

from enum import StrEnum


class UserStatus(StrEnum):
    """表示用户是否可以创建新会话。"""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class SecurityEventType(StrEnum):
    """表示需要审计但不得记录敏感原文的认证事件。"""

    REGISTRATION_SUCCEEDED = "REGISTRATION_SUCCEEDED"
    LOGIN_SUCCEEDED = "LOGIN_SUCCEEDED"
    LOGIN_FAILED = "LOGIN_FAILED"
    SESSION_REVOKED = "SESSION_REVOKED"
    PASSWORD_RESET_REQUESTED = "PASSWORD_RESET_REQUESTED"
    PASSWORD_RESET_SUCCEEDED = "PASSWORD_RESET_SUCCEEDED"
