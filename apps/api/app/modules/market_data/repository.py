"""分型行情、最新读模型、同步任务和 advisory lock 持久化边界。"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from uuid import UUID

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.modules.instruments.enums import AssetType, Market
from app.modules.market_data.domain import MarketDataScheduleRecord, PriceRecord, SyncRunRecord
from app.modules.market_data.enums import PriceType, SyncJobType, SyncStatus
from app.modules.market_data.models import (
    DataSyncRun,
    FundDailyNav,
    IntradayQuote,
    LatestQuote,
    MarketDataSchedule,
)
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
    """维护最新行情读模型，并把不同粒度历史写入专用表。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定由调度器或 API 管理提交与回滚的事务会话。"""
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
        """同步写入股票最新价读模型和盘中时间序列。"""
        return await self._upsert_intraday_quotes(
            [
                {
                    "ticker": item.ticker,
                    "quote_type": PriceType.STOCK_LAST,
                    "value": item.value,
                    "change_rate": item.change_rate,
                    "quoted_at": item.as_of_at,
                    "fetched_at": item.fetched_at,
                    "source": item.source,
                }
                for item in snapshots
            ],
            asset_type=AssetType.STOCK,
        )

    async def upsert_estimated_navs(
        self,
        snapshots: Sequence[FundEstimatedNavSnapshot],
    ) -> int:
        """同步写入基金盘中估值读模型和时间序列。"""
        return await self._upsert_intraday_quotes(
            [
                {
                    "ticker": item.ticker,
                    "quote_type": PriceType.FUND_ESTIMATED_NAV,
                    "value": item.estimated_nav,
                    "change_rate": item.change_rate,
                    "quoted_at": item.as_of_at,
                    "fetched_at": item.fetched_at,
                    "source": item.source,
                }
                for item in snapshots
            ],
            asset_type=AssetType.FUND,
        )

    async def upsert_official_navs(
        self,
        snapshots: Sequence[FundOfficialNavSnapshot],
    ) -> int:
        """按基金和净值日期幂等写入官方净值历史。"""
        if not snapshots:
            return 0
        instrument_map = await self._instrument_ids(
            asset_type=AssetType.FUND,
            tickers=[item.ticker for item in snapshots],
        )
        values = [
            {
                "instrument_id": instrument_map[item.ticker],
                "nav_date": item.nav_date,
                "unit_nav": item.unit_nav,
                "accumulated_nav": None,
                "daily_return_rate": item.change_rate,
                "fetched_at": item.fetched_at,
                "first_observed_at": item.fetched_at,
                "source": item.source,
            }
            for item in snapshots
            if item.ticker in instrument_map
        ]
        if not values:
            return 0
        statement = insert(FundDailyNav).values(values)
        statement = statement.on_conflict_do_update(
            index_elements=[FundDailyNav.instrument_id, FundDailyNav.nav_date],
            set_={
                "unit_nav": statement.excluded.unit_nav,
                "daily_return_rate": statement.excluded.daily_return_rate,
                "fetched_at": statement.excluded.fetched_at,
                "source": statement.excluded.source,
                "updated_at": datetime.now(UTC),
            },
        )
        await self._session.execute(statement)
        return len(values)

    async def latest_prices(
        self,
        *,
        instrument_ids: Sequence[UUID],
    ) -> dict[UUID, list[PriceRecord]]:
        """组合最新行情读模型与基金官方净值，保持上层估值契约稳定。"""
        if not instrument_ids:
            return {}
        records: dict[UUID, list[PriceRecord]] = {}
        latest_quotes = (
            await self._session.scalars(
                select(LatestQuote).where(LatestQuote.instrument_id.in_(instrument_ids))
            )
        ).all()
        for quote in latest_quotes:
            records.setdefault(quote.instrument_id, []).append(self._quote_record(quote))

        latest_navs = (
            await self._session.scalars(
                select(FundDailyNav)
                .where(FundDailyNav.instrument_id.in_(instrument_ids))
                .distinct(FundDailyNav.instrument_id)
                .order_by(
                    FundDailyNav.instrument_id,
                    FundDailyNav.nav_date.desc(),
                    FundDailyNav.fetched_at.desc(),
                    FundDailyNav.id.desc(),
                )
            )
        ).all()
        for nav in latest_navs:
            records.setdefault(nav.instrument_id, []).append(self._nav_record(nav))
        return records

    async def official_nav_on_date(
        self,
        *,
        instrument_id: UUID,
        nav_date: date,
    ) -> PriceRecord | None:
        """读取基金指定真实业务日期的官方单位净值。"""
        nav = await self._session.scalar(
            select(FundDailyNav).where(
                FundDailyNav.instrument_id == instrument_id,
                FundDailyNav.nav_date == nav_date,
            )
        )
        return self._nav_record(nav) if nav is not None else None

    async def latest_official_nav_on_or_before(
        self,
        *,
        instrument_id: UUID,
        nav_date: date,
    ) -> PriceRecord | None:
        """读取指定日期当天或此前最近一条官方单位净值。"""
        nav = await self._session.scalar(
            select(FundDailyNav)
            .where(
                FundDailyNav.instrument_id == instrument_id,
                FundDailyNav.nav_date <= nav_date,
            )
            .order_by(FundDailyNav.nav_date.desc(), FundDailyNav.fetched_at.desc())
            .limit(1)
        )
        return self._nav_record(nav) if nav is not None else None

    async def latest_sync_runs(self) -> list[SyncRunRecord]:
        """返回每种任务最近一次运行，供状态接口判断失败和陈旧。"""
        runs = (
            await self._session.scalars(
                select(DataSyncRun)
                .distinct(DataSyncRun.job_type)
                .order_by(
                    DataSyncRun.job_type,
                    DataSyncRun.started_at.desc(),
                    DataSyncRun.id.desc(),
                )
            )
        ).all()
        return [self._to_sync_run_record(run) for run in runs]

    async def get_schedule(self, *, for_update: bool = False) -> MarketDataScheduleRecord:
        """读取唯一行情调度配置，迁移后意外缺行时自动补齐默认值。"""
        statement = select(MarketDataSchedule).where(MarketDataSchedule.id == 1)
        if for_update:
            statement = statement.with_for_update()
        schedule = await self._session.scalar(statement)
        if schedule is None:
            schedule = MarketDataSchedule(id=1)
            self._session.add(schedule)
            await self._session.flush()
        return self._to_schedule_record(schedule)

    async def update_schedule(
        self,
        *,
        stock_refresh_seconds: int,
        fund_estimate_refresh_seconds: int,
        official_nav_refresh_seconds: int,
        official_nav_window_start: time,
        official_nav_window_end: time,
        instrument_sync_time: time,
    ) -> MarketDataScheduleRecord:
        """锁定并更新唯一配置，使 Worker 可通过版本号热加载。"""
        await self.get_schedule(for_update=True)
        schedule = await self._session.get(MarketDataSchedule, 1)
        assert schedule is not None
        schedule.stock_refresh_seconds = stock_refresh_seconds
        schedule.fund_estimate_refresh_seconds = fund_estimate_refresh_seconds
        schedule.official_nav_refresh_seconds = official_nav_refresh_seconds
        schedule.official_nav_window_start = official_nav_window_start
        schedule.official_nav_window_end = official_nav_window_end
        schedule.instrument_sync_time = instrument_sync_time
        schedule.version += 1
        schedule.updated_at = datetime.now(UTC)
        await self._session.flush()
        return self._to_schedule_record(schedule)

    async def _upsert_intraday_quotes(
        self,
        snapshots: list[dict[str, object]],
        *,
        asset_type: AssetType,
    ) -> int:
        """按业务时点写历史，并以较新的时点更新最新行情。"""
        if not snapshots:
            return 0
        instrument_map = await self._instrument_ids(
            asset_type=asset_type,
            tickers=[str(item["ticker"]) for item in snapshots],
        )
        values = [
            {
                "instrument_id": instrument_map[str(item["ticker"])],
                "quote_type": item["quote_type"],
                "value": item["value"],
                "change_rate": item["change_rate"],
                "quoted_at": item["quoted_at"],
                "fetched_at": item["fetched_at"],
                "source": item["source"],
            }
            for item in snapshots
            if str(item["ticker"]) in instrument_map
        ]
        if not values:
            return 0

        history = insert(IntradayQuote).values(values)
        history = history.on_conflict_do_update(
            index_elements=[
                IntradayQuote.instrument_id,
                IntradayQuote.quote_type,
                IntradayQuote.quoted_at,
                IntradayQuote.source,
            ],
            set_={
                "value": history.excluded.value,
                "change_rate": history.excluded.change_rate,
                "fetched_at": history.excluded.fetched_at,
            },
        )
        await self._session.execute(history)

        latest = insert(LatestQuote).values(values)
        latest = latest.on_conflict_do_update(
            index_elements=[LatestQuote.instrument_id, LatestQuote.quote_type],
            set_={
                "value": latest.excluded.value,
                "change_rate": latest.excluded.change_rate,
                "quoted_at": latest.excluded.quoted_at,
                "fetched_at": latest.excluded.fetched_at,
                "source": latest.excluded.source,
                "updated_at": datetime.now(UTC),
            },
            where=latest.excluded.quoted_at >= LatestQuote.quoted_at,
        )
        await self._session.execute(latest)
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

    @staticmethod
    def _quote_record(quote: LatestQuote) -> PriceRecord:
        """把最新行情读模型转换为稳定的价格领域记录。"""
        return PriceRecord(
            instrument_id=quote.instrument_id,
            price_type=quote.quote_type,
            value=quote.value,
            change_rate=quote.change_rate,
            as_of_date=None,
            as_of_at=quote.quoted_at,
            fetched_at=quote.fetched_at,
            source=quote.source,
        )

    @staticmethod
    def _nav_record(nav: FundDailyNav) -> PriceRecord:
        """把基金官方净值转换为稳定的价格领域记录。"""
        return PriceRecord(
            instrument_id=nav.instrument_id,
            price_type=PriceType.FUND_OFFICIAL_NAV,
            value=nav.unit_nav,
            change_rate=nav.daily_return_rate,
            as_of_date=nav.nav_date,
            as_of_at=None,
            fetched_at=nav.fetched_at,
            source=nav.source,
            first_observed_at=nav.first_observed_at,
        )

    @staticmethod
    def _to_sync_run_record(run: DataSyncRun) -> SyncRunRecord:
        """移除内部错误摘要后返回同步任务公开状态。"""
        return SyncRunRecord(
            job_type=run.job_type,
            status=run.status,
            source=run.source,
            started_at=run.started_at,
            finished_at=run.finished_at,
            succeeded_count=run.succeeded_count,
            failed_count=run.failed_count,
        )

    @staticmethod
    def _to_schedule_record(schedule: MarketDataSchedule) -> MarketDataScheduleRecord:
        """把单例 ORM 配置转换为调度器和 API 共用的不可变记录。"""
        return MarketDataScheduleRecord(
            stock_refresh_seconds=schedule.stock_refresh_seconds,
            fund_estimate_refresh_seconds=schedule.fund_estimate_refresh_seconds,
            official_nav_refresh_seconds=schedule.official_nav_refresh_seconds,
            official_nav_window_start=schedule.official_nav_window_start,
            official_nav_window_end=schedule.official_nav_window_end,
            instrument_sync_time=schedule.instrument_sync_time,
            version=schedule.version,
            updated_at=schedule.updated_at,
        )
