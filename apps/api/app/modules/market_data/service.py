"""行情新鲜度规则和同步状态读取用例。"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.modules.market_data.domain import DataFreshness, PriceRecord, SyncRunRecord
from app.modules.market_data.enums import PriceType, SyncJobType, SyncStatus
from app.modules.market_data.repository import MarketDataRepository


@dataclass(frozen=True, slots=True)
class SyncRunView:
    """组合最近同步记录及其保守的新鲜度判断。"""

    record: SyncRunRecord
    freshness: DataFreshness


class MarketDataFreshnessPolicy:
    """根据任务频率和每日任务节奏判断本地行情是否陈旧。"""

    def __init__(self, *, stock_refresh_seconds: int) -> None:
        """使用实际股票刷新配置派生盘中数据的新鲜窗口。"""
        self._realtime_window = timedelta(seconds=max(300, stock_refresh_seconds * 3))

    def for_price(
        self,
        price: PriceRecord,
        *,
        now: datetime | None = None,
    ) -> DataFreshness:
        """以抓取时间判断旧值是否仍处于对应价格类型的窗口内。"""
        current = now or datetime.now(UTC)
        window = (
            timedelta(hours=48)
            if price.price_type == PriceType.FUND_OFFICIAL_NAV
            else self._realtime_window
        )
        return (
            DataFreshness.FRESH
            if current - price.fetched_at <= window
            else DataFreshness.STALE
        )

    def for_sync_run(
        self,
        run: SyncRunRecord,
        *,
        now: datetime | None = None,
    ) -> DataFreshness:
        """成功且未超过任务窗口才视为新鲜，失败和部分成功保守标陈旧。"""
        if run.status != SyncStatus.SUCCEEDED or run.finished_at is None:
            return DataFreshness.STALE
        current = now or datetime.now(UTC)
        window = self._sync_window(run.job_type)
        return (
            DataFreshness.FRESH
            if current - run.finished_at <= window
            else DataFreshness.STALE
        )

    def _sync_window(self, job_type: SyncJobType) -> timedelta:
        """为每日任务保留跨周末抓取窗口，为盘中任务使用配置派生窗口。"""
        if job_type == SyncJobType.INSTRUMENT_MASTER:
            return timedelta(hours=36)
        if job_type == SyncJobType.FUND_OFFICIAL_NAV:
            return timedelta(hours=48)
        return self._realtime_window


class MarketDataStatusService:
    """读取最近同步任务并附加不依赖外网的新鲜度。"""

    def __init__(
        self,
        repository: MarketDataRepository,
        freshness_policy: MarketDataFreshnessPolicy,
    ) -> None:
        """注入行情读取边界和统一新鲜度策略。"""
        self._repository = repository
        self._freshness_policy = freshness_policy

    async def latest_runs(self) -> list[SyncRunView]:
        """返回所有已有任务类型的最近运行状态。"""
        now = datetime.now(UTC)
        return [
            SyncRunView(
                record=run,
                freshness=self._freshness_policy.for_sync_run(run, now=now),
            )
            for run in await self._repository.latest_sync_runs()
        ]
