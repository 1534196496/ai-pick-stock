"""资产主数据持久化与 Worker 查询边界。"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.instruments.enums import AssetType
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
                "updated_at": statement.excluded.source_updated_at,
            },
        )
        await self._session.execute(statement)
        return len(values)

    async def list_stock_quote_requests(self) -> list[StockQuoteRequest]:
        """返回活跃股票的明确 ticker 与交易所组合。"""
        rows = (
            await self._session.execute(
                select(Instrument.ticker, Instrument.exchange).where(
                    Instrument.asset_type == AssetType.STOCK,
                    Instrument.active.is_(True),
                )
            )
        ).all()
        return [StockQuoteRequest(ticker=ticker, exchange=exchange) for ticker, exchange in rows]

    async def list_active_fund_tickers(self) -> list[str]:
        """返回活跃基金代码供官方或估算净值任务使用。"""
        return list(
            await self._session.scalars(
                select(Instrument.ticker).where(
                    Instrument.asset_type == AssetType.FUND,
                    Instrument.active.is_(True),
                )
            )
        )
