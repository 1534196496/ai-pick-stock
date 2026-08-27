"""FastAPI 应用入口。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import Settings
from app.core.database import DatabaseProbe, create_database_engine, probe_database
from app.core.errors import install_error_handlers
from app.core.middleware import (
    AuthenticationRateLimiter,
    InMemoryAuthenticationRateLimiter,
    RequestSecurityMiddleware,
)
from app.modules.analysis.agent_runtime import create_codex_agent_runtime
from app.modules.analysis.chat_service import AIConversationAgentService
from app.modules.analysis.conversation_repository import AIConversationStore
from app.modules.analysis.provider import create_ai_model_client
from app.modules.analysis.router import conversation_router as analysis_conversation_router
from app.modules.analysis.router import router as analysis_router
from app.modules.auth.mailer import SmtpPasswordResetMailer
from app.modules.auth.router import router as auth_router
from app.modules.instruments.router import router as instrument_router
from app.modules.market_data.providers.factory import create_provider_bundle
from app.modules.market_data.router import router as market_data_router
from app.modules.portfolios.position_router import router as position_router
from app.modules.portfolios.position_router import summary_router as position_summary_router
from app.modules.watchlists.router import router as watchlist_router


class HealthResponse(BaseModel):
    """定义健康检查的稳定公开响应契约。"""

    status: Literal["ok", "not_ready"]
    checks: dict[str, Literal["ok", "unavailable"]] | None = None


def create_app(
    *,
    database_probe: DatabaseProbe = probe_database,
    authentication_rate_limiter: AuthenticationRateLimiter | None = None,
) -> FastAPI:
    """创建 API 应用并注册不依赖外部资源的基础路由。"""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        """在启动时校验配置，并在停止时释放数据库连接池。"""
        settings = Settings()
        engine = create_database_engine(settings)
        application.state.settings = settings
        application.state.database_engine = engine
        application.state.database_session_factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )
        application.state.password_reset_mailer = (
            SmtpPasswordResetMailer(
                host=settings.smtp_host,
                port=settings.smtp_port,
                sender=settings.smtp_from_email,
                public_web_url=settings.public_web_url,
                username=settings.smtp_username,
                password=settings.smtp_password,
                starttls=settings.smtp_starttls,
            )
            if settings.smtp_configured
            and settings.smtp_host is not None
            and settings.smtp_from_email is not None
            else None
        )
        providers = create_provider_bundle(settings)
        ai_model_client = create_ai_model_client(settings)
        codex_agent_runtime = create_codex_agent_runtime(settings)
        if codex_agent_runtime is not None:
            await codex_agent_runtime.start()
        application.state.market_data_providers = providers
        application.state.ai_model_client = ai_model_client
        application.state.codex_agent_runtime = codex_agent_runtime
        application.state.ai_conversation_agent_service = (
            AIConversationAgentService(
                store=AIConversationStore(application.state.database_session_factory),
                runtime=codex_agent_runtime,
                timeout_seconds=settings.ai_agent_turn_timeout_seconds,
            )
            if codex_agent_runtime is not None
            else None
        )
        try:
            yield
        finally:
            if codex_agent_runtime is not None:
                await codex_agent_runtime.close()
            if ai_model_client is not None:
                await ai_model_client.close()
            await providers.close()
            await engine.dispose()

    application = FastAPI(
        title="AI Pick Stock API",
        version="0.1.0",
        lifespan=lifespan,
    )
    install_error_handlers(application)
    application.add_middleware(
        RequestSecurityMiddleware,
        authentication_rate_limiter=(
            authentication_rate_limiter or InMemoryAuthenticationRateLimiter()
        ),
    )
    application.include_router(auth_router, prefix="/api/v1")
    application.include_router(instrument_router, prefix="/api/v1")
    application.include_router(market_data_router, prefix="/api/v1")
    application.include_router(position_router, prefix="/api/v1")
    application.include_router(position_summary_router, prefix="/api/v1")
    application.include_router(watchlist_router, prefix="/api/v1")
    application.include_router(analysis_router, prefix="/api/v1")
    application.include_router(analysis_conversation_router, prefix="/api/v1")

    @application.get(
        "/api/v1/health/live",
        tags=["health"],
        response_model=HealthResponse,
        response_model_exclude_none=True,
    )
    async def live() -> HealthResponse:
        """返回固定存活状态，供容器和反向代理探测进程。"""
        return HealthResponse(status="ok")

    @application.get(
        "/api/v1/health/ready",
        tags=["health"],
        response_model=HealthResponse,
        responses={503: {"model": HealthResponse}},
    )
    async def ready() -> HealthResponse | JSONResponse:
        """根据数据库探测结果返回可供流量入口使用的就绪状态。"""
        engine: AsyncEngine = application.state.database_engine
        checks: dict[str, Literal["ok", "unavailable"]] = {
            "database": "ok" if await database_probe(engine) else "unavailable"
        }
        settings: Settings = application.state.settings
        if settings.environment == "production":
            checks["smtp"] = (
                "ok" if application.state.password_reset_mailer is not None else "unavailable"
            )
        if "unavailable" in checks.values():
            response = HealthResponse(status="not_ready", checks=checks)
            return JSONResponse(
                status_code=503,
                content=response.model_dump(mode="json", exclude_none=True),
            )
        return HealthResponse(status="ok", checks=checks)

    return application


app = create_app()
