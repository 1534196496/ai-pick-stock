"""自选分组、观察标的、备注和移动用例。"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.modules.instruments.domain import InstrumentRecord
from app.modules.instruments.repository import InstrumentRepository
from app.modules.instruments.service import InstrumentView, PriceView
from app.modules.market_data.enums import PriceType
from app.modules.market_data.repository import MarketDataRepository
from app.modules.market_data.service import MarketDataFreshnessPolicy
from app.modules.watchlists.domain import WatchlistGroupRecord, WatchlistItemRecord
from app.modules.watchlists.repository import (
    WatchlistItemAlreadyExistsError,
    WatchlistNameConflictError,
    WatchlistRepository,
)

_PRICE_ORDER = {
    PriceType.STOCK_LAST: 0,
    PriceType.FUND_OFFICIAL_NAV: 1,
    PriceType.FUND_ESTIMATED_NAV: 2,
}


class WatchlistError(Exception):
    """表示可安全映射为公开契约的自选领域错误。"""

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
class WatchlistGroupView:
    """组合自选分组记录和当前观察标的数量。"""

    record: WatchlistGroupRecord
    item_count: int


@dataclass(frozen=True, slots=True)
class WatchlistItemView:
    """组合观察记录、资产身份和互不混淆的最新价格。"""

    record: WatchlistItemRecord
    instrument: InstrumentView


class WatchlistService:
    """执行分组保护、用户隔离、备注规范化和行情组合规则。"""

    def __init__(
        self,
        repository: WatchlistRepository,
        instrument_repository: InstrumentRepository,
        market_data_repository: MarketDataRepository,
        freshness_policy: MarketDataFreshnessPolicy,
    ) -> None:
        """注入自选、资产、行情持久化边界和新鲜度策略。"""
        self._repository = repository
        self._instruments = instrument_repository
        self._market_data = market_data_repository
        self._freshness_policy = freshness_policy

    async def list_groups(self, *, user_id: UUID) -> list[WatchlistGroupView]:
        """返回当前用户全部分组和批量统计的标的数量。"""
        records = await self._repository.list_groups_for_user(user_id=user_id)
        counts = await self._repository.item_counts_for_user(user_id=user_id)
        return [
            WatchlistGroupView(record=record, item_count=counts.get(record.id, 0))
            for record in records
        ]

    async def get_group(self, *, user_id: UUID, group_id: UUID) -> WatchlistGroupView:
        """读取当前用户分组，越权和不存在统一使用 404 语义。"""
        record = await self._require_group(user_id=user_id, group_id=group_id)
        counts = await self._repository.item_counts_for_user(user_id=user_id)
        return WatchlistGroupView(record=record, item_count=counts.get(record.id, 0))

    async def create_group(self, *, user_id: UUID, name: str) -> WatchlistGroupView:
        """规范化名称并把新分组追加到用户排序末尾。"""
        normalized = self._normalize_group_name(name)
        record = await self._repository.create_group_for_user(
            user_id=user_id,
            name=normalized,
            sort_order=await self._repository.next_group_sort_order(user_id=user_id),
        )
        if record is None:
            raise WatchlistError(
                code="WATCHLIST_GROUP_NAME_ALREADY_EXISTS",
                message="已经存在同名自选分组",
            )
        return WatchlistGroupView(record=record, item_count=0)

    async def update_group(
        self,
        *,
        user_id: UUID,
        group_id: UUID,
        version: int,
        name: str | None,
        sort_order: int | None,
    ) -> WatchlistGroupView:
        """合并分组字段并仅在乐观锁版本匹配时保存。"""
        current = await self._require_group(user_id=user_id, group_id=group_id)
        if current.version != version:
            raise WatchlistError(
                code="WATCHLIST_GROUP_VERSION_CONFLICT",
                message="分组已在其他页面更新，请重新加载",
            )
        try:
            updated = await self._repository.update_group_for_user(
                user_id=user_id,
                group_id=group_id,
                version=version,
                name=self._normalize_group_name(name) if name is not None else current.name,
                sort_order=sort_order if sort_order is not None else current.sort_order,
                changed_at=datetime.now(UTC),
            )
        except WatchlistNameConflictError as error:
            raise WatchlistError(
                code="WATCHLIST_GROUP_NAME_ALREADY_EXISTS",
                message="已经存在同名自选分组",
            ) from error
        if updated is None:
            raise WatchlistError(
                code="WATCHLIST_GROUP_VERSION_CONFLICT",
                message="分组已在其他页面更新，请重新加载",
            )
        counts = await self._repository.item_counts_for_user(user_id=user_id)
        return WatchlistGroupView(record=updated, item_count=counts.get(updated.id, 0))

    async def delete_group(self, *, user_id: UUID, group_id: UUID) -> None:
        """拒绝删除默认或非空分组，只删除当前用户普通空分组。"""
        current = await self._require_group(user_id=user_id, group_id=group_id)
        if current.is_default:
            raise WatchlistError(
                code="WATCHLIST_DEFAULT_GROUP_PROTECTED",
                message="默认分组不能删除",
            )
        if await self._repository.group_has_items_for_user(
            user_id=user_id,
            group_id=group_id,
        ):
            raise WatchlistError(
                code="WATCHLIST_GROUP_NOT_EMPTY",
                message="分组仍有自选标的，不能删除",
            )
        if not await self._repository.delete_empty_group_for_user(
            user_id=user_id,
            group_id=group_id,
        ):
            raise WatchlistError(
                code="WATCHLIST_GROUP_NOT_EMPTY",
                message="分组已加入自选标的，不能删除",
            )

    async def list_items(
        self,
        *,
        user_id: UUID,
        group_id: UUID,
        page: int,
        page_size: int,
    ) -> tuple[list[WatchlistItemView], int]:
        """校验分组归属后分页组合观察标的身份和本地行情。"""
        await self._require_group(user_id=user_id, group_id=group_id)
        records, total = await self._repository.list_items_for_user(
            user_id=user_id,
            group_id=group_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        return await self._item_views(records), total

    async def get_item(self, *, user_id: UUID, item_id: UUID) -> WatchlistItemView:
        """读取当前用户拥有的单个观察标的。"""
        record = await self._require_item(user_id=user_id, item_id=item_id)
        return (await self._item_views([record]))[0]

    async def create_item(
        self,
        *,
        user_id: UUID,
        group_id: UUID,
        instrument_id: UUID,
        note: str | None,
    ) -> WatchlistItemView:
        """向当前用户分组添加活跃标的，并提供重复项恢复信息。"""
        await self._require_group(user_id=user_id, group_id=group_id)
        instrument = await self._require_instrument(instrument_id=instrument_id)
        try:
            record = await self._repository.create_item_for_user(
                user_id=user_id,
                group_id=group_id,
                instrument_id=instrument_id,
                note=self._normalize_note(note),
                sort_order=await self._repository.next_item_sort_order(
                    user_id=user_id,
                    group_id=group_id,
                ),
            )
        except WatchlistItemAlreadyExistsError as error:
            raise await self._duplicate_item_error(
                user_id=user_id,
                group_id=group_id,
                instrument_id=instrument_id,
            ) from error
        if record is None:
            raise WatchlistError(code="WATCHLIST_GROUP_NOT_FOUND", message="自选分组不存在")
        return (await self._item_views([record], instruments=[instrument]))[0]

    async def update_item(
        self,
        *,
        user_id: UUID,
        item_id: UUID,
        version: int,
        group_id: UUID | None,
        note: str | None,
        note_provided: bool,
        sort_order: int | None,
    ) -> WatchlistItemView:
        """按版本修改备注、排序或把标的移动到当前用户另一分组。"""
        current = await self._require_item(user_id=user_id, item_id=item_id)
        if current.version != version:
            raise WatchlistError(
                code="WATCHLIST_ITEM_VERSION_CONFLICT",
                message="自选标的已在其他页面更新，请重新加载",
            )
        target_group_id = group_id or current.group_id
        await self._require_group(user_id=user_id, group_id=target_group_id)
        target_note = self._normalize_note(note) if note_provided else current.note
        try:
            updated = await self._repository.update_item_for_user(
                user_id=user_id,
                item_id=item_id,
                version=version,
                group_id=target_group_id,
                note=target_note,
                sort_order=sort_order if sort_order is not None else current.sort_order,
                changed_at=datetime.now(UTC),
            )
        except WatchlistItemAlreadyExistsError as error:
            raise await self._duplicate_item_error(
                user_id=user_id,
                group_id=target_group_id,
                instrument_id=current.instrument_id,
            ) from error
        if updated is None:
            raise WatchlistError(
                code="WATCHLIST_ITEM_VERSION_CONFLICT",
                message="自选标的已在其他页面更新，请重新加载",
            )
        return (await self._item_views([updated]))[0]

    async def delete_item(self, *, user_id: UUID, item_id: UUID) -> None:
        """删除当前用户指定观察标的，越权与不存在保持相同语义。"""
        await self._require_item(user_id=user_id, item_id=item_id)
        if not await self._repository.delete_item_for_user(
            user_id=user_id,
            item_id=item_id,
        ):
            raise WatchlistError(code="WATCHLIST_ITEM_NOT_FOUND", message="自选标的不存在")

    async def _require_group(self, *, user_id: UUID, group_id: UUID) -> WatchlistGroupRecord:
        """要求自选分组属于当前用户。"""
        record = await self._repository.get_group_for_user(
            user_id=user_id,
            group_id=group_id,
        )
        if record is None:
            raise WatchlistError(code="WATCHLIST_GROUP_NOT_FOUND", message="自选分组不存在")
        return record

    async def _require_item(self, *, user_id: UUID, item_id: UUID) -> WatchlistItemRecord:
        """要求观察标的通过所属分组归属于当前用户。"""
        record = await self._repository.get_item_for_user(user_id=user_id, item_id=item_id)
        if record is None:
            raise WatchlistError(code="WATCHLIST_ITEM_NOT_FOUND", message="自选标的不存在")
        return record

    async def _require_instrument(self, *, instrument_id: UUID) -> InstrumentRecord:
        """要求待关注标的是一期可用资产。"""
        instrument = await self._instruments.get_active(instrument_id=instrument_id)
        if instrument is None:
            raise WatchlistError(code="INSTRUMENT_NOT_FOUND", message="资产不存在")
        return instrument

    async def _item_views(
        self,
        records: list[WatchlistItemRecord],
        *,
        instruments: list[InstrumentRecord] | None = None,
    ) -> list[WatchlistItemView]:
        """批量组合资产和价格，避免自选列表产生逐行查询。"""
        instrument_records = instruments or await self._instruments.get_many(
            instrument_ids=[record.instrument_id for record in records]
        )
        instrument_map = {instrument.id: instrument for instrument in instrument_records}
        price_map = await self._market_data.latest_prices(
            instrument_ids=[record.instrument_id for record in records]
        )
        now = datetime.now(UTC)
        return [
            WatchlistItemView(
                record=record,
                instrument=InstrumentView(
                    record=instrument_map[record.instrument_id],
                    prices=tuple(
                        PriceView(
                            record=price,
                            freshness=self._freshness_policy.for_price(price, now=now),
                        )
                        for price in sorted(
                            price_map.get(record.instrument_id, []),
                            key=lambda item: _PRICE_ORDER[item.price_type],
                        )
                    ),
                ),
            )
            for record in records
        ]

    async def _duplicate_item_error(
        self,
        *,
        user_id: UUID,
        group_id: UUID,
        instrument_id: UUID,
    ) -> WatchlistError:
        """查找重复项 ID，帮助客户端恢复到已有记录。"""
        existing = await self._repository.find_item_in_group_for_user(
            user_id=user_id,
            group_id=group_id,
            instrument_id=instrument_id,
        )
        details = {"itemId": str(existing.id)} if existing is not None else None
        return WatchlistError(
            code="WATCHLIST_ITEM_ALREADY_EXISTS",
            message="该分组中已经关注此标的",
            details=details,
        )

    @staticmethod
    def _normalize_group_name(name: str) -> str:
        """去除首尾空白并执行数据库一致的分组名称长度边界。"""
        normalized = name.strip()
        if not 1 <= len(normalized) <= 80:
            raise WatchlistError(
                code="INVALID_WATCHLIST_GROUP_NAME",
                message="分组名称长度必须为 1–80 个字符",
            )
        return normalized

    @staticmethod
    def _normalize_note(note: str | None) -> str | None:
        """把空备注归一为空值，并限制有效备注长度。"""
        if note is None:
            return None
        normalized = note.strip()
        if not normalized:
            return None
        if len(normalized) > 500:
            raise WatchlistError(
                code="INVALID_WATCHLIST_NOTE",
                message="备注最多 500 个字符",
            )
        return normalized
