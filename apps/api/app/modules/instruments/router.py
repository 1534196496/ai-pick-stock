"""资产搜索和详情 HTTP 路由。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import (
    get_current_identity,
    get_instrument_repository,
    get_market_data_repository,
    get_settings,
)
from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.auth.domain import UserIdentity
from app.modules.instruments.enums import AssetType
from app.modules.instruments.repository import InstrumentRepository
from app.modules.instruments.schemas import (
    InstrumentListResponse,
    InstrumentResponse,
    LatestPriceResponse,
)
from app.modules.instruments.service import InstrumentError, InstrumentService, InstrumentView
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.service import MarketDataFreshnessPolicy

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=InstrumentListResponse)
async def search_instruments(
    _identity: Annotated[UserIdentity, Depends(get_current_identity)],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    query: Annotated[str | None, Query(max_length=160)] = None,
    asset_type: Annotated[AssetType | None, Query(alias="assetType")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> InstrumentListResponse:
    """按代码或名称分页搜索当前一期支持的股票和基金。"""
    records, total = await _service(
        instrument_repository,
        market_data_repository,
        settings,
    ).search(
        query=query,
        asset_type=asset_type,
        page=page,
        page_size=page_size,
    )
    return InstrumentListResponse(
        items=[_response(record) for record in records],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{instrument_id}", response_model=InstrumentResponse)
async def get_instrument(
    instrument_id: UUID,
    _identity: Annotated[UserIdentity, Depends(get_current_identity)],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> InstrumentResponse:
    """返回指定一期资产及各价格口径的最新本地快照。"""
    try:
        record = await _service(
            instrument_repository,
            market_data_repository,
            settings,
        ).get(instrument_id=instrument_id)
    except InstrumentError as error:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code=error.code,
            message=error.message,
        ) from error
    return _response(record)


def _service(
    instrument_repository: InstrumentRepository,
    market_data_repository: MarketDataRepository,
    settings: Settings,
) -> InstrumentService:
    """使用请求级 Repository 和已校验刷新配置创建资产服务。"""
    return InstrumentService(
        instrument_repository,
        market_data_repository,
        MarketDataFreshnessPolicy(stock_refresh_seconds=settings.stock_refresh_seconds),
    )


def _response(view: InstrumentView) -> InstrumentResponse:
    """把资产领域视图转换为公开 camelCase 响应。"""
    record = view.record
    return InstrumentResponse(
        id=record.id,
        asset_type=record.asset_type,
        market=record.market,
        exchange=record.exchange,
        ticker=record.ticker,
        name=record.name,
        currency=record.currency,
        source=record.source,
        source_updated_at=record.source_updated_at,
        updated_at=record.updated_at,
        latest_prices=[
            LatestPriceResponse(
                price_type=price.record.price_type,
                value=price.record.value,
                as_of_date=price.record.as_of_date,
                as_of_at=price.record.as_of_at,
                fetched_at=price.record.fetched_at,
                source=price.record.source,
                freshness=price.freshness,
            )
            for price in view.prices
        ],
    )
