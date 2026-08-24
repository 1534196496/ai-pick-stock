"""数据库引擎、模型基类与就绪探测。"""

from collections.abc import Awaitable, Callable

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings


class Base(DeclarativeBase):
    """集中承载所有业务模块的 SQLAlchemy 元数据。"""


DatabaseProbe = Callable[[AsyncEngine], Awaitable[bool]]


def create_database_engine(settings: Settings) -> AsyncEngine:
    """根据已校验配置创建不会在构造阶段主动联网的异步引擎。"""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
    )


async def probe_database(engine: AsyncEngine) -> bool:
    """执行最小查询判断数据库可用性，不向接口泄露异常细节。"""
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True
