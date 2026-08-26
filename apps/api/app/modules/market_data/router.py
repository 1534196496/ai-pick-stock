"""行情同步状态 HTTP 路由。"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.dependencies import get_current_identity, get_market_data_repository, get_settings
from app.core.config import Settings
from app.core.errors import ApiError
from app.jobs.sync_service import MarketDataSyncService
from app.modules.auth.domain import UserIdentity
from app.modules.market_data.domain import MarketDataScheduleRecord
from app.modules.market_data.enums import SyncJobType
from app.modules.market_data.providers.factory import ProviderBundle
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.schemas import (
    ManualMarketDataSyncRequest,
    ManualMarketDataSyncResponse,
    MarketDataJobStatusResponse,
    MarketDataScheduleResponse,
    MarketDataStatusResponse,
    UpdateMarketDataScheduleRequest,
)
from app.modules.market_data.service import (
    MarketDataFreshnessPolicy,
    MarketDataStatusService,
    SyncRunView,
)

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/status", response_model=MarketDataStatusResponse)
async def get_market_data_status(
    _identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[MarketDataRepository, Depends(get_market_data_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MarketDataStatusResponse:
    """返回每种已运行同步任务的最近状态，不在请求内访问行情源。"""
    schedule = await repository.get_schedule()
    service = MarketDataStatusService(
        repository,
        MarketDataFreshnessPolicy(
            stock_refresh_seconds=schedule.stock_refresh_seconds,
            fund_estimate_refresh_seconds=schedule.fund_estimate_refresh_seconds,
        ),
    )
    runs = await service.latest_runs()
    return MarketDataStatusResponse(
        generated_at=datetime.now(UTC),
        jobs=[_job_status_response(item) for item in runs],
    )


@router.get("/schedule", response_model=MarketDataScheduleResponse)
async def get_market_data_schedule(
    _identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[MarketDataRepository, Depends(get_market_data_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MarketDataScheduleResponse:
    """返回后台 Worker 当前使用的定时任务配置。"""
    return _schedule_response(await repository.get_schedule(), settings=settings)


@router.put("/schedule", response_model=MarketDataScheduleResponse)
async def update_market_data_schedule(
    payload: UpdateMarketDataScheduleRequest,
    _identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[MarketDataRepository, Depends(get_market_data_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MarketDataScheduleResponse:
    """更新后台 Job 频率，Worker 最迟十秒内检测版本并重新排期。"""
    schedule = await repository.update_schedule(
        stock_refresh_seconds=payload.stock_refresh_seconds,
        fund_estimate_refresh_seconds=payload.fund_estimate_refresh_seconds,
        official_nav_refresh_seconds=payload.official_nav_refresh_seconds,
        official_nav_window_start=payload.official_nav_window_start,
        official_nav_window_end=payload.official_nav_window_end,
        instrument_sync_time=payload.instrument_sync_time,
    )
    return _schedule_response(schedule, settings=settings)


@router.post("/sync", response_model=ManualMarketDataSyncResponse)
async def manually_sync_market_data(
    payload: ManualMarketDataSyncRequest,
    request: Request,
    _identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[MarketDataRepository, Depends(get_market_data_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ManualMarketDataSyncResponse:
    """复用 Worker 同步服务立即运行指定任务，并返回任务最终状态。"""
    if not settings.market_data_live_enabled:
        raise ApiError(
            status_code=status.HTTP_409_CONFLICT,
            code="MARKET_DATA_SYNC_DISABLED",
            message="服务器尚未启用外部行情同步",
        )
    engine: AsyncEngine = request.app.state.database_engine
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.database_session_factory
    providers: ProviderBundle = request.app.state.market_data_providers
    sync_service = MarketDataSyncService(engine, session_factory, providers)
    actions = {
        SyncJobType.INSTRUMENT_MASTER: sync_service.sync_instruments,
        SyncJobType.STOCK_PRICES: sync_service.sync_stock_prices,
        SyncJobType.FUND_OFFICIAL_NAV: sync_service.sync_official_navs,
        SyncJobType.FUND_ESTIMATED_NAV: sync_service.sync_estimated_navs,
    }
    requested = list(dict.fromkeys(payload.job_types))
    skipped: list[SyncJobType] = []
    for job_type in requested:
        if not await actions[job_type]():
            skipped.append(job_type)

    schedule = await repository.get_schedule()
    status_service = MarketDataStatusService(
        repository,
        MarketDataFreshnessPolicy(
            stock_refresh_seconds=schedule.stock_refresh_seconds,
            fund_estimate_refresh_seconds=schedule.fund_estimate_refresh_seconds,
        ),
    )
    latest = {item.record.job_type: item for item in await status_service.latest_runs()}
    return ManualMarketDataSyncResponse(
        generated_at=datetime.now(UTC),
        jobs=[_job_status_response(latest[item]) for item in requested if item in latest],
        skipped_job_types=skipped,
    )


def _job_status_response(item: SyncRunView) -> MarketDataJobStatusResponse:
    """把服务层同步状态视图转换为稳定 HTTP 响应。"""
    return MarketDataJobStatusResponse(
        job_type=item.record.job_type,
        status=item.record.status,
        source=item.record.source,
        started_at=item.record.started_at,
        finished_at=item.record.finished_at,
        succeeded_count=item.record.succeeded_count,
        failed_count=item.record.failed_count,
        freshness=item.freshness,
    )


def _schedule_response(
    schedule: MarketDataScheduleRecord,
    *,
    settings: Settings,
) -> MarketDataScheduleResponse:
    """组合数据库调度配置和环境级联网开关。"""
    return MarketDataScheduleResponse(
        stock_refresh_seconds=schedule.stock_refresh_seconds,
        fund_estimate_refresh_seconds=schedule.fund_estimate_refresh_seconds,
        official_nav_refresh_seconds=schedule.official_nav_refresh_seconds,
        official_nav_window_start=schedule.official_nav_window_start,
        official_nav_window_end=schedule.official_nav_window_end,
        instrument_sync_time=schedule.instrument_sync_time,
        live_sync_enabled=settings.market_data_live_enabled,
        fund_estimate_sync_enabled=settings.fund_estimate_enabled,
        version=schedule.version,
        updated_at=schedule.updated_at,
    )
