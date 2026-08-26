"""行情同步状态 API 响应契约。"""

from datetime import datetime, time

from pydantic import Field, model_validator

from app.api.schemas import ApiModel
from app.modules.market_data.domain import DataFreshness
from app.modules.market_data.enums import SyncJobType, SyncStatus


class MarketDataJobStatusResponse(ApiModel):
    """返回一种任务最近运行的计数、时间和新鲜度。"""

    job_type: SyncJobType
    status: SyncStatus
    source: str
    started_at: datetime
    finished_at: datetime | None
    succeeded_count: int
    failed_count: int
    freshness: DataFreshness


class MarketDataStatusResponse(ApiModel):
    """返回本地生成时间和已有同步任务的最近状态。"""

    generated_at: datetime
    jobs: list[MarketDataJobStatusResponse]


class MarketDataScheduleResponse(ApiModel):
    """返回后台同步频率及运行期开关状态。"""

    stock_refresh_seconds: int
    fund_estimate_refresh_seconds: int
    official_nav_refresh_seconds: int
    official_nav_window_start: time
    official_nav_window_end: time
    instrument_sync_time: time
    live_sync_enabled: bool
    fund_estimate_sync_enabled: bool
    version: int
    updated_at: datetime


class UpdateMarketDataScheduleRequest(ApiModel):
    """校验用户可修改的全站行情调度配置。"""

    stock_refresh_seconds: int = Field(ge=15, le=3600)
    fund_estimate_refresh_seconds: int = Field(ge=30, le=3600)
    official_nav_refresh_seconds: int = Field(ge=120, le=3600)
    official_nav_window_start: time
    official_nav_window_end: time
    instrument_sync_time: time

    @model_validator(mode="after")
    def validate_refresh_values(self) -> "UpdateMarketDataScheduleRequest":
        """拒绝零长度的官方净值检查窗口。"""
        if self.official_nav_window_start == self.official_nav_window_end:
            raise ValueError("官方净值检查开始和结束时间不能相同")
        return self


class ManualMarketDataSyncRequest(ApiModel):
    """指定一次人工同步需要执行的一个或多个任务。"""

    job_types: list[SyncJobType] = Field(min_length=1, max_length=4)


class ManualMarketDataSyncResponse(ApiModel):
    """汇总人工同步结束后的各任务状态和因锁跳过项。"""

    generated_at: datetime
    jobs: list[MarketDataJobStatusResponse]
    skipped_job_types: list[SyncJobType]
