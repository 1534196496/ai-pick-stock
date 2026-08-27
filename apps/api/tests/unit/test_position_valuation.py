"""持仓金额必须使用正式价格的回归测试。"""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

from app.modules.instruments.domain import InstrumentRecord
from app.modules.instruments.enums import AssetType, Currency, Exchange, Market
from app.modules.market_data.domain import PriceRecord
from app.modules.market_data.enums import PriceType
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.service import MarketDataFreshnessPolicy
from app.modules.portfolios.domain import PositionRecord
from app.modules.portfolios.enums import PositionStatus
from app.modules.portfolios.position_service import PositionService, PositionView
from app.modules.portfolios.valuation import PositionValuationService, _is_price_for_today


def test_fund_market_value_uses_official_nav_when_estimate_is_newer() -> None:
    """盘中估算值即使更新，也不得替代正式净值计算持仓金额。"""
    instrument_id = uuid4()
    position_id = uuid4()
    now = datetime(2026, 8, 27, 8, tzinfo=UTC)
    position = PositionView(
        record=PositionRecord(
            id=position_id,
            group_id=uuid4(),
            instrument_id=instrument_id,
            quantity=Decimal("1000"),
            total_cost=Decimal("2000"),
            average_cost=Decimal("2"),
            realized_profit=Decimal("0"),
            status=PositionStatus.OPEN,
            first_trade_date=date(2026, 8, 1),
            last_trade_date=date(2026, 8, 1),
            version=1,
            created_at=now,
            updated_at=now,
        ),
        instrument=InstrumentRecord(
            id=instrument_id,
            asset_type=AssetType.FUND,
            market=Market.CN,
            exchange=Exchange.FUND_CN,
            ticker="000001",
            name="示例基金",
            currency=Currency.CNY,
            source="fixture",
            source_updated_at=now,
            updated_at=now,
        ),
    )
    estimated_price = PriceRecord(
        instrument_id=instrument_id,
        price_type=PriceType.FUND_ESTIMATED_NAV,
        value=Decimal("2.1000"),
        change_rate=Decimal("0.05"),
        as_of_date=None,
        as_of_at=now,
        fetched_at=now,
        source="estimated-fixture",
    )
    official_price = PriceRecord(
        instrument_id=instrument_id,
        price_type=PriceType.FUND_OFFICIAL_NAV,
        value=Decimal("2.0410"),
        change_rate=Decimal("0.01"),
        as_of_date=date(2026, 8, 27),
        as_of_at=None,
        fetched_at=now,
        source="official-fixture",
    )
    service = PositionValuationService(
        cast(PositionService, object()),
        cast(MarketDataRepository, object()),
        MarketDataFreshnessPolicy(stock_refresh_seconds=60),
    )

    result = service._value_positions(
        [position],
        price_map={instrument_id: [estimated_price, official_price]},
        now=now,
    )[0]

    assert result.valuation is not None
    assert result.valuation.price.price_type == PriceType.FUND_OFFICIAL_NAV
    assert result.valuation.settlement_updated is True
    assert result.valuation.market_value == Decimal("2041.00000000")
    assert result.estimated_valuation is not None
    assert result.estimated_valuation.market_value == Decimal("2100.00000000")


def test_qdii_uses_previous_weekday_as_expected_nav_date() -> None:
    """QDII 前一交易日净值应标记已更新，普通基金同日数据仍视为未更新。"""
    now = datetime(2026, 8, 27, 8, tzinfo=UTC)
    price = PriceRecord(
        instrument_id=uuid4(),
        price_type=PriceType.FUND_OFFICIAL_NAV,
        value=Decimal("2.3150"),
        change_rate=Decimal("0.02"),
        as_of_date=date(2026, 8, 26),
        as_of_at=None,
        fetched_at=now,
        source="official-fixture",
    )

    mainland = _fund_position(name="示例基金", instrument_id=price.instrument_id, now=now)
    qdii = _fund_position(name="示例基金(QDII)", instrument_id=price.instrument_id, now=now)

    assert _is_price_for_today(position=mainland, price=price, now=now) is False
    assert _is_price_for_today(position=qdii, price=price, now=now) is True


def _fund_position(*, name: str, instrument_id: UUID, now: datetime) -> PositionView:
    """构造用于结算日期判定的基金持仓。"""
    return PositionView(
        record=PositionRecord(
            id=uuid4(),
            group_id=uuid4(),
            instrument_id=instrument_id,
            quantity=Decimal("1000"),
            total_cost=Decimal("2000"),
            average_cost=Decimal("2"),
            realized_profit=Decimal("0"),
            status=PositionStatus.OPEN,
            first_trade_date=date(2026, 8, 1),
            last_trade_date=date(2026, 8, 1),
            version=1,
            created_at=now,
            updated_at=now,
        ),
        instrument=InstrumentRecord(
            id=instrument_id,
            asset_type=AssetType.FUND,
            market=Market.CN,
            exchange=Exchange.FUND_CN,
            ticker="000001",
            name=name,
            currency=Currency.CNY,
            source="fixture",
            source_updated_at=now,
            updated_at=now,
        ),
    )
