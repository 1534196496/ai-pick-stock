"""API 层数据库会话和模块依赖。"""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.security import SessionCookiePolicy, create_session_cookie_policy
from app.modules.auth.domain import SessionPrincipal, UserIdentity
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """为一次请求提供事务会话，成功提交，异常回滚。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.database_session_factory
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_auth_repository(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> AuthRepository:
    """把请求级数据库会话绑定到认证 Repository。"""
    return AuthRepository(session)


def get_session_cookie_policy(request: Request) -> SessionCookiePolicy:
    """从启动期已校验配置创建当前环境的会话 Cookie 策略。"""
    settings: Settings = request.app.state.settings
    return create_session_cookie_policy(
        production=settings.environment == "production",
        lifetime=timedelta(days=settings.session_lifetime_days),
    )


async def get_optional_session_principal(
    request: Request,
    repository: Annotated[AuthRepository, Depends(get_auth_repository)],
) -> SessionPrincipal | None:
    """从请求 Cookie 解析会话，未登录或失效时返回空。"""
    policy = get_session_cookie_policy(request)
    return await AuthService(repository).authenticate(token=request.cookies.get(policy.name))


async def get_current_identity(
    principal: Annotated[SessionPrincipal | None, Depends(get_optional_session_principal)],
) -> UserIdentity:
    """为受保护接口提供当前用户，缺少有效会话时拒绝访问。"""
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTHENTICATION_REQUIRED", "message": "请先登录"},
        )
    return principal.identity
