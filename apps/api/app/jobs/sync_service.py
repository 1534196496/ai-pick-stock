"""编排行情 Provider、数据库锁、快照写入与任务留痕。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.modules.instruments.repository import InstrumentRepository
from app.modules.market_data.enums import SyncJobType, SyncStatus
from app.modules.market_data.providers.factory import ProviderBundle
from app.modules.market_data.providers.schemas import ProviderInstrument
from app.modules.market_data.repository import AdvisoryLock, MarketDataRepository

logger = logging.getLogger(__name__)

PersistAction = Callable[[AsyncSession], Awaitable[int]]

_LOCK_KEYS = {
    SyncJobType.INSTRUMENT_MASTER: 2_026_082_601,
    SyncJobType.STOCK_PRICES: 2_026_082_602,
    SyncJobType.FUND_OFFICIAL_NAV: 2_026_082_603,
    SyncJobType.FUND_ESTIMATED_NAV: 2_026_082_604,
}


@dataclass(frozen=True, slots=True)
class CollectedSync:
    """保存一次外部收集结果及其延后执行的数据库写入动作。"""

    persist: PersistAction
    failed_count: int = 0
    error_types: tuple[str, ...] = ()


class MarketDataSyncService:
    """以任务级数据库锁串行同步主数据、股票价格和基金净值。"""

    def __init__(
        self,
        engine: AsyncEngine,
        session_factory: async_sessionmaker[AsyncSession],
        providers: ProviderBundle,
    ) -> None:
        """绑定数据库资源和共享 Provider 连接池。"""
        self._engine = engine
        self._session_factory = session_factory
        self._providers = providers

    async def sync_instruments(self) -> bool:
        """同步股票和基金主数据，单一来源失败时保留另一来源成果。"""

        async def collect() -> CollectedSync:
            results = await asyncio.gather(
                self._providers.stock.fetch_instruments(),
                self._providers.fund.fetch_instruments(),
                return_exceptions=True,
            )
            instruments: list[ProviderInstrument] = []
            errors: list[str] = []
            for result in results:
                if isinstance(result, BaseException):
                    errors.append(type(result).__name__)
                else:
                    instruments.extend(result)

            async def persist(session: AsyncSession) -> int:
                """把成功来源的标准主数据批量写入本地数据库。"""
                return await InstrumentRepository(session).upsert_many(instruments)

            return CollectedSync(persist, len(errors), tuple(errors))

        return await self._run(
            job_type=SyncJobType.INSTRUMENT_MASTER,
            source="tencent+eastmoney",
            collect=collect,
        )

    async def sync_stock_prices(self) -> bool:
        """只为本地活跃股票同步最新价格。"""
        async with self._session_factory() as session:
            requests = await InstrumentRepository(session).list_stock_quote_requests()

        async def collect() -> CollectedSync:
            snapshots = await self._providers.stock.fetch_stock_prices(requests)

            async def persist(session: AsyncSession) -> int:
                """幂等写入股票最新价。"""
                return await MarketDataRepository(session).upsert_stock_prices(snapshots)

            return CollectedSync(persist, max(0, len(requests) - len(snapshots)))

        return await self._run(
            job_type=SyncJobType.STOCK_PRICES,
            source="tencent+sina",
            collect=collect,
        )

    async def sync_official_navs(self) -> bool:
        """只为本地活跃基金同步带真实业务日期的官方单位净值。"""
        tickers = await self._active_fund_tickers()

        async def collect() -> CollectedSync:
            snapshots = await self._providers.fund.fetch_official_navs(tickers) if tickers else []

            async def persist(session: AsyncSession) -> int:
                """幂等写入官方单位净值。"""
                return await MarketDataRepository(session).upsert_official_navs(snapshots)

            return CollectedSync(persist, max(0, len(tickers) - len(snapshots)))

        return await self._run(
            job_type=SyncJobType.FUND_OFFICIAL_NAV,
            source="eastmoney_fund_official",
            collect=collect,
        )

    async def sync_estimated_navs(self) -> bool:
        """为显式启用的活跃基金同步非权威盘中估算净值。"""
        tickers = await self._active_fund_tickers()

        async def collect() -> CollectedSync:
            snapshots = await self._providers.fund.fetch_estimated_navs(tickers)

            async def persist(session: AsyncSession) -> int:
                """幂等写入估算净值并保持独立价格类型。"""
                return await MarketDataRepository(session).upsert_estimated_navs(snapshots)

            return CollectedSync(persist, max(0, len(tickers) - len(snapshots)))

        return await self._run(
            job_type=SyncJobType.FUND_ESTIMATED_NAV,
            source="eastmoney_fund_estimate",
            collect=collect,
        )

    async def _active_fund_tickers(self) -> list[str]:
        """在短只读会话中读取活跃基金，避免外部请求占用数据库事务。"""
        async with self._session_factory() as session:
            return await InstrumentRepository(session).list_active_fund_tickers()

    async def _run(
        self,
        *,
        job_type: SyncJobType,
        source: str,
        collect: Callable[[], Awaitable[CollectedSync]],
    ) -> bool:
        """持有专用 advisory lock，完成收集、事务写入和最终状态记录。"""
        async with (
            self._engine.connect() as connection,
            AdvisoryLock(connection, _LOCK_KEYS[job_type]) as lock,
        ):
            if not lock.acquired:
                logger.info("跳过重复同步任务 job_type=%s", job_type.value)
                return False

            run_id = await self._start_run(job_type=job_type, source=source)
            try:
                collected = await collect()
                async with self._session_factory() as session, session.begin():
                    succeeded_count = await collected.persist(session)
                    await MarketDataRepository(session).finish_run(
                        run_id=run_id,
                        status=_sync_status(succeeded_count, collected.failed_count),
                        succeeded_count=succeeded_count,
                        failed_count=collected.failed_count,
                        error_summary=",".join(collected.error_types) or None,
                    )
            except Exception as error:
                await self._finish_failed(run_id=run_id, error_type=type(error).__name__)
                logger.warning(
                    "行情同步失败 job_type=%s error_type=%s",
                    job_type.value,
                    type(error).__name__,
                )
            return True

    async def _start_run(self, *, job_type: SyncJobType, source: str) -> UUID:
        """在外部请求前提交 RUNNING 记录，确保中断也可观测。"""
        async with self._session_factory() as session, session.begin():
            return await MarketDataRepository(session).start_run(job_type=job_type, source=source)

    async def _finish_failed(self, *, run_id: UUID, error_type: str) -> None:
        """在独立事务中把异常任务标记为失败且只保存异常类型。"""
        async with self._session_factory() as session, session.begin():
            await MarketDataRepository(session).finish_run(
                run_id=run_id,
                status=SyncStatus.FAILED,
                succeeded_count=0,
                failed_count=1,
                error_summary=error_type,
            )


def _sync_status(succeeded_count: int, failed_count: int) -> SyncStatus:
    """根据成功写入数和失败数确定最终任务状态。"""
    if failed_count == 0:
        return SyncStatus.SUCCEEDED
    if succeeded_count > 0:
        return SyncStatus.PARTIAL
    return SyncStatus.FAILED
