"""行情同步状态 API 响应契约。"""

from datetime import datetime

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
