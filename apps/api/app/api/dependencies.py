"""API 层数据库会话和模块依赖。"""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated, cast

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import SessionCookiePolicy, create_session_cookie_policy
from app.modules.analysis.chat_service import AIConversationAgentService
from app.modules.analysis.conversation_repository import AIConversationRepository
from app.modules.analysis.provider import AIModelClient
from app.modules.analysis.repository import AnalysisRepository
from app.modules.auth.domain import SessionPrincipal, UserIdentity
from app.modules.auth.mailer import PasswordResetMailer
from app.modules.auth.repository import AuthRepository
from app.modules.auth.service import AuthService
from app.modules.instruments.repository import InstrumentRepository
from app.modules.market_data.domain import MarketDataScheduleRecord
from app.modules.market_data.providers.contracts import FundNavProvider, StockPriceProvider
from app.modules.market_data.repository import MarketDataRepository
from app.modules.portfolios.position_repository import PositionRepository
from app.modules.watchlists.repository import WatchlistRepository


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
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> AuthRepository:
    """把请求级数据库会话绑定到认证 Repository。"""
    return AuthRepository(session)


def get_instrument_repository(
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> InstrumentRepository:
    """把请求事务绑定到资产主数据 Repository。"""
    return InstrumentRepository(session)


def get_market_data_repository(
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> MarketDataRepository:
    """把请求事务绑定到行情读取 Repository。"""
    return MarketDataRepository(session)


def get_analysis_repository(
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> AnalysisRepository:
    """把请求事务绑定到用户隔离的 AI 分析 Repository。"""
    return AnalysisRepository(session)


def get_ai_conversation_repository(
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> AIConversationRepository:
    """把请求事务绑定到用户隔离的 AI 会话 Repository。"""
    return AIConversationRepository(session)


async def get_market_data_schedule_record(
    repository: Annotated[MarketDataRepository, Depends(get_market_data_repository)],
) -> MarketDataScheduleRecord:
    """读取数据库中的动态行情调度配置供请求期新鲜度规则使用。"""
    return await repository.get_schedule()


def get_position_repository(
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> PositionRepository:
    """把请求事务绑定到用户隔离的持仓 Repository。"""
    return PositionRepository(session)


def get_watchlist_repository(
    session: Annotated[AsyncSession, Depends(get_database_session, scope="function")],
) -> WatchlistRepository:
    """把请求事务绑定到用户隔离的自选 Repository。"""
    return WatchlistRepository(session)


def get_settings(request: Request) -> Settings:
    """返回应用启动时已完成边界校验的配置。"""
    settings: Settings = request.app.state.settings
    return settings


def get_fund_nav_provider(request: Request) -> FundNavProvider:
    """返回应用级共享基金行情 Provider。"""
    provider: object = request.app.state.market_data_providers.fund
    return cast(FundNavProvider, provider)


def get_stock_price_provider(request: Request) -> StockPriceProvider:
    """返回应用级共享股票行情与历史 Provider。"""
    provider: object = request.app.state.market_data_providers.stock
    return cast(StockPriceProvider, provider)


def get_ai_model_client(request: Request) -> AIModelClient | None:
    """返回全站共享模型客户端，未配置时返回空。"""
    client: object | None = request.app.state.ai_model_client
    return cast(AIModelClient | None, client)


def get_ai_conversation_agent_service(request: Request) -> AIConversationAgentService | None:
    """返回应用级 Codex 会话编排器，未配置时返回空。"""
    service: object | None = request.app.state.ai_conversation_agent_service
    return cast(AIConversationAgentService | None, service)


def get_session_cookie_policy(request: Request) -> SessionCookiePolicy:
    """从启动期已校验配置创建当前环境的会话 Cookie 策略。"""
    settings: Settings = request.app.state.settings
    return create_session_cookie_policy(
        production=settings.environment == "production",
        lifetime=timedelta(days=settings.session_lifetime_days),
    )


def get_password_reset_mailer(request: Request) -> PasswordResetMailer | None:
    """返回启动期创建的 SMTP 适配器，开发环境可为空。"""
    mailer: object | None = request.app.state.password_reset_mailer
    return cast(PasswordResetMailer | None, mailer)


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
        raise ApiError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            code="AUTHENTICATION_REQUIRED",
            message="请先登录",
        )
    return principal.identity
