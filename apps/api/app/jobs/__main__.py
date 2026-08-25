"""后台行情同步进程入口。"""

import argparse
import asyncio
import logging
import signal
from collections.abc import Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.database import create_database_engine
from app.jobs.scheduler import ScheduledJob, WorkerScheduler
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
    stop = asyncio.Event()
    _install_signal_handlers(stop)
    try:
        if not settings.market_data_live_enabled:
            logger.info("外部行情同步未启用，Worker 保持待命")
            await stop.wait()
            return

        jobs = [
            ScheduledJob.daily(
                "instrument-master",
                service.sync_instruments,
                hour=4,
                minute=0,
                initial_delay_seconds=1,
            ),
            ScheduledJob.periodic(
                "stock-prices",
                service.sync_stock_prices,
                interval_seconds=settings.stock_refresh_seconds,
            ),
            ScheduledJob.daily(
                "fund-official-nav",
                service.sync_official_navs,
                hour=22,
                minute=30,
                initial_delay_seconds=15,
            ),
        ]
        if settings.fund_estimate_enabled:
            jobs.append(
                ScheduledJob.periodic(
                    "fund-estimated-nav",
                    service.sync_estimated_navs,
                    interval_seconds=settings.stock_refresh_seconds,
                    initial_delay_seconds=15,
                )
            )
        await WorkerScheduler(jobs).run(stop)
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
