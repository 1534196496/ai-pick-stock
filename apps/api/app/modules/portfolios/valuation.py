"""持仓权威价格选择和组合汇总规则。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from app.modules.instruments.enums import AssetType
from app.modules.market_data.domain import DataFreshness, PriceRecord
from app.modules.market_data.enums import PriceType
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.service import MarketDataFreshnessPolicy
from app.modules.portfolios.money import round_decimal
from app.modules.portfolios.position_service import PositionService, PositionView


class ValuationStatus(StrEnum):
    """表示组合估值是否完整、陈旧或为空。"""

    COMPLETE = "COMPLETE"
    STALE = "STALE"
    INCOMPLETE = "INCOMPLETE"
    EMPTY = "EMPTY"


@dataclass(frozen=True, slots=True)
class PositionValuation:
    """保存单个持仓使用的权威价格和计算结果。"""

    position_id: UUID
    price: PriceRecord
    freshness: DataFreshness
    market_value: Decimal
    holding_profit: Decimal
    return_rate: Decimal


@dataclass(frozen=True, slots=True)
class EstimatedFundValuation:
    """保存不进入权威汇总的基金盘中估算结果。"""

    position_id: UUID
    price: PriceRecord
    freshness: DataFreshness
    market_value: Decimal
    holding_profit: Decimal


@dataclass(frozen=True, slots=True)
class ValuedPosition:
    """组合持仓视图和可选权威估值，缺价时估值为空。"""

    position: PositionView
    valuation: PositionValuation | None
    estimated_valuation: EstimatedFundValuation | None


@dataclass(frozen=True, slots=True)
class PositionSummary:
    """保存组合总成本、完整性计数和可选权威估值。"""

    account_id: UUID | None
    status: ValuationStatus
    position_count: int
    priced_position_count: int
    stale_position_count: int
    missing_price_position_ids: tuple[UUID, ...]
    total_cost: Decimal
    market_value: Decimal | None
    holding_profit: Decimal | None
    return_rate: Decimal | None
    calculated_at: datetime


class PositionValuationService:
    """只使用本地股票最新价和基金官方单位净值计算权威汇总。"""

    def __init__(
        self,
        position_service: PositionService,
        market_data_repository: MarketDataRepository,
        freshness_policy: MarketDataFreshnessPolicy,
    ) -> None:
        """注入用户持仓服务、本地行情读取边界和新鲜度规则。"""
        self._positions = position_service
        self._market_data = market_data_repository
        self._freshness = freshness_policy

    async def summarize(
        self,
        *,
        user_id: UUID,
        account_id: UUID | None,
    ) -> PositionSummary:
        """缺少任一权威价格时拒绝生成不完整的总市值和收益。"""
        positions, total = await self._positions.list_positions(
            user_id=user_id,
            account_id=account_id,
            page=1,
            page_size=100,
        )
        if total > len(positions):
            positions, _ = await self._positions.list_positions(
                user_id=user_id,
                account_id=account_id,
                page=1,
                page_size=total,
            )
        now = datetime.now(UTC)
        total_cost = round_decimal(
            sum((item.record.total_cost for item in positions), start=Decimal("0")),
            field="组合总成本",
        )
        if not positions:
            return PositionSummary(
                account_id=account_id,
                status=ValuationStatus.EMPTY,
                position_count=0,
                priced_position_count=0,
                stale_position_count=0,
                missing_price_position_ids=(),
                total_cost=total_cost,
                market_value=Decimal("0.00000000"),
                holding_profit=Decimal("0.00000000"),
                return_rate=None,
                calculated_at=now,
            )

        price_map = await self._market_data.latest_prices(
            instrument_ids=[item.record.instrument_id for item in positions]
        )
        valued_positions = self._value_positions(positions, price_map=price_map, now=now)
        valuations: list[PositionValuation] = []
        missing: list[UUID] = []
        for item in valued_positions:
            if item.valuation is None:
                missing.append(item.position.record.id)
            else:
                valuations.append(item.valuation)

        stale_count = sum(
            valuation.freshness == DataFreshness.STALE for valuation in valuations
        )
        if missing:
            return PositionSummary(
                account_id=account_id,
                status=ValuationStatus.INCOMPLETE,
                position_count=len(positions),
                priced_position_count=len(valuations),
                stale_position_count=stale_count,
                missing_price_position_ids=tuple(missing),
                total_cost=total_cost,
                market_value=None,
                holding_profit=None,
                return_rate=None,
                calculated_at=now,
            )

        market_value = round_decimal(
            sum((item.market_value for item in valuations), start=Decimal("0")),
            field="组合总市值",
        )
        holding_profit = round_decimal(market_value - total_cost, field="组合持有收益")
        return_rate = round_decimal(holding_profit / total_cost, field="组合收益率")
        return PositionSummary(
            account_id=account_id,
            status=ValuationStatus.STALE if stale_count else ValuationStatus.COMPLETE,
            position_count=len(positions),
            priced_position_count=len(valuations),
            stale_position_count=stale_count,
            missing_price_position_ids=(),
            total_cost=total_cost,
            market_value=market_value,
            holding_profit=holding_profit,
            return_rate=return_rate,
            calculated_at=now,
        )

    async def value_positions(self, positions: list[PositionView]) -> list[ValuedPosition]:
        """批量读取本地权威价格并估算列表中的每个持仓。"""
        now = datetime.now(UTC)
        price_map = await self._market_data.latest_prices(
            instrument_ids=[item.record.instrument_id for item in positions]
        )
        return self._value_positions(positions, price_map=price_map, now=now)

    def _value_positions(
        self,
        positions: list[PositionView],
        *,
        price_map: dict[UUID, list[PriceRecord]],
        now: datetime,
    ) -> list[ValuedPosition]:
        """使用一次批量行情结果生成顺序与输入一致的估值列表。"""
        return [
            ValuedPosition(
                position=item,
                valuation=self._value_position(
                    item,
                    prices=price_map.get(item.record.instrument_id, []),
                    now=now,
                ),
                estimated_valuation=self._estimate_fund_position(
                    item,
                    prices=price_map.get(item.record.instrument_id, []),
                    now=now,
                ),
            )
            for item in positions
        ]

    def _value_position(
        self,
        position: PositionView,
        *,
        prices: list[PriceRecord],
        now: datetime,
    ) -> PositionValuation | None:
        """按资产类型选择权威价格，缺数量或价格时返回不可估值。"""
        quantity = position.record.quantity
        if quantity is None:
            return None
        expected_type = (
            PriceType.STOCK_LAST
            if position.instrument.asset_type == AssetType.STOCK
            else PriceType.FUND_OFFICIAL_NAV
        )
        price = next((item for item in prices if item.price_type == expected_type), None)
        if price is None:
            return None
        market_value = round_decimal(quantity * price.value, field="持仓市值")
        holding_profit = round_decimal(
            market_value - position.record.total_cost,
            field="持仓收益",
        )
        return PositionValuation(
            position_id=position.record.id,
            price=price,
            freshness=self._freshness.for_price(price, now=now),
            market_value=market_value,
            holding_profit=holding_profit,
            return_rate=round_decimal(
                holding_profit / position.record.total_cost,
                field="持仓收益率",
            ),
        )

    def _estimate_fund_position(
        self,
        position: PositionView,
        *,
        prices: list[PriceRecord],
        now: datetime,
    ) -> EstimatedFundValuation | None:
        """基金有份额和估算净值时单独计算估算市值，不参与权威汇总。"""
        quantity = position.record.quantity
        if position.instrument.asset_type != AssetType.FUND or quantity is None:
            return None
        price = next(
            (item for item in prices if item.price_type == PriceType.FUND_ESTIMATED_NAV),
            None,
        )
        if price is None:
            return None
        market_value = round_decimal(quantity * price.value, field="基金估算市值")
        return EstimatedFundValuation(
            position_id=position.record.id,
            price=price,
            freshness=self._freshness.for_price(price, now=now),
            market_value=market_value,
            holding_profit=round_decimal(
                market_value - position.record.total_cost,
                field="基金估算收益",
            ),
        )
