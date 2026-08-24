"""FastAPI 应用入口。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.core.config import Settings
from app.core.database import DatabaseProbe, create_database_engine, probe_database
from app.core.errors import register_error_handlers
from app.core.middleware import (
    InMemoryRateLimiter,
    RateLimiter,
    RequestContextMiddleware,
    RequestSecurityMiddleware,
)
from app.modules.auth.router import router as auth_router


class HealthResponse(BaseModel):
    """定义健康检查的稳定公开响应契约。"""

    status: Literal["ok", "not_ready"]
    checks: dict[str, Literal["ok", "unavailable"]] | None = None


def create_app(
    *,
    database_probe: DatabaseProbe = probe_database,
    rate_limiter: RateLimiter | None = None,
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
        try:
            yield
        finally:
            await engine.dispose()

    application = FastAPI(
        title="AI Pick Stock API",
        version="0.1.0",
        lifespan=lifespan,
    )
    register_error_handlers(application)
    application.add_middleware(
        RequestSecurityMiddleware,
        rate_limiter=rate_limiter or InMemoryRateLimiter(),
    )
    application.add_middleware(RequestContextMiddleware)
    application.include_router(auth_router, prefix="/api/v1")

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
        if not await database_probe(engine):
            response = HealthResponse(
                status="not_ready",
                checks={"database": "unavailable"},
            )
            return JSONResponse(
                status_code=503,
                content=response.model_dump(mode="json", exclude_none=True),
            )
        return HealthResponse(status="ok", checks={"database": "ok"})

    application.openapi_schema = _normalize_openapi_error_contract(application.openapi())
    return application


def _normalize_openapi_error_contract(schema: dict[str, Any]) -> dict[str, Any]:
    """让自动请求校验的 OpenAPI 响应与运行时统一错误处理器保持一致。"""
    for path_item in schema.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            response = operation.get("responses", {}).get("422")
            if not isinstance(response, dict):
                continue
            content = response.get("content", {}).get("application/json")
            if not isinstance(content, dict):
                continue
            response_schema = content.get("schema")
            if response_schema == {"$ref": "#/components/schemas/HTTPValidationError"}:
                content["schema"] = {"$ref": "#/components/schemas/ErrorResponse"}

    schemas = schema.get("components", {}).get("schemas", {})
    if isinstance(schemas, dict):
        schemas.pop("HTTPValidationError", None)
        schemas.pop("ValidationError", None)
    return schema


app = create_app()
