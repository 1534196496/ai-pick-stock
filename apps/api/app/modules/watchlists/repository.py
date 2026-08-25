"""用户隔离的自选分组与观察标的持久化边界。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.instruments.models import Instrument
from app.modules.watchlists.domain import WatchlistGroupRecord, WatchlistItemRecord
from app.modules.watchlists.models import WatchlistGroup, WatchlistItem


class WatchlistNameConflictError(Exception):
    """表示同一用户的自选分组名称发生冲突。"""


class WatchlistItemAlreadyExistsError(Exception):
    """表示同一分组已经包含指定标的。"""


class WatchlistRepository:
    """所有自选读写都显式携带当前用户 ID。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定请求事务中的数据库会话。"""
        self._session = session

    async def create_default_for_user(self, *, user_id: UUID) -> WatchlistGroupRecord:
        """幂等创建用户唯一的默认自选分组。"""
        statement = (
            insert(WatchlistGroup)
            .values(
                user_id=user_id,
                name="默认分组",
                is_default=True,
                sort_order=0,
            )
            .on_conflict_do_nothing()
            .returning(WatchlistGroup)
        )
        group = await self._session.scalar(statement)
        if group is None:
            group = await self._session.scalar(
                select(WatchlistGroup).where(
                    WatchlistGroup.user_id == user_id,
                    WatchlistGroup.is_default.is_(True),
                )
            )
        if group is None:
            raise RuntimeError("默认自选分组创建失败")
        return self._to_group_record(group)

    async def list_groups_for_user(
        self,
        *,
        user_id: UUID,
    ) -> list[WatchlistGroupRecord]:
        """按默认优先和用户排序返回全部自选分组。"""
        groups = (
            await self._session.scalars(
                select(WatchlistGroup)
                .where(WatchlistGroup.user_id == user_id)
                .order_by(
                    WatchlistGroup.is_default.desc(),
                    WatchlistGroup.sort_order,
                    WatchlistGroup.created_at,
                    WatchlistGroup.id,
                )
            )
        ).all()
        return [self._to_group_record(group) for group in groups]

    async def get_group_for_user(
        self,
        *,
        user_id: UUID,
        group_id: UUID,
    ) -> WatchlistGroupRecord | None:
        """按用户归属读取分组，越权与不存在均返回空。"""
        group = await self._session.scalar(
            select(WatchlistGroup).where(
                WatchlistGroup.id == group_id,
                WatchlistGroup.user_id == user_id,
            )
        )
        return self._to_group_record(group) if group is not None else None

    async def item_counts_for_user(self, *, user_id: UUID) -> dict[UUID, int]:
        """批量返回当前用户各分组的观察标的数量。"""
        rows = await self._session.execute(
            select(WatchlistGroup.id, func.count(WatchlistItem.id))
            .outerjoin(WatchlistItem, WatchlistItem.group_id == WatchlistGroup.id)
            .where(WatchlistGroup.user_id == user_id)
            .group_by(WatchlistGroup.id)
        )
        return {group_id: int(count) for group_id, count in rows.tuples()}

    async def next_group_sort_order(self, *, user_id: UUID) -> int:
        """返回当前用户最大分组排序值之后的位置。"""
        value = await self._session.scalar(
            select(func.coalesce(func.max(WatchlistGroup.sort_order) + 1, 0)).where(
                WatchlistGroup.user_id == user_id
            )
        )
        return int(value or 0)

    async def create_group_for_user(
        self,
        *,
        user_id: UUID,
        name: str,
        sort_order: int,
    ) -> WatchlistGroupRecord | None:
        """创建非默认分组，同用户名称冲突时返回空。"""
        statement = (
            insert(WatchlistGroup)
            .values(
                user_id=user_id,
                name=name,
                is_default=False,
                sort_order=sort_order,
            )
            .on_conflict_do_nothing()
            .returning(WatchlistGroup)
        )
        group = await self._session.scalar(statement)
        return self._to_group_record(group) if group is not None else None

    async def update_group_for_user(
        self,
        *,
        user_id: UUID,
        group_id: UUID,
        version: int,
        name: str,
        sort_order: int,
        changed_at: datetime,
    ) -> WatchlistGroupRecord | None:
        """仅在用户归属和版本匹配时更新分组名称及排序。"""
        statement = (
            update(WatchlistGroup)
            .where(
                WatchlistGroup.id == group_id,
                WatchlistGroup.user_id == user_id,
                WatchlistGroup.version == version,
            )
            .values(
                name=name,
                sort_order=sort_order,
                version=WatchlistGroup.version + 1,
                updated_at=changed_at,
            )
            .returning(WatchlistGroup)
        )
        try:
            async with self._session.begin_nested():
                group = await self._session.scalar(statement)
        except IntegrityError as error:
            if self._constraint_name(error) == "uq_watchlist_groups_user_name":
                raise WatchlistNameConflictError from error
            raise
        return self._to_group_record(group) if group is not None else None

    async def group_has_items_for_user(self, *, user_id: UUID, group_id: UUID) -> bool:
        """检查当前用户分组是否仍包含观察标的。"""
        value = await self._session.scalar(
            select(
                exists().where(
                    WatchlistItem.group_id == WatchlistGroup.id,
                )
            ).where(
                WatchlistGroup.id == group_id,
                WatchlistGroup.user_id == user_id,
            )
        )
        return bool(value)

    async def delete_empty_group_for_user(self, *, user_id: UUID, group_id: UUID) -> bool:
        """只删除当前用户的非默认空分组。"""
        contains_item = select(WatchlistItem.id).where(
            WatchlistItem.group_id == WatchlistGroup.id
        )
        statement = (
            delete(WatchlistGroup)
            .where(
                WatchlistGroup.id == group_id,
                WatchlistGroup.user_id == user_id,
                WatchlistGroup.is_default.is_(False),
                ~exists(contains_item),
            )
            .returning(WatchlistGroup.id)
        )
        return await self._session.scalar(statement) is not None

    async def list_items_for_user(
        self,
        *,
        user_id: UUID,
        group_id: UUID,
        offset: int,
        limit: int,
    ) -> tuple[list[WatchlistItemRecord], int]:
        """分页返回当前用户指定分组中的观察标的。"""
        condition = (
            (WatchlistItem.group_id == group_id)
            & (WatchlistGroup.user_id == user_id)
            & (WatchlistGroup.id == WatchlistItem.group_id)
        )
        items = (
            await self._session.scalars(
                select(WatchlistItem)
                .join(WatchlistGroup, WatchlistGroup.id == WatchlistItem.group_id)
                .where(condition)
                .order_by(
                    WatchlistItem.sort_order,
                    WatchlistItem.created_at,
                    WatchlistItem.id,
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
        total = await self._session.scalar(
            select(func.count())
            .select_from(WatchlistItem)
            .join(WatchlistGroup, WatchlistGroup.id == WatchlistItem.group_id)
            .where(condition)
        )
        return [self._to_item_record(item) for item in items], int(total or 0)

    async def get_item_for_user(
        self,
        *,
        user_id: UUID,
        item_id: UUID,
    ) -> WatchlistItemRecord | None:
        """按用户分组归属读取观察标的，越权与不存在均返回空。"""
        item = await self._session.scalar(
            select(WatchlistItem)
            .join(WatchlistGroup, WatchlistGroup.id == WatchlistItem.group_id)
            .where(
                WatchlistItem.id == item_id,
                WatchlistGroup.user_id == user_id,
            )
        )
        return self._to_item_record(item) if item is not None else None

    async def next_item_sort_order(self, *, user_id: UUID, group_id: UUID) -> int:
        """返回用户指定分组最大观察标的排序值之后的位置。"""
        value = await self._session.scalar(
            select(func.coalesce(func.max(WatchlistItem.sort_order) + 1, 0))
            .join(WatchlistGroup, WatchlistGroup.id == WatchlistItem.group_id)
            .where(
                WatchlistItem.group_id == group_id,
                WatchlistGroup.user_id == user_id,
            )
        )
        return int(value or 0)

    async def create_item_for_user(
        self,
        *,
        user_id: UUID,
        group_id: UUID,
        instrument_id: UUID,
        note: str | None,
        sort_order: int,
    ) -> WatchlistItemRecord | None:
        """只向当前用户分组添加活跃标的，并识别组内重复。"""
        references_valid = await self._session.scalar(
            select(func.count())
            .select_from(WatchlistGroup)
            .join(Instrument, Instrument.id == instrument_id)
            .where(
                WatchlistGroup.id == group_id,
                WatchlistGroup.user_id == user_id,
                Instrument.active.is_(True),
            )
        )
        if not references_valid:
            return None
        item = WatchlistItem(
            group_id=group_id,
            instrument_id=instrument_id,
            note=note,
            sort_order=sort_order,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(item)
                await self._session.flush()
        except IntegrityError as error:
            if self._constraint_name(error) == "uq_watchlist_items_group_instrument":
                raise WatchlistItemAlreadyExistsError from error
            raise
        return self._to_item_record(item)

    async def find_item_in_group_for_user(
        self,
        *,
        user_id: UUID,
        group_id: UUID,
        instrument_id: UUID,
    ) -> WatchlistItemRecord | None:
        """为重复添加或移动提示查找组内已有观察标的。"""
        item = await self._session.scalar(
            select(WatchlistItem)
            .join(WatchlistGroup, WatchlistGroup.id == WatchlistItem.group_id)
            .where(
                WatchlistItem.group_id == group_id,
                WatchlistItem.instrument_id == instrument_id,
                WatchlistGroup.user_id == user_id,
            )
        )
        return self._to_item_record(item) if item is not None else None

    async def update_item_for_user(
        self,
        *,
        user_id: UUID,
        item_id: UUID,
        version: int,
        group_id: UUID,
        note: str | None,
        sort_order: int,
        changed_at: datetime,
    ) -> WatchlistItemRecord | None:
        """仅在目标分组归属和版本匹配时修改、排序或移动观察标的。"""
        target_owned = await self._session.scalar(
            select(WatchlistGroup.id).where(
                WatchlistGroup.id == group_id,
                WatchlistGroup.user_id == user_id,
            )
        )
        if target_owned is None:
            return None
        owned_item = (
            select(WatchlistItem.id)
            .join(WatchlistGroup, WatchlistGroup.id == WatchlistItem.group_id)
            .where(
                WatchlistItem.id == item_id,
                WatchlistGroup.user_id == user_id,
            )
        )
        statement = (
            update(WatchlistItem)
            .where(
                WatchlistItem.id.in_(owned_item),
                WatchlistItem.version == version,
            )
            .values(
                group_id=group_id,
                note=note,
                sort_order=sort_order,
                version=WatchlistItem.version + 1,
                updated_at=changed_at,
            )
            .returning(WatchlistItem)
        )
        try:
            async with self._session.begin_nested():
                item = await self._session.scalar(statement)
        except IntegrityError as error:
            if self._constraint_name(error) == "uq_watchlist_items_group_instrument":
                raise WatchlistItemAlreadyExistsError from error
            raise
        return self._to_item_record(item) if item is not None else None

    async def delete_item_for_user(self, *, user_id: UUID, item_id: UUID) -> bool:
        """只删除当前用户分组中的指定观察标的。"""
        owned_item = (
            select(WatchlistItem.id)
            .join(WatchlistGroup, WatchlistGroup.id == WatchlistItem.group_id)
            .where(
                WatchlistItem.id == item_id,
                WatchlistGroup.user_id == user_id,
            )
        )
        statement = (
            delete(WatchlistItem)
            .where(WatchlistItem.id.in_(owned_item))
            .returning(WatchlistItem.id)
        )
        return await self._session.scalar(statement) is not None

    @staticmethod
    def _constraint_name(error: IntegrityError) -> str | None:
        """从 psycopg 异常诊断中读取约束名。"""
        diagnostic = getattr(error.orig, "diag", None)
        value = getattr(diagnostic, "constraint_name", None)
        return value if isinstance(value, str) else None

    @staticmethod
    def _to_group_record(group: WatchlistGroup) -> WatchlistGroupRecord:
        """把 ORM 自选分组转换为不可变领域记录。"""
        return WatchlistGroupRecord(
            id=group.id,
            user_id=group.user_id,
            name=group.name,
            is_default=group.is_default,
            sort_order=group.sort_order,
            version=group.version,
            created_at=group.created_at,
            updated_at=group.updated_at,
        )

    @staticmethod
    def _to_item_record(item: WatchlistItem) -> WatchlistItemRecord:
        """把 ORM 观察标的转换为不可变领域记录。"""
        return WatchlistItemRecord(
            id=item.id,
            group_id=item.group_id,
            instrument_id=item.instrument_id,
            note=item.note,
            sort_order=item.sort_order,
            version=item.version,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
