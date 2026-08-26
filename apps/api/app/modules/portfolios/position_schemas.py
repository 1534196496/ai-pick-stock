"""股票持仓 API 请求与响应契约。"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BeforeValidator, Field, PlainSerializer, WithJsonSchema, model_validator

from app.api.schemas import ApiModel
from app.modules.instruments.enums import AssetType, Currency, Exchange, Market
from app.modules.instruments.schemas import LatestPriceResponse
from app.modules.portfolios.enums import CostInputMode, PositionInputMode, PositionStatus
from app.modules.portfolios.valuation import ValuationStatus


def parse_financial_decimal(value: Any) -> Decimal:
    """只接受十进制字符串或整数，拒绝二进制浮点进入财务边界。"""
    if isinstance(value, (bool, float)):
        raise ValueError("财务值必须使用十进制字符串")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("财务值不是有效十进制数") from error


FinancialDecimal = Annotated[
    Decimal,
    BeforeValidator(parse_financial_decimal),
    PlainSerializer(lambda value: format(value, "f"), return_type=str),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+(\.\d+)?$"}),
]


class PositionInstrumentResponse(ApiModel):
    """返回持仓列表稳定需要的资产身份。"""

    id: UUID
    asset_type: AssetType
    market: Market
    exchange: Exchange
    ticker: str
    name: str
    currency: Currency


class PositionValuationResponse(ApiModel):
    """返回单只持仓使用的权威价格及精确估值。"""

    price: LatestPriceResponse
    market_value: FinancialDecimal
    today_profit: FinancialDecimal | None = None
    holding_profit: FinancialDecimal
    return_rate: FinancialDecimal


class EstimatedFundValuationResponse(ApiModel):
    """返回明确标记且不进入组合汇总的基金盘中估算。"""

    price: LatestPriceResponse
    market_value: FinancialDecimal
    today_profit: FinancialDecimal | None = None
    holding_profit: FinancialDecimal
    return_rate: FinancialDecimal


class PositionResponse(ApiModel):
    """返回精简持仓投影、动态估值、资产身份和乐观锁版本。"""

    id: UUID
    group_id: UUID
    instrument: PositionInstrumentResponse
    quantity: FinancialDecimal | None
    total_cost: FinancialDecimal
    average_cost: FinancialDecimal | None
    realized_profit: FinancialDecimal
    status: PositionStatus
    first_trade_date: date
    last_trade_date: date
    valuation: PositionValuationResponse | None = None
    estimated_valuation: EstimatedFundValuationResponse | None = None
    version: int
    created_at: datetime
    updated_at: datetime


class PositionListResponse(ApiModel):
    """返回当前用户持仓的稳定分页列表。"""

    items: list[PositionResponse]
    page: int
    page_size: int
    total: int


class PositionSummaryResponse(ApiModel):
    """返回组合成本、价格完整性和可选权威估值汇总。"""

    group_id: UUID | None
    status: ValuationStatus
    position_count: int
    priced_position_count: int
    stale_position_count: int
    missing_price_position_ids: list[UUID]
    total_cost: FinancialDecimal
    market_value: FinancialDecimal | None
    holding_profit: FinancialDecimal | None
    return_rate: FinancialDecimal | None
    intraday_market_value: FinancialDecimal | None
    intraday_holding_profit: FinancialDecimal | None
    intraday_return_rate: FinancialDecimal | None
    today_profit: FinancialDecimal | None = None
    today_profit_position_count: int = 0
    estimated_fund_position_count: int
    calculated_at: datetime


class CreateStockPositionRequest(ApiModel):
    """接收股票数量及总成本或平均成本二选一输入。"""

    input_mode: Literal[PositionInputMode.STOCK_SHARES]
    group_id: UUID
    instrument_id: UUID
    input_date: date
    quantity: FinancialDecimal
    cost_input_mode: CostInputMode
    total_cost: FinancialDecimal | None = None
    average_cost: FinancialDecimal | None = None

    @model_validator(mode="after")
    def validate_cost_shape(self) -> "CreateStockPositionRequest":
        """要求成本字段与所选输入方式严格一致。"""
        if self.cost_input_mode == CostInputMode.TOTAL_COST:
            valid = self.total_cost is not None and self.average_cost is None
        else:
            valid = self.average_cost is not None and self.total_cost is None
        if not valid:
            raise ValueError("成本输入方式与填写字段不一致")
        return self


class UpdateStockPositionRequest(ApiModel):
    """接收带版本号的股票持仓部分更新。"""

    input_mode: Literal[PositionInputMode.STOCK_SHARES]
    version: int = Field(ge=1)
    group_id: UUID | None = None
    input_date: date | None = None
    quantity: FinancialDecimal | None = None
    cost_input_mode: CostInputMode | None = None
    total_cost: FinancialDecimal | None = None
    average_cost: FinancialDecimal | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "UpdateStockPositionRequest":
        """拒绝空 PATCH、显式清空和互相冲突的成本字段。"""
        editable = {
            "group_id",
            "input_date",
            "quantity",
            "cost_input_mode",
            "total_cost",
            "average_cost",
        }
        changed = self.model_fields_set & editable
        if not changed:
            raise ValueError("至少提供一个待修改字段")
        if any(getattr(self, field) is None for field in changed):
            raise ValueError("持仓字段不能显式清空")
        if self.total_cost is not None and self.average_cost is not None:
            raise ValueError("总成本和平均成本只能填写一项")
        if (self.cost_input_mode == CostInputMode.TOTAL_COST and self.average_cost is not None) or (
            self.cost_input_mode == CostInputMode.AVERAGE_COST and self.total_cost is not None
        ):
            raise ValueError("成本输入方式与填写字段不一致")
        return self


class CreateFundAmountPositionRequest(ApiModel):
    """接收基金当前金额和可正可负的持有收益。"""

    input_mode: Literal[PositionInputMode.FUND_AMOUNT]
    group_id: UUID
    instrument_id: UUID
    input_date: date
    current_value: FinancialDecimal
    holding_profit: FinancialDecimal


class CreateFundSharesPositionRequest(ApiModel):
    """接收基金份额及总成本或平均成本二选一输入。"""

    input_mode: Literal[PositionInputMode.FUND_SHARES]
    group_id: UUID
    instrument_id: UUID
    input_date: date
    quantity: FinancialDecimal
    cost_input_mode: CostInputMode
    total_cost: FinancialDecimal | None = None
    average_cost: FinancialDecimal | None = None

    @model_validator(mode="after")
    def validate_cost_shape(self) -> "CreateFundSharesPositionRequest":
        """要求成本字段与所选输入方式严格一致。"""
        if self.cost_input_mode == CostInputMode.TOTAL_COST:
            valid = self.total_cost is not None and self.average_cost is None
        else:
            valid = self.average_cost is not None and self.total_cost is None
        if not valid:
            raise ValueError("成本输入方式与填写字段不一致")
        return self


class UpdateFundAmountPositionRequest(ApiModel):
    """接收带版本号的基金金额模式部分更新。"""

    input_mode: Literal[PositionInputMode.FUND_AMOUNT]
    version: int = Field(ge=1)
    group_id: UUID | None = None
    input_date: date | None = None
    current_value: FinancialDecimal | None = None
    holding_profit: FinancialDecimal | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "UpdateFundAmountPositionRequest":
        """拒绝空 PATCH 或显式清空基金金额字段。"""
        editable = {"group_id", "input_date", "current_value", "holding_profit"}
        changed = self.model_fields_set & editable
        if not changed:
            raise ValueError("至少提供一个待修改字段")
        if any(getattr(self, field) is None for field in changed):
            raise ValueError("持仓字段不能显式清空")
        return self


class UpdateFundSharesPositionRequest(ApiModel):
    """接收带版本号的基金份额模式部分更新。"""

    input_mode: Literal[PositionInputMode.FUND_SHARES]
    version: int = Field(ge=1)
    group_id: UUID | None = None
    input_date: date | None = None
    quantity: FinancialDecimal | None = None
    cost_input_mode: CostInputMode | None = None
    total_cost: FinancialDecimal | None = None
    average_cost: FinancialDecimal | None = None

    @model_validator(mode="after")
    def validate_patch(self) -> "UpdateFundSharesPositionRequest":
        """拒绝空 PATCH、显式清空和互相冲突的成本字段。"""
        editable = {
            "group_id",
            "input_date",
            "quantity",
            "cost_input_mode",
            "total_cost",
            "average_cost",
        }
        changed = self.model_fields_set & editable
        if not changed:
            raise ValueError("至少提供一个待修改字段")
        if any(getattr(self, field) is None for field in changed):
            raise ValueError("持仓字段不能显式清空")
        if self.total_cost is not None and self.average_cost is not None:
            raise ValueError("总成本和平均成本只能填写一项")
        if (self.cost_input_mode == CostInputMode.TOTAL_COST and self.average_cost is not None) or (
            self.cost_input_mode == CostInputMode.AVERAGE_COST and self.total_cost is not None
        ):
            raise ValueError("成本输入方式与填写字段不一致")
        return self


CreatePositionRequest = Annotated[
    CreateStockPositionRequest | CreateFundAmountPositionRequest | CreateFundSharesPositionRequest,
    Field(discriminator="input_mode"),
]
UpdatePositionRequest = Annotated[
    UpdateStockPositionRequest | UpdateFundAmountPositionRequest | UpdateFundSharesPositionRequest,
    Field(discriminator="input_mode"),
]
