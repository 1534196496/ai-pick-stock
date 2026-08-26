"""后台行情同步进程入口。"""

import argparse
import asyncio
import logging
import signal
from collections.abc import Callable, Sequence
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.database import create_database_engine
from app.jobs.schedule_config import MarketDataScheduleCache
from app.jobs.scheduler import SHANGHAI, ScheduledJob, WorkerScheduler, is_time_in_window
from app.jobs.sync_service import MarketDataSyncService
from app.modules.market_data.providers.factory import create_provider_bundle

logger = logging.getLogger(__name__)


def run_worker(*, wait: Callable[[], None] | None = None) -> None:
    """校验配置并启动调度器；注入 wait 时保留轻量兼容入口。"""
    settings = Settings()
    if wait is not None:
        wait()
        return
    asyncio.run(_run_scheduler(settings))


async def _run_scheduler(settings: Settings) -> None:
    """创建共享资源并运行周期与每日任务直到收到停止信号。"""
    engine = create_database_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    providers = create_provider_bundle(settings)
    service = MarketDataSyncService(engine, session_factory, providers)
    schedule_cache = MarketDataScheduleCache(session_factory)
    stop = asyncio.Event()
    _install_signal_handlers(stop)
    try:
        if not settings.market_data_live_enabled:
            logger.info("外部行情同步未启用，Worker 保持待命")
            await stop.wait()
            return

        await schedule_cache.refresh()

        async def sync_official_navs_in_window() -> bool:
            """只在当前热配置的官方净值窗口内执行自动同步。"""
            schedule = schedule_cache.current
            if not is_time_in_window(
                datetime.now(SHANGHAI).time(),
                start=schedule.official_nav_window_start,
                end=schedule.official_nav_window_end,
            ):
                return False
            return await service.sync_official_navs()

        jobs = [
            ScheduledJob.periodic(
                "schedule-config",
                schedule_cache.refresh,
                interval_seconds=10,
                initial_delay_seconds=10,
            ),
            ScheduledJob.daily(
                "instrument-master",
                service.sync_instruments,
                hour=lambda: schedule_cache.current.instrument_sync_time.hour,
                minute=lambda: schedule_cache.current.instrument_sync_time.minute,
                initial_delay_seconds=1,
                reschedule_on_revision=True,
            ),
            ScheduledJob.periodic(
                "stock-prices",
                service.sync_stock_prices,
                interval_seconds=lambda: schedule_cache.current.stock_refresh_seconds,
                reschedule_on_revision=True,
            ),
            ScheduledJob.windowed_periodic(
                "fund-official-nav",
                sync_official_navs_in_window,
                interval_seconds=lambda: schedule_cache.current.official_nav_refresh_seconds,
                window_start=lambda: schedule_cache.current.official_nav_window_start,
                window_end=lambda: schedule_cache.current.official_nav_window_end,
                initial_delay_seconds=15,
                reschedule_on_revision=True,
            ),
        ]
        if settings.fund_estimate_enabled:
            jobs.append(
                ScheduledJob.periodic(
                    "fund-estimated-nav",
                    service.sync_estimated_navs,
                    interval_seconds=lambda: schedule_cache.current.fund_estimate_refresh_seconds,
                    initial_delay_seconds=15,
                    reschedule_on_revision=True,
                )
            )
        await WorkerScheduler(
            jobs,
            schedule_revision=lambda: schedule_cache.version,
        ).run(stop)
    finally:
        await providers.close()
        await engine.dispose()


def _install_signal_handlers(stop: asyncio.Event) -> None:
    """把容器终止信号转换为协作式异步停止事件。"""
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            signal.signal(signum, lambda *_: stop.set())


async def _run_once(settings: Settings, task: str) -> None:
    """为运维人工触发单个已命名同步任务。"""
    if not settings.market_data_live_enabled:
        raise RuntimeError("必须显式启用 AIPICKSTOCK_MARKET_DATA_LIVE_ENABLED")
    engine = create_database_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    providers = create_provider_bundle(settings)
    service = MarketDataSyncService(engine, session_factory, providers)
    actions = {
        "instrument-master": service.sync_instruments,
        "stock-prices": service.sync_stock_prices,
        "fund-official-nav": service.sync_official_navs,
        "fund-estimated-nav": service.sync_estimated_navs,
    }
    try:
        await actions[task]()
    finally:
        await providers.close()
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    """解析可选单次任务参数并启动 Worker。"""
    parser = argparse.ArgumentParser(description="持仓簿行情同步 Worker")
    parser.add_argument(
        "--once",
        choices=(
            "instrument-master",
            "stock-prices",
            "fund-official-nav",
            "fund-estimated-nav",
        ),
    )
    arguments = parser.parse_args(argv)
    if arguments.once:
        asyncio.run(_run_once(Settings(), arguments.once))
        return
    run_worker()


if __name__ == "__main__":
    main()
