"""股票与基金持仓 CRUD HTTP 路由。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import (
    get_current_identity,
    get_instrument_repository,
    get_investment_account_repository,
    get_market_data_repository,
    get_position_repository,
    get_settings,
)
from app.core.config import Settings
from app.core.errors import ApiError
from app.modules.auth.domain import UserIdentity
from app.modules.instruments.repository import InstrumentRepository
from app.modules.instruments.schemas import LatestPriceResponse
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.service import MarketDataFreshnessPolicy
from app.modules.portfolios.position_commands import (
    FundAmountPositionCommand,
    FundSharesPositionCommand,
    StockPositionCommand,
    UpdateFundAmountPositionCommand,
    UpdateFundSharesPositionCommand,
    UpdateStockPositionCommand,
)
from app.modules.portfolios.position_repository import PositionRepository
from app.modules.portfolios.position_schemas import (
    CreateFundAmountPositionRequest,
    CreatePositionRequest,
    CreateStockPositionRequest,
    EstimatedFundValuationResponse,
    PositionInstrumentResponse,
    PositionListResponse,
    PositionResponse,
    PositionSummaryResponse,
    PositionValuationResponse,
    UpdateFundAmountPositionRequest,
    UpdatePositionRequest,
    UpdateStockPositionRequest,
)
from app.modules.portfolios.position_service import PositionError, PositionService, PositionView
from app.modules.portfolios.repository import InvestmentAccountRepository
from app.modules.portfolios.valuation import (
    EstimatedFundValuation,
    PositionValuation,
    PositionValuationService,
)

router = APIRouter(prefix="/positions", tags=["positions"])
summary_router = APIRouter(tags=["positions"])


@summary_router.get("/position-summary", response_model=PositionSummaryResponse)
async def get_position_summary(
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    position_repository: Annotated[PositionRepository, Depends(get_position_repository)],
    account_repository: Annotated[
        InvestmentAccountRepository,
        Depends(get_investment_account_repository),
    ],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    account_id: Annotated[UUID | None, Query(alias="accountId")] = None,
) -> PositionSummaryResponse:
    """返回全部账户或指定账户的权威口径持仓汇总。"""
    valuation_service = PositionValuationService(
        _service(position_repository, account_repository, instrument_repository),
        market_data_repository,
        MarketDataFreshnessPolicy(stock_refresh_seconds=settings.stock_refresh_seconds),
    )
    try:
        summary = await valuation_service.summarize(
            user_id=identity.id,
            account_id=account_id,
        )
    except PositionError as error:
        raise _api_error(error) from error
    return PositionSummaryResponse(
        account_id=summary.account_id,
        status=summary.status,
        position_count=summary.position_count,
        priced_position_count=summary.priced_position_count,
        stale_position_count=summary.stale_position_count,
        missing_price_position_ids=list(summary.missing_price_position_ids),
        total_cost=summary.total_cost,
        market_value=summary.market_value,
        holding_profit=summary.holding_profit,
        return_rate=summary.return_rate,
        calculated_at=summary.calculated_at,
    )


@router.get("", response_model=PositionListResponse)
async def list_positions(
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    position_repository: Annotated[PositionRepository, Depends(get_position_repository)],
    account_repository: Annotated[
        InvestmentAccountRepository,
        Depends(get_investment_account_repository),
    ],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    account_id: Annotated[UUID | None, Query(alias="accountId")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> PositionListResponse:
    """分页返回当前用户全部或指定账户的持仓。"""
    try:
        records, total = await _service(
            position_repository,
            account_repository,
            instrument_repository,
        ).list_positions(
            user_id=identity.id,
            account_id=account_id,
            page=page,
            page_size=page_size,
        )
    except PositionError as error:
        raise _api_error(error) from error
    valuation_service = PositionValuationService(
        _service(position_repository, account_repository, instrument_repository),
        market_data_repository,
        MarketDataFreshnessPolicy(stock_refresh_seconds=settings.stock_refresh_seconds),
    )
    valued_records = await valuation_service.value_positions(records)
    return PositionListResponse(
        items=[
            _response(
                item.position,
                valuation=item.valuation,
                estimated_valuation=item.estimated_valuation,
            )
            for item in valued_records
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PositionResponse)
async def create_position(
    payload: CreatePositionRequest,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    position_repository: Annotated[PositionRepository, Depends(get_position_repository)],
    account_repository: Annotated[
        InvestmentAccountRepository,
        Depends(get_investment_account_repository),
    ],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
) -> PositionResponse:
    """按录入模式为当前用户账户创建唯一股票或基金持仓。"""
    service = _service(
        position_repository,
        account_repository,
        instrument_repository,
        market_data_repository,
    )
    try:
        if isinstance(payload, CreateStockPositionRequest):
            record = await service.create_stock_position(
                user_id=identity.id,
                command=StockPositionCommand(
                    account_id=payload.account_id,
                    instrument_id=payload.instrument_id,
                    input_date=payload.input_date,
                    quantity=payload.quantity,
                    cost_input_mode=payload.cost_input_mode,
                    total_cost=payload.total_cost,
                    average_cost=payload.average_cost,
                ),
            )
        elif isinstance(payload, CreateFundAmountPositionRequest):
            record = await service.create_fund_amount_position(
                user_id=identity.id,
                command=FundAmountPositionCommand(
                    account_id=payload.account_id,
                    instrument_id=payload.instrument_id,
                    input_date=payload.input_date,
                    current_value=payload.current_value,
                    holding_profit=payload.holding_profit,
                ),
            )
        else:
            record = await service.create_fund_shares_position(
                user_id=identity.id,
                command=FundSharesPositionCommand(
                    account_id=payload.account_id,
                    instrument_id=payload.instrument_id,
                    input_date=payload.input_date,
                    quantity=payload.quantity,
                    cost_input_mode=payload.cost_input_mode,
                    total_cost=payload.total_cost,
                    average_cost=payload.average_cost,
                ),
            )
    except PositionError as error:
        raise _api_error(error) from error
    return _response(record)


@router.get("/{position_id}", response_model=PositionResponse)
async def get_position(
    position_id: UUID,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    position_repository: Annotated[PositionRepository, Depends(get_position_repository)],
    account_repository: Annotated[
        InvestmentAccountRepository,
        Depends(get_investment_account_repository),
    ],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
) -> PositionResponse:
    """返回当前用户拥有的指定持仓。"""
    try:
        record = await _service(
            position_repository,
            account_repository,
            instrument_repository,
        ).get_position(user_id=identity.id, position_id=position_id)
    except PositionError as error:
        raise _api_error(error) from error
    return _response(record)


@router.patch("/{position_id}", response_model=PositionResponse)
async def update_position(
    position_id: UUID,
    payload: UpdatePositionRequest,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    position_repository: Annotated[PositionRepository, Depends(get_position_repository)],
    account_repository: Annotated[
        InvestmentAccountRepository,
        Depends(get_investment_account_repository),
    ],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
) -> PositionResponse:
    """按录入模式和版本部分修改持仓或移动账户。"""
    service = _service(
        position_repository,
        account_repository,
        instrument_repository,
        market_data_repository,
    )
    try:
        if isinstance(payload, UpdateStockPositionRequest):
            record = await service.update_stock_position(
                user_id=identity.id,
                position_id=position_id,
                command=UpdateStockPositionCommand(
                    version=payload.version,
                    account_id=payload.account_id,
                    input_date=payload.input_date,
                    quantity=payload.quantity,
                    cost_input_mode=payload.cost_input_mode,
                    total_cost=payload.total_cost,
                    average_cost=payload.average_cost,
                ),
            )
        elif isinstance(payload, UpdateFundAmountPositionRequest):
            record = await service.update_fund_amount_position(
                user_id=identity.id,
                position_id=position_id,
                command=UpdateFundAmountPositionCommand(
                    version=payload.version,
                    account_id=payload.account_id,
                    input_date=payload.input_date,
                    current_value=payload.current_value,
                    holding_profit=payload.holding_profit,
                ),
            )
        else:
            record = await service.update_fund_shares_position(
                user_id=identity.id,
                position_id=position_id,
                command=UpdateFundSharesPositionCommand(
                    version=payload.version,
                    account_id=payload.account_id,
                    input_date=payload.input_date,
                    quantity=payload.quantity,
                    cost_input_mode=payload.cost_input_mode,
                    total_cost=payload.total_cost,
                    average_cost=payload.average_cost,
                ),
            )
    except PositionError as error:
        raise _api_error(error) from error
    return _response(record)


@router.delete("/{position_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_position(
    position_id: UUID,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    position_repository: Annotated[PositionRepository, Depends(get_position_repository)],
    account_repository: Annotated[
        InvestmentAccountRepository,
        Depends(get_investment_account_repository),
    ],
    instrument_repository: Annotated[
        InstrumentRepository,
        Depends(get_instrument_repository),
    ],
) -> Response:
    """删除当前用户指定持仓。"""
    try:
        await _service(
            position_repository,
            account_repository,
            instrument_repository,
        ).delete_position(user_id=identity.id, position_id=position_id)
    except PositionError as error:
        raise _api_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _service(
    positions: PositionRepository,
    accounts: InvestmentAccountRepository,
    instruments: InstrumentRepository,
    market_data: MarketDataRepository | None = None,
) -> PositionService:
    """使用同一请求事务中的 Repository 创建持仓服务。"""
    return PositionService(positions, accounts, instruments, market_data)


def _response(
    view: PositionView,
    *,
    valuation: PositionValuation | None = None,
    estimated_valuation: EstimatedFundValuation | None = None,
) -> PositionResponse:
    """把持仓领域视图裁剪为公开响应。"""
    record = view.record
    instrument = view.instrument
    return PositionResponse(
        id=record.id,
        account_id=record.account_id,
        instrument=PositionInstrumentResponse(
            id=instrument.id,
            asset_type=instrument.asset_type,
            market=instrument.market,
            exchange=instrument.exchange,
            ticker=instrument.ticker,
            name=instrument.name,
            currency=instrument.currency,
        ),
        input_mode=record.input_mode,
        cost_input_mode=record.cost_input_mode,
        input_date=record.input_date,
        input_quantity=record.input_quantity,
        input_total_cost=record.input_total_cost,
        input_average_cost=record.input_average_cost,
        input_current_value=record.input_current_value,
        input_holding_profit=record.input_holding_profit,
        quantity=record.quantity,
        total_cost=record.total_cost,
        average_cost=record.average_cost,
        quantity_estimated=record.quantity_estimated,
        quantity_basis_nav=record.quantity_basis_nav,
        quantity_basis_nav_date=record.quantity_basis_nav_date,
        valuation=(
            PositionValuationResponse(
                price=LatestPriceResponse(
                    price_type=valuation.price.price_type,
                    value=valuation.price.value,
                    as_of_date=valuation.price.as_of_date,
                    as_of_at=valuation.price.as_of_at,
                    fetched_at=valuation.price.fetched_at,
                    source=valuation.price.source,
                    freshness=valuation.freshness,
                ),
                market_value=valuation.market_value,
                holding_profit=valuation.holding_profit,
                return_rate=valuation.return_rate,
            )
            if valuation is not None
            else None
        ),
        estimated_valuation=(
            EstimatedFundValuationResponse(
                price=LatestPriceResponse(
                    price_type=estimated_valuation.price.price_type,
                    value=estimated_valuation.price.value,
                    as_of_date=estimated_valuation.price.as_of_date,
                    as_of_at=estimated_valuation.price.as_of_at,
                    fetched_at=estimated_valuation.price.fetched_at,
                    source=estimated_valuation.price.source,
                    freshness=estimated_valuation.freshness,
                ),
                market_value=estimated_valuation.market_value,
                holding_profit=estimated_valuation.holding_profit,
            )
            if estimated_valuation is not None
            else None
        ),
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _api_error(error: PositionError) -> ApiError:
    """把持仓领域错误映射为稳定 HTTP 状态。"""
    if error.code in {"POSITION_NOT_FOUND", "ACCOUNT_NOT_FOUND", "INSTRUMENT_NOT_FOUND"}:
        status_code = status.HTTP_404_NOT_FOUND
    elif error.code in {"POSITION_ALREADY_EXISTS", "POSITION_VERSION_CONFLICT"}:
        status_code = status.HTTP_409_CONFLICT
    else:
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return ApiError(
        status_code=status_code,
        code=error.code,
        message=error.message,
        details=error.details,
    )
