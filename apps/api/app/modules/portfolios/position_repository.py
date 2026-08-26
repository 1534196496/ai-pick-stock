"""用户隔离的持仓投影与交易事实持久化边界。"""

from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.instruments.models import Instrument
from app.modules.portfolios.domain import PositionDraft, PositionRecord
from app.modules.portfolios.enums import (
    PositionStatus,
    TransactionStatus,
    TransactionType,
)
from app.modules.portfolios.models import Position, PositionTransaction
from app.modules.watchlists.models import WatchlistGroup


class PositionAlreadyExistsError(Exception):
    """表示同一分组已经持有同一标的。"""


class PositionRepository:
    """以交易事实更新精简持仓投影，并强制校验用户归属。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定由 API 服务管理事务边界的数据库会话。"""
        self._session = session

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        group_id: UUID | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[PositionRecord], int]:
        """按当前用户和可选分组稳定分页读取持仓。"""
        conditions = [WatchlistGroup.user_id == user_id]
        if group_id is not None:
            conditions.append(Position.group_id == group_id)
        base = (
            select(Position)
            .join(WatchlistGroup, WatchlistGroup.id == Position.group_id)
            .where(*conditions)
        )
        positions = (
            await self._session.scalars(
                base.order_by(Position.created_at, Position.id).offset(offset).limit(limit)
            )
        ).all()
        total = await self._session.scalar(
            select(func.count())
            .select_from(Position)
            .join(WatchlistGroup, WatchlistGroup.id == Position.group_id)
            .where(*conditions)
        )
        return [self._to_record(position) for position in positions], int(total or 0)

    async def get_for_user(
        self,
        *,
        user_id: UUID,
        position_id: UUID,
    ) -> PositionRecord | None:
        """按当前用户读取单个持仓，越权和不存在均返回空。"""
        position = await self._owned_position(user_id=user_id, position_id=position_id)
        return self._to_record(position) if position is not None else None

    async def find_by_group_instrument_for_user(
        self,
        *,
        user_id: UUID,
        group_id: UUID,
        instrument_id: UUID,
    ) -> PositionRecord | None:
        """为重复创建提示查找当前用户分组中的已有持仓。"""
        position = await self._session.scalar(
            select(Position)
            .join(WatchlistGroup, WatchlistGroup.id == Position.group_id)
            .where(
                Position.group_id == group_id,
                Position.instrument_id == instrument_id,
                WatchlistGroup.user_id == user_id,
            )
        )
        return self._to_record(position) if position is not None else None

    async def create_for_user(
        self,
        *,
        user_id: UUID,
        draft: PositionDraft,
    ) -> PositionRecord | None:
        """创建当前持仓投影，并同步写入一笔期初交易。"""
        if not await self._references_valid(user_id=user_id, draft=draft):
            return None
        position = Position(
            group_id=draft.group_id,
            instrument_id=draft.instrument_id,
            quantity=draft.quantity,
            total_cost=draft.total_cost,
            average_cost=draft.average_cost,
            realized_profit=Decimal("0"),
            status=PositionStatus.OPEN,
            first_trade_date=draft.trade_date,
            last_trade_date=draft.trade_date,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(position)
                await self._session.flush()
                self._session.add(
                    PositionTransaction(
                        position_id=position.id,
                        transaction_type=TransactionType.OPENING,
                        status=TransactionStatus.CONFIRMED,
                        trade_date=draft.trade_date,
                        quantity_change=draft.quantity,
                        cash_amount=draft.total_cost,
                        fee_amount=Decimal("0"),
                    )
                )
                await self._session.flush()
        except IntegrityError as error:
            if self._constraint_name(error) == "uq_positions_group_instrument":
                raise PositionAlreadyExistsError from error
            raise
        return self._to_record(position)

    async def update_for_user(
        self,
        *,
        user_id: UUID,
        position_id: UUID,
        version: int,
        draft: PositionDraft,
        changed_at: datetime,
    ) -> PositionRecord | None:
        """以乐观锁更新投影，并把数量和成本差额记为调整交易。"""
        current = await self._owned_position(user_id=user_id, position_id=position_id)
        if current is None or current.version != version:
            return None
        if not await self._references_valid(user_id=user_id, draft=draft):
            return None
        quantity_before = current.quantity or Decimal("0")
        quantity_change = draft.quantity - quantity_before
        cash_amount = draft.total_cost - current.total_cost
        statement = (
            update(Position)
            .where(Position.id == position_id, Position.version == version)
            .values(
                group_id=draft.group_id,
                quantity=draft.quantity,
                total_cost=draft.total_cost,
                average_cost=draft.average_cost,
                status=PositionStatus.OPEN,
                last_trade_date=draft.trade_date,
                version=Position.version + 1,
                updated_at=changed_at,
            )
            .returning(Position)
        )
        try:
            async with self._session.begin_nested():
                position = await self._session.scalar(statement)
                if position is None:
                    return None
                self._session.add(
                    PositionTransaction(
                        position_id=position.id,
                        transaction_type=TransactionType.ADJUSTMENT,
                        status=TransactionStatus.CONFIRMED,
                        trade_date=draft.trade_date,
                        quantity_change=quantity_change,
                        cash_amount=cash_amount,
                        fee_amount=Decimal("0"),
                    )
                )
                await self._session.flush()
        except IntegrityError as error:
            if self._constraint_name(error) == "uq_positions_group_instrument":
                raise PositionAlreadyExistsError from error
            raise
        return self._to_record(position)

    async def delete_for_user(self, *, user_id: UUID, position_id: UUID) -> bool:
        """删除误录持仓及其级联交易；正常清仓后续通过卖出交易完成。"""
        owned_position = (
            select(Position.id)
            .join(WatchlistGroup, WatchlistGroup.id == Position.group_id)
            .where(
                Position.id == position_id,
                WatchlistGroup.user_id == user_id,
            )
        )
        statement = delete(Position).where(Position.id.in_(owned_position)).returning(Position.id)
        return await self._session.scalar(statement) is not None

    async def _owned_position(
        self,
        *,
        user_id: UUID,
        position_id: UUID,
    ) -> Position | None:
        """读取属于指定用户的 ORM 持仓。"""
        return cast(
            Position | None,
            await self._session.scalar(
                select(Position)
                .join(WatchlistGroup, WatchlistGroup.id == Position.group_id)
                .where(
                    Position.id == position_id,
                    WatchlistGroup.user_id == user_id,
                )
            ),
        )

    async def _references_valid(self, *, user_id: UUID, draft: PositionDraft) -> bool:
        """确认目标分组属于用户且资产仍处于可用状态。"""
        count = await self._session.scalar(
            select(func.count())
            .select_from(WatchlistGroup)
            .join(Instrument, Instrument.id == draft.instrument_id)
            .where(
                WatchlistGroup.id == draft.group_id,
                WatchlistGroup.user_id == user_id,
                Instrument.active.is_(True),
            )
        )
        return bool(count)

    @staticmethod
    def _constraint_name(error: IntegrityError) -> str | None:
        """从 psycopg 异常诊断中读取约束名，避免误报其他完整性错误。"""
        diagnostic = getattr(error.orig, "diag", None)
        value = getattr(diagnostic, "constraint_name", None)
        return value if isinstance(value, str) else None

    @staticmethod
    def _to_record(position: Position) -> PositionRecord:
        """把 ORM 持仓转换为不含数据库状态的领域记录。"""
        return PositionRecord(
            id=position.id,
            group_id=position.group_id,
            instrument_id=position.instrument_id,
            quantity=position.quantity,
            total_cost=position.total_cost,
            average_cost=position.average_cost,
            realized_profit=position.realized_profit,
            status=position.status,
            first_trade_date=position.first_trade_date,
            last_trade_date=position.last_trade_date,
            version=position.version,
            created_at=position.created_at,
            updated_at=position.updated_at,
        )
