"""股票持仓创建、读取、修改和删除用例。"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.instruments.domain import InstrumentRecord
from app.modules.instruments.enums import AssetType
from app.modules.instruments.repository import InstrumentRepository
from app.modules.market_data.repository import MarketDataRepository
from app.modules.portfolios.domain import PositionDraft, PositionRecord
from app.modules.portfolios.enums import CostInputMode, PositionInputMode
from app.modules.portfolios.position_commands import (
    FundAmountPositionCommand,
    FundSharesPositionCommand,
    OfficialNavBasis,
    StockPositionCommand,
    UpdateFundAmountPositionCommand,
    UpdateFundSharesPositionCommand,
    UpdateStockPositionCommand,
)
from app.modules.portfolios.position_normalizer import (
    FundAmountPositionNormalizer,
    FundSharesPositionNormalizer,
    PositionNormalizationError,
    StockPositionNormalizer,
)
from app.modules.portfolios.position_repository import (
    PositionAlreadyExistsError,
    PositionRepository,
)
from app.modules.portfolios.repository import InvestmentAccountRepository


class PositionError(Exception):
    """表示可安全映射为公开契约的持仓领域错误。"""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """保存稳定错误码、中文提示和可选恢复信息。"""
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


@dataclass(frozen=True, slots=True)
class PositionView:
    """组合用户持仓和可展示资产身份。"""

    record: PositionRecord
    instrument: InstrumentRecord


class PositionService:
    """执行股票持仓规范化、用户归属和乐观锁规则。"""

    def __init__(
        self,
        position_repository: PositionRepository,
        account_repository: InvestmentAccountRepository,
        instrument_repository: InstrumentRepository,
        market_data_repository: MarketDataRepository | None = None,
    ) -> None:
        """注入用户隔离的持仓、账户和资产持久化边界。"""
        self._positions = position_repository
        self._accounts = account_repository
        self._instruments = instrument_repository
        self._market_data = market_data_repository
        self._normalizer = StockPositionNormalizer()

    async def list_positions(
        self,
        *,
        user_id: UUID,
        account_id: UUID | None,
        page: int,
        page_size: int,
    ) -> tuple[list[PositionView], int]:
        """校验可选账户归属并分页返回当前用户持仓。"""
        if account_id is not None:
            await self._require_account(user_id=user_id, account_id=account_id)
        records, total = await self._positions.list_for_user(
            user_id=user_id,
            account_id=account_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return await self._views(records), total

    async def get_position(self, *, user_id: UUID, position_id: UUID) -> PositionView:
        """读取当前用户单个持仓，越权与不存在使用同一错误。"""
        record = await self._require_position(user_id=user_id, position_id=position_id)
        return (await self._views([record]))[0]

    async def create_stock_position(
        self,
        *,
        user_id: UUID,
        command: StockPositionCommand,
    ) -> PositionView:
        """校验账户与股票身份，规范化后创建账户内唯一持仓。"""
        await self._require_account(user_id=user_id, account_id=command.account_id)
        instrument = await self._require_stock(instrument_id=command.instrument_id)
        draft = self._normalize(command)
        try:
            record = await self._positions.create_for_user(user_id=user_id, draft=draft)
        except PositionAlreadyExistsError as error:
            raise await self._duplicate_error(
                user_id=user_id,
                account_id=command.account_id,
                instrument_id=command.instrument_id,
            ) from error
        if record is None:
            raise PositionError(code="ACCOUNT_NOT_FOUND", message="投资账户不存在")
        return PositionView(record=record, instrument=instrument)

    async def update_stock_position(
        self,
        *,
        user_id: UUID,
        position_id: UUID,
        command: UpdateStockPositionCommand,
    ) -> PositionView:
        """合并部分输入、重新规范化，并仅在版本匹配时保存。"""
        current = await self._require_position(user_id=user_id, position_id=position_id)
        if current.input_mode != PositionInputMode.STOCK_SHARES:
            raise PositionError(
                code="POSITION_INPUT_MODE_MISMATCH",
                message="当前持仓不是股票份额模式",
            )
        if current.version != command.version:
            raise PositionError(
                code="POSITION_VERSION_CONFLICT",
                message="持仓已在其他页面更新，请重新加载",
            )
        account_id = command.account_id or current.account_id
        await self._require_account(user_id=user_id, account_id=account_id)
        cost_mode, total_cost, average_cost = self._merged_cost(current, command)
        quantity = command.quantity if command.quantity is not None else current.input_quantity
        if quantity is None:
            raise PositionError(
                code="INVALID_POSITION_DECIMAL",
                message="股票持有数量不能为空",
            )
        draft = self._normalize(
            StockPositionCommand(
                account_id=account_id,
                instrument_id=current.instrument_id,
                input_date=command.input_date or current.input_date,
                quantity=quantity,
                cost_input_mode=cost_mode,
                total_cost=total_cost,
                average_cost=average_cost,
            )
        )
        try:
            updated = await self._positions.update_for_user(
                user_id=user_id,
                position_id=position_id,
                version=command.version,
                draft=draft,
                changed_at=datetime.now(UTC),
            )
        except PositionAlreadyExistsError as error:
            raise await self._duplicate_error(
                user_id=user_id,
                account_id=account_id,
                instrument_id=current.instrument_id,
            ) from error
        if updated is None:
            raise PositionError(
                code="POSITION_VERSION_CONFLICT",
                message="持仓已在其他页面更新，请重新加载",
            )
        return (await self._views([updated]))[0]

    async def create_fund_amount_position(
        self,
        *,
        user_id: UUID,
        command: FundAmountPositionCommand,
    ) -> PositionView:
        """使用录入日期官方净值可选推算份额并创建基金快速持仓。"""
        await self._require_account(user_id=user_id, account_id=command.account_id)
        instrument = await self._require_fund(instrument_id=command.instrument_id)
        draft = self._normalize_fund_amount(
            FundAmountPositionCommand(
                account_id=command.account_id,
                instrument_id=command.instrument_id,
                input_date=command.input_date,
                current_value=command.current_value,
                holding_profit=command.holding_profit,
                nav_basis=await self._official_nav_basis(
                    instrument_id=command.instrument_id,
                    input_date=command.input_date,
                ),
            )
        )
        try:
            record = await self._positions.create_for_user(user_id=user_id, draft=draft)
        except PositionAlreadyExistsError as error:
            raise await self._duplicate_error(
                user_id=user_id,
                account_id=command.account_id,
                instrument_id=command.instrument_id,
            ) from error
        if record is None:
            raise PositionError(code="ACCOUNT_NOT_FOUND", message="投资账户不存在")
        return PositionView(record=record, instrument=instrument)

    async def create_fund_shares_position(
        self,
        *,
        user_id: UUID,
        command: FundSharesPositionCommand,
    ) -> PositionView:
        """规范化份额和成本后创建基金精确持仓。"""
        await self._require_account(user_id=user_id, account_id=command.account_id)
        instrument = await self._require_fund(instrument_id=command.instrument_id)
        draft = self._normalize_fund_shares(command)
        try:
            record = await self._positions.create_for_user(user_id=user_id, draft=draft)
        except PositionAlreadyExistsError as error:
            raise await self._duplicate_error(
                user_id=user_id,
                account_id=command.account_id,
                instrument_id=command.instrument_id,
            ) from error
        if record is None:
            raise PositionError(code="ACCOUNT_NOT_FOUND", message="投资账户不存在")
        return PositionView(record=record, instrument=instrument)

    async def update_fund_amount_position(
        self,
        *,
        user_id: UUID,
        position_id: UUID,
        command: UpdateFundAmountPositionCommand,
    ) -> PositionView:
        """合并基金金额输入并按新日期重新选择官方净值推算份额。"""
        current = await self._require_mode(
            user_id=user_id,
            position_id=position_id,
            version=command.version,
            input_mode=PositionInputMode.FUND_AMOUNT,
        )
        account_id = command.account_id or current.account_id
        await self._require_account(user_id=user_id, account_id=account_id)
        current_value = (
            command.current_value
            if command.current_value is not None
            else current.input_current_value
        )
        holding_profit = (
            command.holding_profit
            if command.holding_profit is not None
            else current.input_holding_profit
        )
        if current_value is None or holding_profit is None:
            raise PositionError(
                code="INVALID_FUND_AMOUNT_INPUT",
                message="基金当前金额和持有收益不能为空",
            )
        input_date = command.input_date or current.input_date
        draft = self._normalize_fund_amount(
            FundAmountPositionCommand(
                account_id=account_id,
                instrument_id=current.instrument_id,
                input_date=input_date,
                current_value=current_value,
                holding_profit=holding_profit,
                nav_basis=await self._official_nav_basis(
                    instrument_id=current.instrument_id,
                    input_date=input_date,
                ),
            )
        )
        return await self._update_position(
            user_id=user_id,
            position_id=position_id,
            version=command.version,
            draft=draft,
        )

    async def update_fund_shares_position(
        self,
        *,
        user_id: UUID,
        position_id: UUID,
        command: UpdateFundSharesPositionCommand,
    ) -> PositionView:
        """合并基金份额输入并按乐观锁保存精确持仓。"""
        current = await self._require_mode(
            user_id=user_id,
            position_id=position_id,
            version=command.version,
            input_mode=PositionInputMode.FUND_SHARES,
        )
        account_id = command.account_id or current.account_id
        await self._require_account(user_id=user_id, account_id=account_id)
        cost_mode, total_cost, average_cost = self._merged_cost(current, command)
        quantity = command.quantity if command.quantity is not None else current.input_quantity
        if quantity is None:
            raise PositionError(
                code="INVALID_POSITION_DECIMAL",
                message="基金持有份额不能为空",
            )
        draft = self._normalize_fund_shares(
            FundSharesPositionCommand(
                account_id=account_id,
                instrument_id=current.instrument_id,
                input_date=command.input_date or current.input_date,
                quantity=quantity,
                cost_input_mode=cost_mode,
                total_cost=total_cost,
                average_cost=average_cost,
            )
        )
        return await self._update_position(
            user_id=user_id,
            position_id=position_id,
            version=command.version,
            draft=draft,
        )

    async def delete_position(self, *, user_id: UUID, position_id: UUID) -> None:
        """删除当前用户持仓，越权与不存在保持相同错误语义。"""
        await self._require_position(user_id=user_id, position_id=position_id)
        if not await self._positions.delete_for_user(
            user_id=user_id,
            position_id=position_id,
        ):
            raise PositionError(code="POSITION_NOT_FOUND", message="持仓不存在")

    def _normalize(self, command: StockPositionCommand) -> PositionDraft:
        """把规范化错误转换为统一持仓领域错误。"""
        try:
            return self._normalizer.normalize(command)
        except PositionNormalizationError as error:
            raise PositionError(code=error.code, message=error.message) from error

    @staticmethod
    def _normalize_fund_amount(command: FundAmountPositionCommand) -> PositionDraft:
        """把基金金额规范化错误转换为统一持仓领域错误。"""
        try:
            return FundAmountPositionNormalizer().normalize(command)
        except PositionNormalizationError as error:
            raise PositionError(code=error.code, message=error.message) from error

    @staticmethod
    def _normalize_fund_shares(command: FundSharesPositionCommand) -> PositionDraft:
        """把基金份额规范化错误转换为统一持仓领域错误。"""
        try:
            return FundSharesPositionNormalizer().normalize(command)
        except PositionNormalizationError as error:
            raise PositionError(code=error.code, message=error.message) from error

    async def _require_account(self, *, user_id: UUID, account_id: UUID) -> None:
        """要求投资账户属于当前用户。"""
        account = await self._accounts.get_for_user(user_id=user_id, account_id=account_id)
        if account is None:
            raise PositionError(code="ACCOUNT_NOT_FOUND", message="投资账户不存在")

    async def _require_stock(self, *, instrument_id: UUID) -> InstrumentRecord:
        """要求标的是一期可用股票，基金不能进入股票录入路径。"""
        instrument = await self._instruments.get_active(instrument_id=instrument_id)
        if instrument is None:
            raise PositionError(code="INSTRUMENT_NOT_FOUND", message="资产不存在")
        if instrument.asset_type != AssetType.STOCK:
            raise PositionError(
                code="POSITION_ASSET_TYPE_MISMATCH",
                message="股票持仓只能选择股票",
            )
        return instrument

    async def _require_fund(self, *, instrument_id: UUID) -> InstrumentRecord:
        """要求标的是一期可用基金，股票不能进入基金录入路径。"""
        instrument = await self._instruments.get_active(instrument_id=instrument_id)
        if instrument is None:
            raise PositionError(code="INSTRUMENT_NOT_FOUND", message="资产不存在")
        if instrument.asset_type != AssetType.FUND:
            raise PositionError(
                code="POSITION_ASSET_TYPE_MISMATCH",
                message="基金持仓只能选择基金",
            )
        return instrument

    async def _require_mode(
        self,
        *,
        user_id: UUID,
        position_id: UUID,
        version: int,
        input_mode: PositionInputMode,
    ) -> PositionRecord:
        """要求持仓模式和版本与更新请求一致。"""
        current = await self._require_position(user_id=user_id, position_id=position_id)
        if current.input_mode != input_mode:
            raise PositionError(
                code="POSITION_INPUT_MODE_MISMATCH",
                message="持仓录入模式与更新请求不一致",
            )
        if current.version != version:
            raise PositionError(
                code="POSITION_VERSION_CONFLICT",
                message="持仓已在其他页面更新，请重新加载",
            )
        return current

    async def _official_nav_basis(
        self,
        *,
        instrument_id: UUID,
        input_date: date,
    ) -> OfficialNavBasis | None:
        """使用录入日当天或此前最近的官方单位净值推算份额。"""
        if self._market_data is None:
            raise RuntimeError("基金持仓服务缺少行情 Repository")
        price = await self._market_data.latest_official_nav_on_or_before(
            instrument_id=instrument_id,
            nav_date=input_date,
        )
        return (
            OfficialNavBasis(value=price.value, nav_date=price.as_of_date)
            if price is not None and price.as_of_date is not None
            else None
        )

    async def _update_position(
        self,
        *,
        user_id: UUID,
        position_id: UUID,
        version: int,
        draft: PositionDraft,
    ) -> PositionView:
        """保存已规范化持仓并统一处理重复和并发冲突。"""
        try:
            updated = await self._positions.update_for_user(
                user_id=user_id,
                position_id=position_id,
                version=version,
                draft=draft,
                changed_at=datetime.now(UTC),
            )
        except PositionAlreadyExistsError as error:
            raise await self._duplicate_error(
                user_id=user_id,
                account_id=draft.account_id,
                instrument_id=draft.instrument_id,
            ) from error
        if updated is None:
            raise PositionError(
                code="POSITION_VERSION_CONFLICT",
                message="持仓已在其他页面更新，请重新加载",
            )
        return (await self._views([updated]))[0]

    async def _require_position(self, *, user_id: UUID, position_id: UUID) -> PositionRecord:
        """要求持仓属于当前用户，避免通过 ID 枚举其他用户数据。"""
        record = await self._positions.get_for_user(user_id=user_id, position_id=position_id)
        if record is None:
            raise PositionError(code="POSITION_NOT_FOUND", message="持仓不存在")
        return record

    async def _views(self, records: list[PositionRecord]) -> list[PositionView]:
        """批量组合资产身份，避免持仓列表产生逐行查询。"""
        instruments = await self._instruments.get_many(
            instrument_ids=[record.instrument_id for record in records]
        )
        instrument_map = {instrument.id: instrument for instrument in instruments}
        return [
            PositionView(record=record, instrument=instrument_map[record.instrument_id])
            for record in records
        ]

    async def _duplicate_error(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
        instrument_id: UUID,
    ) -> PositionError:
        """查找已有持仓 ID，帮助客户端从新增恢复到编辑。"""
        existing = await self._positions.find_by_account_instrument_for_user(
            user_id=user_id,
            account_id=account_id,
            instrument_id=instrument_id,
        )
        details = {"positionId": str(existing.id)} if existing is not None else None
        return PositionError(
            code="POSITION_ALREADY_EXISTS",
            message="该账户中已经存在此标的",
            details=details,
        )

    @staticmethod
    def _merged_cost(
        current: PositionRecord,
        command: UpdateStockPositionCommand | UpdateFundSharesPositionCommand,
    ) -> tuple[CostInputMode, Decimal | None, Decimal | None]:
        """根据 PATCH 成本字段决定目标模式并丢弃另一模式的旧值。"""
        if command.total_cost is not None and command.average_cost is not None:
            raise PositionError(
                code="INVALID_COST_INPUT",
                message="总成本和平均成本只能填写一项",
            )
        if (
            command.cost_input_mode == CostInputMode.TOTAL_COST
            and command.average_cost is not None
        ) or (
            command.cost_input_mode == CostInputMode.AVERAGE_COST
            and command.total_cost is not None
        ):
            raise PositionError(
                code="INVALID_COST_INPUT",
                message="成本输入方式与填写字段不一致",
            )
        if command.total_cost is not None:
            return CostInputMode.TOTAL_COST, command.total_cost, None
        if command.average_cost is not None:
            return CostInputMode.AVERAGE_COST, None, command.average_cost
        mode = command.cost_input_mode or current.cost_input_mode
        if mode == CostInputMode.TOTAL_COST and current.input_total_cost is not None:
            return mode, current.input_total_cost, None
        if mode == CostInputMode.AVERAGE_COST and current.input_average_cost is not None:
            return mode, None, current.input_average_cost
        raise PositionError(
            code="INVALID_COST_INPUT",
            message="切换成本方式时必须填写对应成本",
        )
