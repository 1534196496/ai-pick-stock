"""数据库引擎、模型基类与就绪探测。"""

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TypeVar

from sqlalchemy import text
from sqlalchemy.engine.interfaces import Dialect
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import String, TypeDecorator

from app.core.config import Settings


class Base(DeclarativeBase):
    """集中承载所有业务模块的 SQLAlchemy 元数据。"""


EnumT = TypeVar("EnumT", bound=StrEnum)


class EnumValueType(TypeDecorator[EnumT]):
    """把字符串枚举映射为普通 VARCHAR，约束由表级 CHECK 明确定义。"""

    impl = String
    cache_ok = True

    def __init__(self, enum_class: type[EnumT], length: int) -> None:
        """记录枚举类型，并使用与迁移一致的字符串长度。"""
        self.enum_class = enum_class
        super().__init__(length=length)

    def process_bind_param(self, value: EnumT | str | None, dialect: Dialect) -> str | None:
        """写入前校验字符串值，避免无效枚举绕过应用层。"""
        del dialect
        if value is None:
            return None
        return self.enum_class(value).value

    def process_result_value(self, value: str | None, dialect: Dialect) -> EnumT | None:
        """读取时恢复为业务枚举，保持现有调用方行为不变。"""
        del dialect
        if value is None:
            return None
        return self.enum_class(value)


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
