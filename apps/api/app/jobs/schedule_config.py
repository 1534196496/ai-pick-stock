"""在 Worker 进程内热加载数据库中的行情调度配置。"""

from datetime import UTC, datetime, time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.market_data.domain import MarketDataScheduleRecord
from app.modules.market_data.repository import MarketDataRepository


class MarketDataScheduleCache:
    """缓存最近读取的调度配置，并用版本号通知调度器重排任务。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """绑定短事务会话工厂并设置与数据库迁移一致的启动默认值。"""
        self._session_factory = session_factory
        self._current = MarketDataScheduleRecord(
            stock_refresh_seconds=30,
            fund_estimate_refresh_seconds=60,
            official_nav_refresh_seconds=300,
            official_nav_window_start=time(16, 0),
            official_nav_window_end=time(0, 30),
            instrument_sync_time=time(4, 0),
            version=0,
            updated_at=datetime.now(UTC),
        )

    @property
    def current(self) -> MarketDataScheduleRecord:
        """返回当前进程已生效的不可变调度配置。"""
        return self._current

    @property
    def version(self) -> int:
        """返回数据库配置版本，供调度器判断是否需要重新排期。"""
        return self._current.version

    async def refresh(self) -> bool:
        """从数据库加载配置；仅在版本变化时替换当前快照。"""
        async with self._session_factory() as session, session.begin():
            schedule = await MarketDataRepository(session).get_schedule()
        changed = schedule.version != self._current.version
        if changed:
            self._current = schedule
        return changed
