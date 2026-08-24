"""认证 API 的请求、成功响应与错误响应契约。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.modules.auth.enums import UserStatus


class ApiModel(BaseModel):
    """统一 API 字段使用 camelCase，同时允许服务端按 Python 字段名构造。"""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


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
