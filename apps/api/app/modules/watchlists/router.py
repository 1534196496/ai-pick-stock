"""自选分组与观察标的 HTTP 路由。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import (
    get_current_identity,
    get_instrument_repository,
    get_market_data_repository,
    get_market_data_schedule_record,
    get_watchlist_repository,
)
from app.core.errors import ApiError
from app.modules.auth.domain import UserIdentity
from app.modules.instruments.repository import InstrumentRepository
from app.modules.instruments.schemas import InstrumentResponse, LatestPriceResponse
from app.modules.instruments.service import InstrumentView
from app.modules.market_data.domain import MarketDataScheduleRecord
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.service import MarketDataFreshnessPolicy
from app.modules.watchlists.domain import WatchlistGroupRecord
from app.modules.watchlists.repository import WatchlistRepository
from app.modules.watchlists.schemas import (
    CreateWatchlistGroupRequest,
    CreateWatchlistItemRequest,
    UpdateWatchlistGroupRequest,
    UpdateWatchlistItemRequest,
    WatchlistGroupListResponse,
    WatchlistGroupResponse,
    WatchlistItemListResponse,
    WatchlistItemResponse,
)
from app.modules.watchlists.service import (
    WatchlistError,
    WatchlistGroupView,
    WatchlistItemView,
    WatchlistService,
)

router = APIRouter(tags=["watchlists"])


@router.get("/watchlist-groups", response_model=WatchlistGroupListResponse)
async def list_watchlist_groups(
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[WatchlistRepository, Depends(get_watchlist_repository)],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    schedule: Annotated[MarketDataScheduleRecord, Depends(get_market_data_schedule_record)],
) -> WatchlistGroupListResponse:
    """返回当前用户全部自选分组及标的数量。"""
    records = await _service(
        repository,
        instrument_repository,
        market_data_repository,
        schedule,
    ).list_groups(user_id=identity.id)
    return WatchlistGroupListResponse(items=[_group_response(record) for record in records])


@router.post(
    "/watchlist-groups",
    status_code=status.HTTP_201_CREATED,
    response_model=WatchlistGroupResponse,
)
async def create_watchlist_group(
    payload: CreateWatchlistGroupRequest,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[WatchlistRepository, Depends(get_watchlist_repository)],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    schedule: Annotated[MarketDataScheduleRecord, Depends(get_market_data_schedule_record)],
) -> WatchlistGroupResponse:
    """为当前用户创建名称唯一的普通自选分组。"""
    try:
        record = await _service(
            repository,
            instrument_repository,
            market_data_repository,
            schedule,
        ).create_group(user_id=identity.id, name=payload.name)
    except WatchlistError as error:
        raise _api_error(error) from error
    return _group_response(record)


@router.get("/watchlist-groups/{group_id}", response_model=WatchlistGroupResponse)
async def get_watchlist_group(
    group_id: UUID,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[WatchlistRepository, Depends(get_watchlist_repository)],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    schedule: Annotated[MarketDataScheduleRecord, Depends(get_market_data_schedule_record)],
) -> WatchlistGroupResponse:
    """返回当前用户拥有的指定自选分组。"""
    try:
        record = await _service(
            repository,
            instrument_repository,
            market_data_repository,
            schedule,
        ).get_group(user_id=identity.id, group_id=group_id)
    except WatchlistError as error:
        raise _api_error(error) from error
    return _group_response(record)


@router.patch("/watchlist-groups/{group_id}", response_model=WatchlistGroupResponse)
async def update_watchlist_group(
    group_id: UUID,
    payload: UpdateWatchlistGroupRequest,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[WatchlistRepository, Depends(get_watchlist_repository)],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    schedule: Annotated[MarketDataScheduleRecord, Depends(get_market_data_schedule_record)],
) -> WatchlistGroupResponse:
    """按版本重命名或调整当前用户自选分组排序。"""
    try:
        record = await _service(
            repository,
            instrument_repository,
            market_data_repository,
            schedule,
        ).update_group(
            user_id=identity.id,
            group_id=group_id,
            version=payload.version,
            name=payload.name,
            sort_order=payload.sort_order,
        )
    except WatchlistError as error:
        raise _api_error(error) from error
    return _group_response(record)


@router.delete("/watchlist-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist_group(
    group_id: UUID,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[WatchlistRepository, Depends(get_watchlist_repository)],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    schedule: Annotated[MarketDataScheduleRecord, Depends(get_market_data_schedule_record)],
) -> Response:
    """删除当前用户的普通空分组。"""
    try:
        await _service(
            repository,
            instrument_repository,
            market_data_repository,
            schedule,
        ).delete_group(user_id=identity.id, group_id=group_id)
    except WatchlistError as error:
        raise _api_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/watchlist-groups/{group_id}/items",
    response_model=WatchlistItemListResponse,
)
async def list_watchlist_items(
    group_id: UUID,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[WatchlistRepository, Depends(get_watchlist_repository)],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    schedule: Annotated[MarketDataScheduleRecord, Depends(get_market_data_schedule_record)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> WatchlistItemListResponse:
    """分页返回当前用户指定分组的观察标的与本地行情。"""
    try:
        records, total = await _service(
            repository,
            instrument_repository,
            market_data_repository,
            schedule,
        ).list_items(
            user_id=identity.id,
            group_id=group_id,
            page=page,
            page_size=page_size,
        )
    except WatchlistError as error:
        raise _api_error(error) from error
    return WatchlistItemListResponse(
        items=[_item_response(record) for record in records],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post(
    "/watchlist-groups/{group_id}/items",
    status_code=status.HTTP_201_CREATED,
    response_model=WatchlistItemResponse,
)
async def create_watchlist_item(
    group_id: UUID,
    payload: CreateWatchlistItemRequest,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[WatchlistRepository, Depends(get_watchlist_repository)],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    schedule: Annotated[MarketDataScheduleRecord, Depends(get_market_data_schedule_record)],
) -> WatchlistItemResponse:
    """向当前用户指定分组添加股票或基金。"""
    try:
        record = await _service(
            repository,
            instrument_repository,
            market_data_repository,
            schedule,
        ).create_item(
            user_id=identity.id,
            group_id=group_id,
            instrument_id=payload.instrument_id,
            note=payload.note,
        )
    except WatchlistError as error:
        raise _api_error(error) from error
    return _item_response(record)


@router.get("/watchlist-items/{item_id}", response_model=WatchlistItemResponse)
async def get_watchlist_item(
    item_id: UUID,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[WatchlistRepository, Depends(get_watchlist_repository)],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    schedule: Annotated[MarketDataScheduleRecord, Depends(get_market_data_schedule_record)],
) -> WatchlistItemResponse:
    """返回当前用户拥有的指定观察标的。"""
    try:
        record = await _service(
            repository,
            instrument_repository,
            market_data_repository,
            schedule,
        ).get_item(user_id=identity.id, item_id=item_id)
    except WatchlistError as error:
        raise _api_error(error) from error
    return _item_response(record)


@router.patch("/watchlist-items/{item_id}", response_model=WatchlistItemResponse)
async def update_watchlist_item(
    item_id: UUID,
    payload: UpdateWatchlistItemRequest,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[WatchlistRepository, Depends(get_watchlist_repository)],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    schedule: Annotated[MarketDataScheduleRecord, Depends(get_market_data_schedule_record)],
) -> WatchlistItemResponse:
    """按版本移动观察标的、修改备注或调整排序。"""
    try:
        record = await _service(
            repository,
            instrument_repository,
            market_data_repository,
            schedule,
        ).update_item(
            user_id=identity.id,
            item_id=item_id,
            version=payload.version,
            group_id=payload.group_id,
            note=payload.note,
            note_provided="note" in payload.model_fields_set,
            sort_order=payload.sort_order,
        )
    except WatchlistError as error:
        raise _api_error(error) from error
    return _item_response(record)


@router.delete("/watchlist-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist_item(
    item_id: UUID,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[WatchlistRepository, Depends(get_watchlist_repository)],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    schedule: Annotated[MarketDataScheduleRecord, Depends(get_market_data_schedule_record)],
) -> Response:
    """删除当前用户指定观察标的。"""
    try:
        await _service(
            repository,
            instrument_repository,
            market_data_repository,
            schedule,
        ).delete_item(user_id=identity.id, item_id=item_id)
    except WatchlistError as error:
        raise _api_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _service(
    repository: WatchlistRepository,
    instrument_repository: InstrumentRepository,
    market_data_repository: MarketDataRepository,
    schedule: MarketDataScheduleRecord,
) -> WatchlistService:
    """使用请求级 Repository 和统一行情新鲜度配置创建自选服务。"""
    return WatchlistService(
        repository,
        instrument_repository,
        market_data_repository,
        MarketDataFreshnessPolicy(
            stock_refresh_seconds=schedule.stock_refresh_seconds,
            fund_estimate_refresh_seconds=schedule.fund_estimate_refresh_seconds,
        ),
    )


def _group_response(view: WatchlistGroupView) -> WatchlistGroupResponse:
    """裁剪用户归属字段并生成公开分组响应。"""
    record: WatchlistGroupRecord = view.record
    return WatchlistGroupResponse(
        id=record.id,
        name=record.name,
        is_default=record.is_default,
        sort_order=record.sort_order,
        item_count=view.item_count,
        position_count=view.position_count,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _item_response(view: WatchlistItemView) -> WatchlistItemResponse:
    """把观察记录、资产和价格转换为公开响应。"""
    record = view.record
    return WatchlistItemResponse(
        id=record.id,
        group_id=record.group_id,
        instrument=_instrument_response(view.instrument),
        note=record.note,
        sort_order=record.sort_order,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _instrument_response(view: InstrumentView) -> InstrumentResponse:
    """把自选项内嵌资产和全部价格口径转换为公开响应。"""
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
                change_rate=price.record.change_rate,
                as_of_date=price.record.as_of_date,
                as_of_at=price.record.as_of_at,
                fetched_at=price.record.fetched_at,
                source=price.record.source,
                freshness=price.freshness,
            )
            for price in view.prices
        ],
    )


def _api_error(error: WatchlistError) -> ApiError:
    """把自选领域错误映射到稳定 HTTP 状态。"""
    if error.code in {
        "WATCHLIST_GROUP_NOT_FOUND",
        "WATCHLIST_ITEM_NOT_FOUND",
        "INSTRUMENT_NOT_FOUND",
    }:
        status_code = status.HTTP_404_NOT_FOUND
    elif error.code in {
        "WATCHLIST_GROUP_NAME_ALREADY_EXISTS",
        "WATCHLIST_GROUP_VERSION_CONFLICT",
        "WATCHLIST_DEFAULT_GROUP_PROTECTED",
        "WATCHLIST_GROUP_NOT_EMPTY",
        "WATCHLIST_ITEM_ALREADY_EXISTS",
        "WATCHLIST_ITEM_VERSION_CONFLICT",
    }:
        status_code = status.HTTP_409_CONFLICT
    else:
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return ApiError(
        status_code=status_code,
        code=error.code,
        message=error.message,
        details=error.details,
    )
