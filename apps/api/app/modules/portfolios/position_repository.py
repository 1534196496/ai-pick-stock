"""用户隔离的持仓持久化边界。"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.instruments.models import Instrument
from app.modules.portfolios.domain import (
    PendingFundAmountPosition,
    PositionDraft,
    PositionRecord,
)
from app.modules.portfolios.enums import PositionInputMode
from app.modules.portfolios.models import InvestmentAccount, Position


class PositionAlreadyExistsError(Exception):
    """表示同一投资账户已经持有同一标的。"""


class PositionRepository:
    """所有持仓入口都通过投资账户关联强制校验当前用户。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定由 API 服务管理事务边界的数据库会话。"""
        self._session = session

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        account_id: UUID | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[PositionRecord], int]:
        """按当前用户和可选账户稳定分页读取持仓。"""
        conditions = [InvestmentAccount.user_id == user_id]
        if account_id is not None:
            conditions.append(Position.account_id == account_id)
        base = (
            select(Position)
            .join(InvestmentAccount, InvestmentAccount.id == Position.account_id)
            .where(*conditions)
        )
        statement = (
            base.order_by(Position.created_at, Position.id)
            .offset(offset)
            .limit(limit)
        )
        positions = (await self._session.scalars(statement)).all()
        total = await self._session.scalar(
            select(func.count())
            .select_from(Position)
            .join(InvestmentAccount, InvestmentAccount.id == Position.account_id)
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
        position = await self._session.scalar(
            select(Position)
            .join(InvestmentAccount, InvestmentAccount.id == Position.account_id)
            .where(
                Position.id == position_id,
                InvestmentAccount.user_id == user_id,
            )
        )
        return self._to_record(position) if position is not None else None

    async def find_by_account_instrument_for_user(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
        instrument_id: UUID,
    ) -> PositionRecord | None:
        """为重复创建提示查找当前用户账户中的已有持仓。"""
        position = await self._session.scalar(
            select(Position)
            .join(InvestmentAccount, InvestmentAccount.id == Position.account_id)
            .where(
                Position.account_id == account_id,
                Position.instrument_id == instrument_id,
                InvestmentAccount.user_id == user_id,
            )
        )
        return self._to_record(position) if position is not None else None

    async def create_for_user(
        self,
        *,
        user_id: UUID,
        draft: PositionDraft,
    ) -> PositionRecord | None:
        """仅为当前用户账户和活跃标的创建规范化持仓。"""
        references_valid = await self._session.scalar(
            select(func.count())
            .select_from(InvestmentAccount)
            .join(Instrument, Instrument.id == draft.instrument_id)
            .where(
                InvestmentAccount.id == draft.account_id,
                InvestmentAccount.user_id == user_id,
                Instrument.active.is_(True),
            )
        )
        if not references_valid:
            return None
        position = Position(
            account_id=draft.account_id,
            instrument_id=draft.instrument_id,
            input_mode=draft.input_mode,
            cost_input_mode=draft.cost_input_mode,
            input_date=draft.input_date,
            input_quantity=draft.input_quantity,
            input_total_cost=draft.input_total_cost,
            input_average_cost=draft.input_average_cost,
            input_current_value=draft.input_current_value,
            input_holding_profit=draft.input_holding_profit,
            quantity=draft.quantity,
            total_cost=draft.total_cost,
            average_cost=draft.average_cost,
            quantity_estimated=draft.quantity_estimated,
            quantity_basis_nav=draft.quantity_basis_nav,
            quantity_basis_nav_date=draft.quantity_basis_nav_date,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(position)
                await self._session.flush()
        except IntegrityError as error:
            if self._constraint_name(error) == "uq_positions_account_instrument":
                raise PositionAlreadyExistsError from error
            raise
        return self._to_record(position)

    async def delete_for_user(self, *, user_id: UUID, position_id: UUID) -> bool:
        """只删除当前用户账户中的指定持仓。"""
        owned_position = (
            select(Position.id)
            .join(InvestmentAccount, InvestmentAccount.id == Position.account_id)
            .where(
                Position.id == position_id,
                InvestmentAccount.user_id == user_id,
            )
        )
        statement = delete(Position).where(Position.id.in_(owned_position)).returning(Position.id)
        return await self._session.scalar(statement) is not None

    async def update_for_user(
        self,
        *,
        user_id: UUID,
        position_id: UUID,
        version: int,
        draft: PositionDraft,
        changed_at: datetime,
    ) -> PositionRecord | None:
        """仅在当前用户归属和版本匹配时覆盖规范化输入并递增版本。"""
        owned_position = (
            select(Position.id)
            .join(InvestmentAccount, InvestmentAccount.id == Position.account_id)
            .where(
                Position.id == position_id,
                InvestmentAccount.user_id == user_id,
            )
        )
        statement = (
            update(Position)
            .where(
                Position.id.in_(owned_position),
                Position.version == version,
            )
            .values(
                account_id=draft.account_id,
                input_mode=draft.input_mode,
                cost_input_mode=draft.cost_input_mode,
                input_date=draft.input_date,
                input_quantity=draft.input_quantity,
                input_total_cost=draft.input_total_cost,
                input_average_cost=draft.input_average_cost,
                input_current_value=draft.input_current_value,
                input_holding_profit=draft.input_holding_profit,
                quantity=draft.quantity,
                total_cost=draft.total_cost,
                average_cost=draft.average_cost,
                quantity_estimated=draft.quantity_estimated,
                quantity_basis_nav=draft.quantity_basis_nav,
                quantity_basis_nav_date=draft.quantity_basis_nav_date,
                version=Position.version + 1,
                updated_at=changed_at,
            )
            .returning(Position)
        )
        try:
            async with self._session.begin_nested():
                position = await self._session.scalar(statement)
        except IntegrityError as error:
            if self._constraint_name(error) == "uq_positions_account_instrument":
                raise PositionAlreadyExistsError from error
            raise
        return self._to_record(position) if position is not None else None

    async def list_pending_fund_amounts(self) -> list[PendingFundAmountPosition]:
        """为系统同步任务返回仍缺少推算份额的基金金额持仓。"""
        positions = (
            await self._session.scalars(
                select(Position).where(
                    Position.input_mode == PositionInputMode.FUND_AMOUNT,
                    Position.quantity.is_(None),
                    Position.input_current_value.is_not(None),
                )
            )
        ).all()
        return [
            PendingFundAmountPosition(
                id=position.id,
                instrument_id=position.instrument_id,
                input_date=position.input_date,
                current_value=position.input_current_value,
                total_cost=position.total_cost,
                version=position.version,
            )
            for position in positions
            if position.input_current_value is not None
        ]

    async def apply_fund_amount_basis(
        self,
        *,
        position_id: UUID,
        version: int,
        quantity: Decimal,
        average_cost: Decimal,
        nav: Decimal,
        nav_date: date,
        changed_at: datetime,
    ) -> bool:
        """仅在版本和待补状态未变化时写入官方净值推算结果。"""
        statement = (
            update(Position)
            .where(
                Position.id == position_id,
                Position.version == version,
                Position.input_mode == PositionInputMode.FUND_AMOUNT,
                Position.quantity.is_(None),
            )
            .values(
                quantity=quantity,
                average_cost=average_cost,
                quantity_estimated=True,
                quantity_basis_nav=nav,
                quantity_basis_nav_date=nav_date,
                version=Position.version + 1,
                updated_at=changed_at,
            )
            .returning(Position.id)
        )
        return await self._session.scalar(statement) is not None

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
            account_id=position.account_id,
            instrument_id=position.instrument_id,
            input_mode=position.input_mode,
            cost_input_mode=position.cost_input_mode,
            input_date=position.input_date,
            input_quantity=position.input_quantity,
            input_total_cost=position.input_total_cost,
            input_average_cost=position.input_average_cost,
            input_current_value=position.input_current_value,
            input_holding_profit=position.input_holding_profit,
            quantity=position.quantity,
            total_cost=position.total_cost,
            average_cost=position.average_cost,
            quantity_estimated=position.quantity_estimated,
            quantity_basis_nav=position.quantity_basis_nav,
            quantity_basis_nav_date=position.quantity_basis_nav_date,
            version=position.version,
            created_at=position.created_at,
            updated_at=position.updated_at,
        )
