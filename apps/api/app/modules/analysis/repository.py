"""AI 分析访问控制、持仓上下文与最近报告持久化。"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analysis.dataset import AnalysisDataset, HoldingContext
from app.modules.analysis.models import AIAnalysisReport
from app.modules.analysis.schemas import GeneratedAnalysis
from app.modules.instruments.domain import InstrumentRecord
from app.modules.instruments.models import Instrument
from app.modules.portfolios.enums import PositionStatus
from app.modules.portfolios.models import Position
from app.modules.watchlists.models import WatchlistGroup, WatchlistItem


class AnalysisRepository:
    """只允许用户分析自己持仓或自选中的标的。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定请求级数据库事务。"""
        self._session = session

    async def get_tracked_instrument(
        self,
        *,
        user_id: UUID,
        instrument_id: UUID,
    ) -> InstrumentRecord | None:
        """返回用户持仓或自选已引用的标的，否则返回空。"""
        position_exists = exists(
            select(Position.id)
            .join(WatchlistGroup, WatchlistGroup.id == Position.group_id)
            .where(
                Position.instrument_id == instrument_id,
                WatchlistGroup.user_id == user_id,
            )
        )
        watchlist_exists = exists(
            select(WatchlistItem.id)
            .join(WatchlistGroup, WatchlistGroup.id == WatchlistItem.group_id)
            .where(
                WatchlistItem.instrument_id == instrument_id,
                WatchlistGroup.user_id == user_id,
            )
        )
        instrument = await self._session.scalar(
            select(Instrument).where(
                Instrument.id == instrument_id,
                Instrument.active.is_(True),
                or_(position_exists, watchlist_exists),
            )
        )
        return self._to_instrument(instrument) if instrument is not None else None

    async def holding_context(
        self,
        *,
        user_id: UUID,
        instrument_id: UUID,
    ) -> HoldingContext | None:
        """聚合用户全部分组中同一标的的开放持仓数量和成本。"""
        row = (
            await self._session.execute(
                select(
                    func.sum(Position.quantity),
                    func.sum(Position.total_cost),
                )
                .join(WatchlistGroup, WatchlistGroup.id == Position.group_id)
                .where(
                    WatchlistGroup.user_id == user_id,
                    Position.instrument_id == instrument_id,
                    Position.status == PositionStatus.OPEN,
                    Position.quantity.is_not(None),
                )
            )
        ).one()
        quantity, total_cost = row
        if quantity is None or total_cost is None:
            return None
        return HoldingContext(quantity=Decimal(quantity), total_cost=Decimal(total_cost))

    async def latest_report(
        self,
        *,
        user_id: UUID,
        instrument_id: UUID,
    ) -> AIAnalysisReport | None:
        """读取用户对指定标的最近一次成功分析。"""
        return cast(
            AIAnalysisReport | None,
            await self._session.scalar(
                select(AIAnalysisReport).where(
                    AIAnalysisReport.user_id == user_id,
                    AIAnalysisReport.instrument_id == instrument_id,
                )
            ),
        )

    async def save_report(
        self,
        *,
        user_id: UUID,
        instrument_id: UUID,
        provider: str,
        model: str,
        dataset: AnalysisDataset,
        content: GeneratedAnalysis,
    ) -> AIAnalysisReport:
        """新增或覆盖最近报告，不保留重复历史以控制个人站点体积。"""
        report = await self.latest_report(user_id=user_id, instrument_id=instrument_id)
        values = {
            "provider": provider,
            "model": model,
            "data_as_of": dataset.data_as_of,
            "data_sources": list(dataset.data_sources),
            "metrics": [
                {"label": metric.label, "value": metric.value} for metric in dataset.metrics
            ],
            "content": content.model_dump(mode="json"),
            "generated_at": datetime.now(UTC),
        }
        if report is None:
            report = AIAnalysisReport(
                user_id=user_id,
                instrument_id=instrument_id,
                **values,
            )
            self._session.add(report)
        else:
            for key, value in values.items():
                setattr(report, key, value)
        await self._session.flush()
        return report

    @staticmethod
    def _to_instrument(instrument: Instrument) -> InstrumentRecord:
        """把 ORM 标的转换为不携带数据库状态的领域记录。"""
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
