"""价格快照、同步任务和 advisory lock 持久化边界。"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.modules.instruments.enums import AssetType, Market
from app.modules.instruments.models import Instrument
from app.modules.market_data.enums import PriceType, SyncJobType, SyncStatus
from app.modules.market_data.models import DataSyncRun, InstrumentPrice
from app.modules.market_data.providers.schemas import (
    FundEstimatedNavSnapshot,
    FundOfficialNavSnapshot,
    StockPriceSnapshot,
)


class AdvisoryLock:
    """在单一数据库连接上持有并可靠释放任务级 advisory lock。"""

    def __init__(self, connection: AsyncConnection, key: int) -> None:
        """绑定专用连接和稳定整数锁键。"""
        self._connection = connection
        self._key = key
        self.acquired = False

    async def __aenter__(self) -> "AdvisoryLock":
        """非阻塞尝试获取锁，已有执行者时立即返回未获取状态。"""
        self.acquired = bool(
            await self._connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"),
                {"key": self._key},
            )
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        """只释放当前上下文实际获取的锁。"""
        if self.acquired:
            await self._connection.execute(
                text("SELECT pg_advisory_unlock(:key)"),
                {"key": self._key},
            )


class MarketDataRepository:
    """保存同步留痕和经过校验的最新价格快照。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定由调度器管理提交与回滚的事务会话。"""
        self._session = session

    async def start_run(
        self,
        *,
        job_type: SyncJobType,
        source: str,
        started_at: datetime | None = None,
    ) -> UUID:
        """创建 RUNNING 任务记录并返回 ID。"""
        run = DataSyncRun(
            job_type=job_type,
            status=SyncStatus.RUNNING,
            source=source,
            started_at=started_at or datetime.now(UTC),
            succeeded_count=0,
            failed_count=0,
        )
        self._session.add(run)
        await self._session.flush()
        return run.id

    async def finish_run(
        self,
        *,
        run_id: UUID,
        status: SyncStatus,
        succeeded_count: int,
        failed_count: int,
        error_summary: str | None,
        finished_at: datetime | None = None,
    ) -> None:
        """完成任务并把错误摘要限制在数据库边界内。"""
        await self._session.execute(
            update(DataSyncRun)
            .where(DataSyncRun.id == run_id)
            .values(
                status=status,
                succeeded_count=succeeded_count,
                failed_count=failed_count,
                error_summary=error_summary[:500] if error_summary else None,
                finished_at=finished_at or datetime.now(UTC),
            )
        )

    async def upsert_stock_prices(self, snapshots: Sequence[StockPriceSnapshot]) -> int:
        """按标的、类型、业务时点和来源幂等写入股票价格。"""
        return await self._upsert_at_prices(
            [
                {
                    "ticker": item.ticker,
                    "price_type": PriceType.STOCK_LAST,
                    "value": item.value,
                    "as_of_at": item.as_of_at,
                    "fetched_at": item.fetched_at,
                    "source": item.source,
                }
                for item in snapshots
            ],
            asset_type=AssetType.STOCK,
        )

    async def upsert_official_navs(
        self,
        snapshots: Sequence[FundOfficialNavSnapshot],
    ) -> int:
        """只把单位净值写入权威价格字段，累计净值不参与估值表。"""
        if not snapshots:
            return 0
        instrument_map = await self._instrument_ids(
            asset_type=AssetType.FUND,
            tickers=[item.ticker for item in snapshots],
        )
        values = [
            {
                "instrument_id": instrument_map[item.ticker],
                "price_type": PriceType.FUND_OFFICIAL_NAV,
                "value": item.unit_nav,
                "as_of_date": item.nav_date,
                "as_of_at": None,
                "fetched_at": item.fetched_at,
                "source": item.source,
            }
            for item in snapshots
            if item.ticker in instrument_map
        ]
        if not values:
            return 0
        statement = insert(InstrumentPrice).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[
                InstrumentPrice.instrument_id,
                InstrumentPrice.price_type,
                InstrumentPrice.as_of_date,
                InstrumentPrice.source,
            ],
            index_where=InstrumentPrice.as_of_date.is_not(None),
            set_={
                "value": statement.excluded.value,
                "fetched_at": statement.excluded.fetched_at,
            },
        )
        await self._session.execute(statement)
        return len(values)

    async def upsert_estimated_navs(
        self,
        snapshots: Sequence[FundEstimatedNavSnapshot],
    ) -> int:
        """幂等写入明确标记的非权威估算净值。"""
        return await self._upsert_at_prices(
            [
                {
                    "ticker": item.ticker,
                    "price_type": PriceType.FUND_ESTIMATED_NAV,
                    "value": item.estimated_nav,
                    "as_of_at": item.as_of_at,
                    "fetched_at": item.fetched_at,
                    "source": item.source,
                }
                for item in snapshots
            ],
            asset_type=AssetType.FUND,
        )

    async def _upsert_at_prices(
        self,
        snapshots: list[dict[str, object]],
        *,
        asset_type: AssetType,
    ) -> int:
        """写入以业务时点唯一的股票或基金估算价格。"""
        if not snapshots:
            return 0
        instrument_map = await self._instrument_ids(
            asset_type=asset_type,
            tickers=[str(item["ticker"]) for item in snapshots],
        )
        values = [
            {
                "instrument_id": instrument_map[str(item["ticker"])],
                "price_type": item["price_type"],
                "value": item["value"],
                "as_of_date": None,
                "as_of_at": item["as_of_at"],
                "fetched_at": item["fetched_at"],
                "source": item["source"],
            }
            for item in snapshots
            if str(item["ticker"]) in instrument_map
        ]
        if not values:
            return 0
        statement = insert(InstrumentPrice).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[
                InstrumentPrice.instrument_id,
                InstrumentPrice.price_type,
                InstrumentPrice.as_of_at,
                InstrumentPrice.source,
            ],
            index_where=InstrumentPrice.as_of_at.is_not(None),
            set_={
                "value": statement.excluded.value,
                "fetched_at": statement.excluded.fetched_at,
            },
        )
        await self._session.execute(statement)
        return len(values)

    async def _instrument_ids(
        self,
        *,
        asset_type: AssetType,
        tickers: list[str],
    ) -> dict[str, UUID]:
        """按标准身份解析 ticker，忽略尚未同步的未知标的。"""
        if not tickers:
            return {}
        rows = (
            await self._session.execute(
                text(
                    "SELECT ticker, id FROM instruments "
                    "WHERE asset_type = :asset_type AND market = :market "
                    "AND ticker = ANY(:tickers)"
                ),
                {
                    "asset_type": asset_type.value,
                    "market": Market.CN.value,
                    "tickers": tickers,
                },
            )
        ).all()
        return {str(ticker): instrument_id for ticker, instrument_id in rows}
