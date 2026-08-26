"""外部主数据、股票价格与基金净值边界模型。"""

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.modules.instruments.enums import AssetType, Currency, Exchange, Market


def parse_decimal(value: Any) -> Decimal:
    """把第三方字符串或整数转换为 Decimal，并拒绝布尔和二进制浮点。"""
    if isinstance(value, (bool, float)):
        raise ValueError("财务值必须使用十进制字符串或整数")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("财务值不是有效十进制数") from error


PositiveDecimal = Annotated[Decimal, BeforeValidator(parse_decimal), Field(gt=0)]
SignedRate = Annotated[
    Decimal,
    BeforeValidator(parse_decimal),
    Field(ge=Decimal("-10"), le=Decimal("10")),
]


class ProviderModel(BaseModel):
    """禁止第三方静默增加字段，确保响应变更立即触发契约失败。"""

    model_config = ConfigDict(extra="forbid")


class ProviderInstrument(ProviderModel):
    """表示经过适配器规范化的股票或基金主数据。"""

    asset_type: AssetType
    market: Market
    exchange: Exchange
    ticker: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=160)
    currency: Currency
    source: str = Field(min_length=1, max_length=80)
    source_updated_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_asset_exchange(self) -> "ProviderInstrument":
        """保证股票和基金使用各自合法交易所边界。"""
        stock_exchanges = {Exchange.SSE, Exchange.SZSE, Exchange.BSE}
        if self.asset_type is AssetType.STOCK and self.exchange not in stock_exchanges:
            raise ValueError("股票必须属于 SSE、SZSE 或 BSE")
        if self.asset_type is AssetType.FUND and self.exchange is not Exchange.FUND_CN:
            raise ValueError("基金必须属于 FUND_CN")
        return self


class StockQuoteRequest(ProviderModel):
    """用明确交易所和 ticker 请求股票行情，避免代码规则成为身份权威。"""

    ticker: str = Field(min_length=1, max_length=32)
    exchange: Exchange


class StockPriceSnapshot(ProviderModel):
    """表示 A 股最新成交价格和精确业务时点。"""

    ticker: str = Field(min_length=1, max_length=32)
    value: PositiveDecimal
    change_rate: SignedRate
    as_of_at: AwareDatetime
    fetched_at: AwareDatetime
    source: str = Field(min_length=1, max_length=80)


class FundOfficialNavSnapshot(ProviderModel):
    """表示基金官方单位净值，并单独保留可选累计净值。"""

    ticker: str = Field(min_length=1, max_length=32)
    unit_nav: PositiveDecimal
    accumulated_nav: PositiveDecimal | None = None
    change_rate: SignedRate | None = None
    nav_date: date
    fetched_at: AwareDatetime
    source: str = Field(min_length=1, max_length=80)


class FundEstimatedNavSnapshot(ProviderModel):
    """表示非权威盘中估算净值及其业务时点。"""

    ticker: str = Field(min_length=1, max_length=32)
    estimated_nav: PositiveDecimal
    change_rate: SignedRate
    as_of_at: AwareDatetime
    fetched_at: AwareDatetime
    source: str = Field(min_length=1, max_length=80)
