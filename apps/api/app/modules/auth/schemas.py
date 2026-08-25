"""认证 API 的请求、成功响应与错误响应契约。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.api.schemas import ApiModel
from app.modules.auth.enums import UserStatus


class RegistrationRequest(ApiModel):
    """接收待由认证服务完整校验的邮箱和密码原文。"""

    email: str
    password: str


class RegistrationResponse(ApiModel):
    """返回不含任何密码材料的新用户身份。"""

    id: UUID
    email: str
    status: UserStatus
    created_at: datetime


class LoginRequest(ApiModel):
    """接收登录邮箱和密码，并由服务统一处理错误以防账户枚举。"""

    email: str
    password: str


class SessionResponse(ApiModel):
    """返回当前会话对应且不含凭据的用户身份。"""

    id: UUID
    email: str
    status: UserStatus
    created_at: datetime


class PasswordResetRequest(ApiModel):
    """接收可能存在或不存在的注册邮箱。"""

    email: str


class PasswordResetRequestResponse(ApiModel):
    """返回不泄露邮箱存在性的统一结果。"""

    message: str


class PasswordResetConfirmRequest(ApiModel):
    """接收单次令牌与待校验的新密码。"""

    token: str
    new_password: str


class ErrorDetail(ApiModel):
    """描述可由客户端稳定匹配的单项 API 错误。"""

    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str


class ErrorResponse(ApiModel):
    """统一包装 API 错误，供后续全局异常处理中间件复用。"""

    error: ErrorDetail
