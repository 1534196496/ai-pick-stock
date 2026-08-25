"""资产主数据持久化与 Worker 查询边界。"""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import case, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.instruments.domain import InstrumentRecord
from app.modules.instruments.enums import AssetType, Exchange, Market
from app.modules.instruments.models import Instrument
from app.modules.market_data.providers.schemas import ProviderInstrument, StockQuoteRequest


class InstrumentRepository:
    """批量写入标准主数据并为行情任务返回活跃标的。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定 Worker 或 API 事务会话。"""
        self._session = session

    async def upsert_many(self, instruments: Sequence[ProviderInstrument]) -> int:
        """按资产联合身份幂等新增或更新名称、交易所和来源。"""
        if not instruments:
            return 0
        values = [
            {
                "asset_type": item.asset_type,
                "market": item.market,
                "exchange": item.exchange,
                "ticker": item.ticker,
                "name": item.name,
                "currency": item.currency,
                "active": True,
                "source": item.source,
                "source_updated_at": item.source_updated_at,
            }
            for item in instruments
        ]
        statement = insert(Instrument).values(values)
        statement = statement.on_conflict_do_update(
            constraint="uq_instruments_identity",
            set_={
                "exchange": statement.excluded.exchange,
                "name": statement.excluded.name,
                "currency": statement.excluded.currency,
                "active": True,
                "source": statement.excluded.source,
                "source_updated_at": statement.excluded.source_updated_at,
                "updated_at": func.now(),
            },
        )
        await self._session.execute(statement)
        return len(values)

    async def list_stock_quote_requests(self) -> list[StockQuoteRequest]:
        """只返回被任一用户持仓或自选引用的活跃股票。"""
        rows = await self._list_tracked(asset_type=AssetType.STOCK)
        return [
            StockQuoteRequest(ticker=str(ticker), exchange=Exchange(str(exchange)))
            for ticker, exchange in rows
        ]

    async def list_active_fund_tickers(self) -> list[str]:
        """只返回被任一用户持仓或自选引用的活跃基金代码。"""
        return [str(ticker) for ticker, _ in await self._list_tracked(asset_type=AssetType.FUND)]

    async def search_active(
        self,
        *,
        query: str | None,
        asset_type: AssetType | None,
        offset: int,
        limit: int,
    ) -> tuple[list[InstrumentRecord], int]:
        """按代码或名称搜索一期活跃资产，并返回稳定分页结果。"""
        conditions = [Instrument.active.is_(True), Instrument.market == Market.CN]
        if asset_type is not None:
            conditions.append(Instrument.asset_type == asset_type)
        if query is not None:
            conditions.append(
                or_(
                    Instrument.ticker.icontains(query, autoescape=True),
                    Instrument.name.icontains(query, autoescape=True),
                )
            )

        statement = select(Instrument).where(*conditions)
        if query is not None:
            statement = statement.order_by(
                case(
                    (func.lower(Instrument.ticker) == query.casefold(), 0),
                    (Instrument.ticker.istartswith(query, autoescape=True), 1),
                    (Instrument.name.istartswith(query, autoescape=True), 2),
                    else_=3,
                ),
                Instrument.asset_type,
                Instrument.ticker,
                Instrument.id,
            )
        else:
            statement = statement.order_by(
                Instrument.asset_type,
                Instrument.ticker,
                Instrument.id,
            )
        statement = statement.offset(offset).limit(limit)
        instruments = (await self._session.scalars(statement)).all()
        total = await self._session.scalar(
            select(func.count()).select_from(Instrument).where(*conditions)
        )
        return [self._to_record(item) for item in instruments], int(total or 0)

    async def get_active(self, *, instrument_id: UUID) -> InstrumentRecord | None:
        """按 ID 读取一期活跃资产，不暴露停用或其他市场资产。"""
        instrument = await self._session.scalar(
            select(Instrument).where(
                Instrument.id == instrument_id,
                Instrument.active.is_(True),
                Instrument.market == Market.CN,
            )
        )
        return self._to_record(instrument) if instrument is not None else None

    async def get_many(self, *, instrument_ids: Sequence[UUID]) -> list[InstrumentRecord]:
        """批量读取已被业务记录引用的资产，包括后续可能停用的标的。"""
        if not instrument_ids:
            return []
        instruments = (
            await self._session.scalars(
                select(Instrument)
                .where(Instrument.id.in_(instrument_ids))
                .order_by(Instrument.asset_type, Instrument.ticker, Instrument.id)
            )
        ).all()
        return [self._to_record(instrument) for instrument in instruments]

    async def _list_tracked(self, *, asset_type: AssetType) -> list[tuple[object, object]]:
        """兼容后续业务表逐步上线，表不存在时不触发任何全量行情请求。"""
        relation_row = (
            await self._session.execute(
                text(
                    "SELECT to_regclass('public.positions'), "
                    "to_regclass('public.watchlist_items')"
                )
            )
        ).one()
        relation_names = ("positions", "watchlist_items")
        available = [
            name for name, relation in zip(relation_names, relation_row, strict=True) if relation
        ]
        if not available:
            return []
        references = " UNION ".join(
            f"SELECT instrument_id FROM {relation_name}" for relation_name in available
        )
        rows = await self._session.execute(
            text(
                "SELECT i.ticker, i.exchange FROM instruments i "
                f"WHERE i.id IN ({references}) "
                "AND i.asset_type = :asset_type AND i.market = :market "
                "AND i.active IS TRUE ORDER BY i.ticker"
            ),
            {"asset_type": asset_type.value, "market": Market.CN.value},
        )
        return list(rows.tuples())

    @staticmethod
    def _to_record(instrument: Instrument) -> InstrumentRecord:
        """把 ORM 资产转换为不携带数据库状态的领域记录。"""
        return InstrumentRecord(
            id=instrument.id,
            asset_type=instrument.asset_type,
            market=instrument.market,
            exchange=instrument.exchange,
            ticker=instrument.ticker,
            name=instrument.name,
            currency=instrument.currency,
            source=instrument.source,
            source_updated_at=instrument.source_updated_at,
            updated_at=instrument.updated_at,
        )
