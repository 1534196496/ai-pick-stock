"""行情同步状态 HTTP 路由。"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_identity, get_market_data_repository, get_settings
from app.core.config import Settings
from app.modules.auth.domain import UserIdentity
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.schemas import (
    MarketDataJobStatusResponse,
    MarketDataStatusResponse,
)
from app.modules.market_data.service import MarketDataFreshnessPolicy, MarketDataStatusService

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/status", response_model=MarketDataStatusResponse)
async def get_market_data_status(
    _identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[MarketDataRepository, Depends(get_market_data_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MarketDataStatusResponse:
    """返回每种已运行同步任务的最近状态，不在请求内访问行情源。"""
    service = MarketDataStatusService(
        repository,
        MarketDataFreshnessPolicy(stock_refresh_seconds=settings.stock_refresh_seconds),
    )
    runs = await service.latest_runs()
    return MarketDataStatusResponse(
        generated_at=datetime.now(UTC),
        jobs=[
            MarketDataJobStatusResponse(
                job_type=item.record.job_type,
                status=item.record.status,
                source=item.record.source,
                started_at=item.record.started_at,
                finished_at=item.record.finished_at,
                succeeded_count=item.record.succeeded_count,
                failed_count=item.record.failed_count,
                freshness=item.freshness,
            )
            for item in runs
        ],
    )
