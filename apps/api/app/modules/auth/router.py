"""认证模块 HTTP 路由。"""

import logging
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.dependencies import (
    get_auth_repository,
    get_optional_session_principal,
    get_password_reset_mailer,
    get_session_cookie_policy,
    get_watchlist_repository,
)
from app.core.errors import ApiError, request_id_from
from app.modules.auth.domain import SessionPrincipal, UserIdentity
from app.modules.auth.mailer import PasswordResetMailer
from app.modules.auth.repository import AuthRepository
from app.modules.auth.reset_service import PasswordResetError, PasswordResetService
from app.modules.auth.schemas import (
    ErrorResponse,
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    RegistrationRequest,
    RegistrationResponse,
    SessionResponse,
)
from app.modules.auth.service import AuthenticationError, AuthService, RegistrationError
from app.modules.watchlists.repository import WatchlistRepository

logger = logging.getLogger(__name__)

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
    watchlist_repository: Annotated[
        WatchlistRepository,
        Depends(get_watchlist_repository),
    ],
) -> RegistrationResponse:
    """创建邮箱密码用户，并保证响应不包含密码或摘要。"""
    service = AuthService(
        repository,
        watchlist_initializer=watchlist_repository,
    )
    try:
        identity = await service.register(
            email=payload.email,
            password=payload.password,
            request_id=request_id_from(request),
        )
    except RegistrationError as error:
        status_code = (
            status.HTTP_409_CONFLICT
            if error.code == "EMAIL_ALREADY_REGISTERED"
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise ApiError(
            status_code=status_code,
            code=error.code,
            message=error.message,
            details={"field": error.field},
        ) from error

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
) -> SessionResponse:
    """验证邮箱密码、轮换旧会话并写入环境匹配的安全 Cookie。"""
    policy = get_session_cookie_policy(request)
    service = AuthService(repository)
    try:
        result = await service.login(
            email=payload.email,
            password=payload.password,
            current_token=request.cookies.get(policy.name),
            request_id=request_id_from(request),
            lifetime=timedelta(seconds=policy.max_age_seconds),
        )
    except AuthenticationError as error:
        raise ApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code=error.code,
            message=error.message,
        ) from error

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
    principal: Annotated[SessionPrincipal | None, Depends(get_optional_session_principal)],
) -> SessionResponse:
    """从服务端不透明会话恢复当前用户身份。"""
    if principal is None:
        raise ApiError(
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
        request_id=request_id_from(request),
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


@router.post(
    "/password-reset-requests",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=PasswordResetRequestResponse,
)
async def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    repository: Annotated[AuthRepository, Depends(get_auth_repository)],
    mailer: Annotated[PasswordResetMailer | None, Depends(get_password_reset_mailer)],
) -> PasswordResetRequestResponse:
    """统一接受重置请求，存在账户时通过适配器发送单次链接。"""
    request_id = request_id_from(request)
    delivery = await PasswordResetService(repository).request_reset(
        email=payload.email,
        request_id=request_id,
    )
    if delivery is not None and mailer is not None:
        try:
            await mailer.send_password_reset(email=delivery.email, token=delivery.token)
        except Exception as error:
            logger.error(
                "密码重置邮件投递失败 request_id=%s exception_type=%s",
                request_id,
                type(error).__name__,
            )
    return PasswordResetRequestResponse(
        message="如果该邮箱已注册，我们会发送密码重置邮件",
    )


@router.post("/password-resets", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    payload: PasswordResetConfirmRequest,
    request: Request,
    repository: Annotated[AuthRepository, Depends(get_auth_repository)],
) -> Response:
    """消费单次令牌设置新密码，并撤销用户现有会话。"""
    try:
        await PasswordResetService(repository).reset_password(
            token=payload.token,
            new_password=payload.new_password,
            request_id=request_id_from(request),
        )
    except PasswordResetError as error:
        raise ApiError(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code=error.code,
            message=error.message,
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _session_response(identity: UserIdentity) -> SessionResponse:
    """把已验证身份转换为不含认证材料的会话响应。"""
    return SessionResponse(
        id=identity.id,
        email=identity.email_normalized,
        status=identity.status,
        created_at=identity.created_at,
    )
