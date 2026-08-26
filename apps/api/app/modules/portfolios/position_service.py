"""股票与基金持仓的创建、读取、修改和删除用例。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from app.modules.instruments.domain import InstrumentRecord
from app.modules.instruments.enums import AssetType
from app.modules.instruments.repository import InstrumentRepository
from app.modules.market_data.enums import PriceType
from app.modules.market_data.providers.contracts import FundNavProvider
from app.modules.market_data.providers.http import ProviderPayloadError, ProviderUnavailableError
from app.modules.market_data.repository import MarketDataRepository
from app.modules.portfolios.domain import PositionDraft, PositionRecord
from app.modules.portfolios.enums import CostInputMode
from app.modules.portfolios.position_commands import (
    FundAmountPositionCommand,
    FundNavBasis,
    FundSharesPositionCommand,
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
from app.modules.watchlists.repository import WatchlistRepository

_SHANGHAI = ZoneInfo("Asia/Shanghai")


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
    """把多种表单输入规范化为统一持仓投影。"""

    def __init__(
        self,
        position_repository: PositionRepository,
        group_repository: WatchlistRepository,
        instrument_repository: InstrumentRepository,
        market_data_repository: MarketDataRepository | None = None,
        fund_nav_provider: FundNavProvider | None = None,
    ) -> None:
        """注入用户隔离的持仓、分组、资产、行情和基金来源边界。"""
        self._positions = position_repository
        self._groups = group_repository
        self._instruments = instrument_repository
        self._market_data = market_data_repository
        self._fund_nav_provider = fund_nav_provider

    async def list_positions(
        self,
        *,
        user_id: UUID,
        group_id: UUID | None,
        page: int,
        page_size: int,
    ) -> tuple[list[PositionView], int]:
        """校验可选分组归属并分页返回当前用户持仓。"""
        if group_id is not None:
            await self._require_group(user_id=user_id, group_id=group_id)
        records, total = await self._positions.list_for_user(
            user_id=user_id,
            group_id=group_id,
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
        """校验股票身份并创建组内唯一持仓及期初交易。"""
        return await self._create_position(
            user_id=user_id,
            command_group_id=command.group_id,
            instrument=await self._require_asset(
                instrument_id=command.instrument_id,
                asset_type=AssetType.STOCK,
            ),
            draft=self._normalize_stock(command),
        )

    async def create_fund_amount_position(
        self,
        *,
        user_id: UUID,
        command: FundAmountPositionCommand,
    ) -> PositionView:
        """获取实时估值或最新净值，立即把基金金额换算为份额。"""
        instrument = await self._require_asset(
            instrument_id=command.instrument_id,
            asset_type=AssetType.FUND,
        )
        normalized = FundAmountPositionCommand(
            group_id=command.group_id,
            instrument_id=command.instrument_id,
            input_date=command.input_date,
            current_value=command.current_value,
            holding_profit=command.holding_profit,
            nav_basis=await self._fund_nav_basis(instrument=instrument),
        )
        return await self._create_position(
            user_id=user_id,
            command_group_id=command.group_id,
            instrument=instrument,
            draft=self._normalize_fund_amount(normalized),
        )

    async def create_fund_shares_position(
        self,
        *,
        user_id: UUID,
        command: FundSharesPositionCommand,
    ) -> PositionView:
        """校验基金身份并按份额与成本创建持仓。"""
        return await self._create_position(
            user_id=user_id,
            command_group_id=command.group_id,
            instrument=await self._require_asset(
                instrument_id=command.instrument_id,
                asset_type=AssetType.FUND,
            ),
            draft=self._normalize_fund_shares(command),
        )

    async def update_stock_position(
        self,
        *,
        user_id: UUID,
        position_id: UUID,
        command: UpdateStockPositionCommand,
    ) -> PositionView:
        """合并股票部分输入，并把变化写入调整交易。"""
        current, instrument = await self._current_for_update(
            user_id=user_id,
            position_id=position_id,
            version=command.version,
            asset_type=AssetType.STOCK,
        )
        quantity = command.quantity if command.quantity is not None else current.quantity
        if quantity is None:
            raise PositionError(code="INVALID_POSITION_DECIMAL", message="股票持有数量不能为空")
        cost_mode, total_cost, average_cost = self._merged_cost(current, command)
        draft = self._normalize_stock(
            StockPositionCommand(
                group_id=command.group_id or current.group_id,
                instrument_id=current.instrument_id,
                input_date=command.input_date or current.last_trade_date,
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
            instrument=instrument,
            draft=draft,
        )

    async def update_fund_amount_position(
        self,
        *,
        user_id: UUID,
        position_id: UUID,
        command: UpdateFundAmountPositionCommand,
    ) -> PositionView:
        """按当前可用净值重新计算基金金额模式持仓。"""
        current, instrument = await self._current_for_update(
            user_id=user_id,
            position_id=position_id,
            version=command.version,
            asset_type=AssetType.FUND,
        )
        group_id = command.group_id or current.group_id
        trade_date = command.input_date or current.last_trade_date
        if command.current_value is None and command.holding_profit is None:
            if current.quantity is None or current.average_cost is None:
                raise PositionError(code="POSITION_PENDING", message="历史持仓数据尚未补齐")
            draft = PositionDraft(
                group_id=group_id,
                instrument_id=current.instrument_id,
                trade_date=trade_date,
                quantity=current.quantity,
                total_cost=current.total_cost,
                average_cost=current.average_cost,
            )
        else:
            basis = await self._fund_nav_basis(instrument=instrument)
            if basis is None or current.quantity is None:
                raise PositionError(
                    code="FUND_NAV_UNAVAILABLE",
                    message="暂时无法取得基金净值，请稍后重试或改用份额录入",
                )
            current_value = current.quantity * basis.value
            holding_profit = current_value - current.total_cost
            draft = self._normalize_fund_amount(
                FundAmountPositionCommand(
                    group_id=group_id,
                    instrument_id=current.instrument_id,
                    input_date=trade_date,
                    current_value=(
                        command.current_value
                        if command.current_value is not None
                        else current_value
                    ),
                    holding_profit=(
                        command.holding_profit
                        if command.holding_profit is not None
                        else holding_profit
                    ),
                    nav_basis=basis,
                )
            )
        return await self._update_position(
            user_id=user_id,
            position_id=position_id,
            version=command.version,
            instrument=instrument,
            draft=draft,
        )

    async def update_fund_shares_position(
        self,
        *,
        user_id: UUID,
        position_id: UUID,
        command: UpdateFundSharesPositionCommand,
    ) -> PositionView:
        """合并基金份额输入，并把变化写入调整交易。"""
        current, instrument = await self._current_for_update(
            user_id=user_id,
            position_id=position_id,
            version=command.version,
            asset_type=AssetType.FUND,
        )
        quantity = command.quantity if command.quantity is not None else current.quantity
        if quantity is None:
            raise PositionError(code="INVALID_POSITION_DECIMAL", message="基金持有份额不能为空")
        cost_mode, total_cost, average_cost = self._merged_cost(current, command)
        draft = self._normalize_fund_shares(
            FundSharesPositionCommand(
                group_id=command.group_id or current.group_id,
                instrument_id=current.instrument_id,
                input_date=command.input_date or current.last_trade_date,
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
            instrument=instrument,
            draft=draft,
        )

    async def delete_position(self, *, user_id: UUID, position_id: UUID) -> None:
        """删除误录持仓，越权与不存在保持相同错误语义。"""
        await self._require_position(user_id=user_id, position_id=position_id)
        if not await self._positions.delete_for_user(user_id=user_id, position_id=position_id):
            raise PositionError(code="POSITION_NOT_FOUND", message="持仓不存在")

    async def _create_position(
        self,
        *,
        user_id: UUID,
        command_group_id: UUID,
        instrument: InstrumentRecord,
        draft: PositionDraft,
    ) -> PositionView:
        """统一处理分组归属、重复持仓和创建结果。"""
        await self._require_group(user_id=user_id, group_id=command_group_id)
        try:
            record = await self._positions.create_for_user(user_id=user_id, draft=draft)
        except PositionAlreadyExistsError as error:
            raise await self._duplicate_error(
                user_id=user_id,
                group_id=command_group_id,
                instrument_id=instrument.id,
            ) from error
        if record is None:
            raise PositionError(code="GROUP_NOT_FOUND", message="分组不存在")
        return PositionView(record=record, instrument=instrument)

    async def _update_position(
        self,
        *,
        user_id: UUID,
        position_id: UUID,
        version: int,
        instrument: InstrumentRecord,
        draft: PositionDraft,
    ) -> PositionView:
        """统一保存投影、处理组内重复和乐观锁冲突。"""
        await self._require_group(user_id=user_id, group_id=draft.group_id)
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
                group_id=draft.group_id,
                instrument_id=draft.instrument_id,
            ) from error
        if updated is None:
            raise PositionError(
                code="POSITION_VERSION_CONFLICT",
                message="持仓已在其他页面更新，请重新加载",
            )
        return PositionView(record=updated, instrument=instrument)

    async def _current_for_update(
        self,
        *,
        user_id: UUID,
        position_id: UUID,
        version: int,
        asset_type: AssetType,
    ) -> tuple[PositionRecord, InstrumentRecord]:
        """校验当前投影版本及其资产类型。"""
        current = await self._require_position(user_id=user_id, position_id=position_id)
        if current.version != version:
            raise PositionError(
                code="POSITION_VERSION_CONFLICT",
                message="持仓已在其他页面更新，请重新加载",
            )
        instrument = await self._require_asset(
            instrument_id=current.instrument_id,
            asset_type=asset_type,
        )
        return current, instrument

    async def _require_group(self, *, user_id: UUID, group_id: UUID) -> None:
        """要求组合分组属于当前用户。"""
        if await self._groups.get_group_for_user(user_id=user_id, group_id=group_id) is None:
            raise PositionError(code="GROUP_NOT_FOUND", message="分组不存在")

    async def _require_asset(
        self,
        *,
        instrument_id: UUID,
        asset_type: AssetType,
    ) -> InstrumentRecord:
        """要求标的存在、可用且与录入入口资产类型一致。"""
        instrument = await self._instruments.get_active(instrument_id=instrument_id)
        if instrument is None:
            raise PositionError(code="INSTRUMENT_NOT_FOUND", message="资产不存在")
        if instrument.asset_type != asset_type:
            label = "股票" if asset_type == AssetType.STOCK else "基金"
            raise PositionError(
                code="POSITION_ASSET_TYPE_MISMATCH",
                message=f"{label}持仓只能选择{label}",
            )
        return instrument

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
        group_id: UUID,
        instrument_id: UUID,
    ) -> PositionError:
        """查找已有持仓 ID，帮助客户端从新增恢复到编辑。"""
        existing = await self._positions.find_by_group_instrument_for_user(
            user_id=user_id,
            group_id=group_id,
            instrument_id=instrument_id,
        )
        details = {"positionId": str(existing.id)} if existing is not None else None
        return PositionError(
            code="POSITION_ALREADY_EXISTS",
            message="该分组中已经存在此标的",
            details=details,
        )

    async def _fund_nav_basis(self, *, instrument: InstrumentRecord) -> FundNavBasis | None:
        """优先拉取盘中估值，回退最新官方净值和本地行情。"""
        if self._market_data is None:
            raise RuntimeError("基金持仓服务缺少行情 Repository")
        if self._fund_nav_provider is not None:
            try:
                estimated = list(
                    await self._fund_nav_provider.fetch_estimated_navs([instrument.ticker])
                )
                if estimated:
                    estimated_snapshot = estimated[0]
                    await self._market_data.upsert_estimated_navs(estimated)
                    return FundNavBasis(
                        value=estimated_snapshot.estimated_nav,
                        nav_date=estimated_snapshot.as_of_at.astimezone(_SHANGHAI).date(),
                    )
                official = list(
                    await self._fund_nav_provider.fetch_official_navs([instrument.ticker])
                )
                if official:
                    official_snapshot = official[0]
                    await self._market_data.upsert_official_navs(official)
                    return FundNavBasis(
                        value=official_snapshot.unit_nav,
                        nav_date=official_snapshot.nav_date,
                    )
            except (ProviderUnavailableError, ProviderPayloadError, ValidationError):
                pass

        prices = (await self._market_data.latest_prices(instrument_ids=[instrument.id])).get(
            instrument.id,
            [],
        )
        today = datetime.now(_SHANGHAI).date()
        estimated_price = next(
            (
                price
                for price in prices
                if price.price_type == PriceType.FUND_ESTIMATED_NAV
                and price.as_of_at is not None
                and price.as_of_at.astimezone(_SHANGHAI).date() == today
            ),
            None,
        )
        if estimated_price is not None:
            return FundNavBasis(value=estimated_price.value, nav_date=today)
        price = await self._market_data.latest_official_nav_on_or_before(
            instrument_id=instrument.id,
            nav_date=today,
        )
        return (
            FundNavBasis(value=price.value, nav_date=price.as_of_date)
            if price is not None and price.as_of_date is not None
            else None
        )

    @staticmethod
    def _normalize_stock(command: StockPositionCommand) -> PositionDraft:
        """把股票规范化错误转换为统一持仓领域错误。"""
        return PositionService._normalize_with(StockPositionNormalizer(), command)

    @staticmethod
    def _normalize_fund_amount(command: FundAmountPositionCommand) -> PositionDraft:
        """把基金金额规范化错误转换为统一持仓领域错误。"""
        return PositionService._normalize_with(FundAmountPositionNormalizer(), command)

    @staticmethod
    def _normalize_fund_shares(command: FundSharesPositionCommand) -> PositionDraft:
        """把基金份额规范化错误转换为统一持仓领域错误。"""
        return PositionService._normalize_with(FundSharesPositionNormalizer(), command)

    @staticmethod
    def _normalize_with(normalizer: Any, command: Any) -> PositionDraft:
        """统一转换规范化组件暴露的稳定错误。"""
        try:
            return cast(PositionDraft, normalizer.normalize(command))
        except PositionNormalizationError as error:
            raise PositionError(code=error.code, message=error.message) from error

    @staticmethod
    def _merged_cost(
        current: PositionRecord,
        command: UpdateStockPositionCommand | UpdateFundSharesPositionCommand,
    ) -> tuple[CostInputMode, Decimal | None, Decimal | None]:
        """把部分成本输入合并为一次完整且无歧义的规范化请求。"""
        if command.total_cost is not None and command.average_cost is not None:
            raise PositionError(code="INVALID_COST_INPUT", message="总成本和平均成本只能填写一项")
        if command.total_cost is not None:
            return CostInputMode.TOTAL_COST, command.total_cost, None
        if command.average_cost is not None:
            return CostInputMode.AVERAGE_COST, None, command.average_cost
        if command.cost_input_mode == CostInputMode.AVERAGE_COST:
            if current.average_cost is None:
                raise PositionError(code="POSITION_PENDING", message="历史持仓数据尚未补齐")
            return CostInputMode.AVERAGE_COST, None, current.average_cost
        return CostInputMode.TOTAL_COST, current.total_cost, None
