"""认证模块 HTTP 路由。"""

from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.dependencies import (
    get_auth_repository,
    get_optional_session_principal,
    get_session_cookie_policy,
)
from app.core.errors import ErrorResponse, create_error_response, get_request_id
from app.modules.auth.domain import SessionPrincipal, UserIdentity
from app.modules.auth.repository import AuthRepository
from app.modules.auth.schemas import (
    LoginRequest,
    RegistrationRequest,
    RegistrationResponse,
    SessionResponse,
)
from app.modules.auth.service import AuthenticationError, AuthService, RegistrationError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/registrations",
    status_code=status.HTTP_201_CREATED,
    response_model=RegistrationResponse,
    responses={
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse},
    },
)
async def register(
    payload: RegistrationRequest,
    request: Request,
    repository: Annotated[AuthRepository, Depends(get_auth_repository)],
) -> RegistrationResponse | JSONResponse:
    """创建邮箱密码用户，并保证响应不包含密码或摘要。"""
    service = AuthService(repository)
    try:
        identity = await service.register(
            email=payload.email,
            password=payload.password,
            request_id=_resolve_request_id(request),
        )
    except RegistrationError as error:
        status_code = (
            status.HTTP_409_CONFLICT
            if error.code == "EMAIL_ALREADY_REGISTERED"
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        return create_error_response(
            status_code=status_code,
            code=error.code,
            message=error.message,
            details={"field": error.field},
            request_id=get_request_id(request),
        )

    return RegistrationResponse(
        id=identity.id,
        email=identity.email_normalized,
        status=identity.status,
        created_at=identity.created_at,
    )


@router.post(
    "/sessions",
    response_model=SessionResponse,
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    repository: Annotated[AuthRepository, Depends(get_auth_repository)],
) -> SessionResponse | JSONResponse:
    """验证邮箱密码、轮换旧会话并写入环境匹配的安全 Cookie。"""
    policy = get_session_cookie_policy(request)
    service = AuthService(repository)
    try:
        result = await service.login(
            email=payload.email,
            password=payload.password,
            current_token=request.cookies.get(policy.name),
            request_id=_resolve_request_id(request),
            lifetime=timedelta(seconds=policy.max_age_seconds),
        )
    except AuthenticationError as error:
        return _error_response(
            request=request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=error.code,
            message=error.message,
        )

    response.set_cookie(
        key=policy.name,
        value=result.token,
        **policy.response_options(),
    )
    return _session_response(result.identity)


@router.get(
    "/session",
    response_model=SessionResponse,
    responses={status.HTTP_401_UNAUTHORIZED: {"model": ErrorResponse}},
)
async def current_session(
    request: Request,
    principal: Annotated[SessionPrincipal | None, Depends(get_optional_session_principal)],
) -> SessionResponse | JSONResponse:
    """从服务端不透明会话恢复当前用户身份。"""
    if principal is None:
        return _error_response(
            request=request,
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTHENTICATION_REQUIRED",
            message="请先登录",
        )
    return _session_response(principal.identity)


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    repository: Annotated[AuthRepository, Depends(get_auth_repository)],
) -> Response:
    """幂等撤销当前会话并清除浏览器 Cookie。"""
    policy = get_session_cookie_policy(request)
    await AuthService(repository).logout(
        token=request.cookies.get(policy.name),
        request_id=_resolve_request_id(request),
    )
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        key=policy.name,
        path="/",
        secure=policy.secure,
        httponly=True,
        samesite="lax",
    )
    return response


def _resolve_request_id(request: Request) -> str:
    """复用请求上下文中已经校验的追踪标识写入安全审计。"""
    return get_request_id(request)


def _session_response(identity: UserIdentity) -> SessionResponse:
    """把已验证身份转换为不含认证材料的会话响应。"""
    return SessionResponse(
        id=identity.id,
        email=identity.email_normalized,
        status=identity.status,
        created_at=identity.created_at,
    )


def _error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    """创建不含内部异常细节的统一认证错误响应。"""
    return create_error_response(
        status_code=status_code,
        code=code,
        message=message,
        request_id=get_request_id(request),
    )
