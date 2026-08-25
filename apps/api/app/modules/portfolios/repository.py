"""投资账户数据库访问边界。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.portfolios.domain import InvestmentAccountRecord
from app.modules.portfolios.models import InvestmentAccount


class AccountNameConflictError(Exception):
    """表示数据库唯一约束拒绝账户重命名。"""


class InvestmentAccountRepository:
    """所有账户读写都显式携带当前用户 ID。"""

    def __init__(self, session: AsyncSession) -> None:
        """绑定请求事务中的数据库会话。"""
        self._session = session

    async def create_default_for_user(self, *, user_id: UUID) -> InvestmentAccountRecord:
        """幂等创建注册用户的默认人民币账户。"""
        statement = (
            insert(InvestmentAccount)
            .values(user_id=user_id, name="默认账户", base_currency="CNY", sort_order=0)
            .on_conflict_do_nothing(
                index_elements=[InvestmentAccount.user_id, InvestmentAccount.name]
            )
            .returning(InvestmentAccount)
        )
        account = await self._session.scalar(statement)
        if account is None:
            account = await self._session.scalar(
                select(InvestmentAccount).where(
                    InvestmentAccount.user_id == user_id,
                    InvestmentAccount.name == "默认账户",
                )
            )
        if account is None:
            raise RuntimeError("默认投资账户创建失败")
        return self._to_record(account)

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[InvestmentAccountRecord], int]:
        """按稳定排序分页返回当前用户账户和总数。"""
        condition = InvestmentAccount.user_id == user_id
        statement = (
            select(InvestmentAccount)
            .where(condition)
            .order_by(
                InvestmentAccount.sort_order,
                InvestmentAccount.created_at,
                InvestmentAccount.id,
            )
            .offset(offset)
            .limit(limit)
        )
        accounts = (await self._session.scalars(statement)).all()
        total = await self._session.scalar(
            select(func.count()).select_from(InvestmentAccount).where(condition)
        )
        return [self._to_record(account) for account in accounts], int(total or 0)

    async def get_for_user(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
    ) -> InvestmentAccountRecord | None:
        """按用户归属读取账户，越权与不存在均返回空。"""
        account = await self._session.scalar(
            select(InvestmentAccount).where(
                InvestmentAccount.id == account_id,
                InvestmentAccount.user_id == user_id,
            )
        )
        return self._to_record(account) if account is not None else None

    async def next_sort_order(self, *, user_id: UUID) -> int:
        """返回用户当前最大排序值之后的位置。"""
        value = await self._session.scalar(
            select(func.coalesce(func.max(InvestmentAccount.sort_order) + 1, 0)).where(
                InvestmentAccount.user_id == user_id
            )
        )
        return int(value or 0)

    async def create_for_user(
        self,
        *,
        user_id: UUID,
        name: str,
        sort_order: int,
    ) -> InvestmentAccountRecord | None:
        """创建同用户唯一账户，名称冲突时返回空。"""
        statement = (
            insert(InvestmentAccount)
            .values(
                user_id=user_id,
                name=name,
                base_currency="CNY",
                sort_order=sort_order,
            )
            .on_conflict_do_nothing(
                index_elements=[InvestmentAccount.user_id, InvestmentAccount.name]
            )
            .returning(InvestmentAccount)
        )
        account = await self._session.scalar(statement)
        return self._to_record(account) if account is not None else None

    async def update_for_user(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
        version: int,
        name: str | None,
        sort_order: int | None,
        changed_at: datetime,
    ) -> InvestmentAccountRecord | None:
        """仅在版本匹配时更新当前用户账户并递增版本。"""
        values: dict[str, object] = {
            "version": InvestmentAccount.version + 1,
            "updated_at": changed_at,
        }
        if name is not None:
            values["name"] = name
        if sort_order is not None:
            values["sort_order"] = sort_order
        statement = (
            update(InvestmentAccount)
            .where(
                InvestmentAccount.id == account_id,
                InvestmentAccount.user_id == user_id,
                InvestmentAccount.version == version,
            )
            .values(**values)
            .returning(InvestmentAccount)
        )
        try:
            async with self._session.begin_nested():
                account = await self._session.scalar(statement)
        except IntegrityError as error:
            raise AccountNameConflictError from error
        return self._to_record(account) if account is not None else None

    async def has_positions_for_user(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
    ) -> bool:
        """在持仓迁移存在时检查账户是否仍被当前用户持仓引用。"""
        positions_table = await self._session.scalar(text("SELECT to_regclass('public.positions')"))
        if positions_table is None:
            return False
        exists = await self._session.scalar(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM positions p "
                "JOIN investment_accounts a ON a.id = p.account_id "
                "WHERE p.account_id = :account_id AND a.user_id = :user_id"
                ")"
            ),
            {"account_id": account_id, "user_id": user_id},
        )
        return bool(exists)

    async def delete_for_user(self, *, user_id: UUID, account_id: UUID) -> bool:
        """删除当前用户账户；持仓外键加入后数据库继续保护非空账户。"""
        statement = (
            delete(InvestmentAccount)
            .where(
                InvestmentAccount.id == account_id,
                InvestmentAccount.user_id == user_id,
            )
            .returning(InvestmentAccount.id)
        )
        return await self._session.scalar(statement) is not None

    @staticmethod
    def _to_record(account: InvestmentAccount) -> InvestmentAccountRecord:
        """把 ORM 实例转换为不含内部状态的领域记录。"""
        return InvestmentAccountRecord(
            id=account.id,
            user_id=account.user_id,
            name=account.name,
            base_currency=account.base_currency,
            sort_order=account.sort_order,
            version=account.version,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )
