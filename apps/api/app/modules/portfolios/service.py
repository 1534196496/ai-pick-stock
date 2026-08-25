"""投资账户分页、唯一、排序与乐观锁用例。"""

from datetime import UTC, datetime
from uuid import UUID

from app.modules.portfolios.domain import InvestmentAccountRecord
from app.modules.portfolios.repository import (
    AccountNameConflictError,
    InvestmentAccountRepository,
)


class InvestmentAccountError(Exception):
    """表示可安全映射为公开契约的账户领域错误。"""

    def __init__(self, *, code: str, message: str) -> None:
        """保存稳定错误码和中文修正提示。"""
        super().__init__(message)
        self.code = code
        self.message = message


class InvestmentAccountService:
    """处理账户名称、用户归属、版本冲突和非空删除。"""

    def __init__(self, repository: InvestmentAccountRepository) -> None:
        """注入只接受用户 ID 的账户持久化边界。"""
        self._repository = repository

    async def list_accounts(
        self,
        *,
        user_id: UUID,
        page: int,
        page_size: int,
    ) -> tuple[list[InvestmentAccountRecord], int]:
        """按页码转换偏移并返回当前用户账户。"""
        return await self._repository.list_for_user(
            user_id=user_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )

    async def create_account(
        self,
        *,
        user_id: UUID,
        name: str,
    ) -> InvestmentAccountRecord:
        """规范化名称并追加到用户账户排序末尾。"""
        normalized = self._normalize_name(name)
        sort_order = await self._repository.next_sort_order(user_id=user_id)
        account = await self._repository.create_for_user(
            user_id=user_id,
            name=normalized,
            sort_order=sort_order,
        )
        if account is None:
            raise InvestmentAccountError(
                code="ACCOUNT_NAME_ALREADY_EXISTS",
                message="已经存在同名投资账户",
            )
        return account

    async def get_account(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
    ) -> InvestmentAccountRecord:
        """读取当前用户账户，越权和不存在统一 404 语义。"""
        account = await self._repository.get_for_user(
            user_id=user_id,
            account_id=account_id,
        )
        if account is None:
            raise InvestmentAccountError(
                code="ACCOUNT_NOT_FOUND",
                message="投资账户不存在",
            )
        return account

    async def update_account(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
        version: int,
        name: str | None,
        sort_order: int | None,
    ) -> InvestmentAccountRecord:
        """先确认归属与版本，再执行防覆盖更新。"""
        current = await self.get_account(user_id=user_id, account_id=account_id)
        if current.version != version:
            raise InvestmentAccountError(
                code="ACCOUNT_VERSION_CONFLICT",
                message="账户已在其他页面更新，请重新加载",
            )
        normalized_name = self._normalize_name(name) if name is not None else None
        try:
            updated = await self._repository.update_for_user(
                user_id=user_id,
                account_id=account_id,
                version=version,
                name=normalized_name,
                sort_order=sort_order,
                changed_at=datetime.now(UTC),
            )
        except AccountNameConflictError as error:
            raise InvestmentAccountError(
                code="ACCOUNT_NAME_ALREADY_EXISTS",
                message="已经存在同名投资账户",
            ) from error
        if updated is None:
            raise InvestmentAccountError(
                code="ACCOUNT_VERSION_CONFLICT",
                message="账户已在其他页面更新，请重新加载",
            )
        return updated

    async def delete_account(self, *, user_id: UUID, account_id: UUID) -> None:
        """只删除当前用户空账户，越权仍统一返回不存在。"""
        await self.get_account(user_id=user_id, account_id=account_id)
        if await self._repository.has_positions_for_user(
            user_id=user_id,
            account_id=account_id,
        ):
            raise InvestmentAccountError(
                code="ACCOUNT_NOT_EMPTY",
                message="账户仍有持仓，不能删除",
            )
        if not await self._repository.delete_for_user(
            user_id=user_id,
            account_id=account_id,
        ):
            raise InvestmentAccountError(
                code="ACCOUNT_NOT_FOUND",
                message="投资账户不存在",
            )

    @staticmethod
    def _normalize_name(name: str) -> str:
        """去除首尾空白并执行数据库一致的长度边界。"""
        normalized = name.strip()
        if not 1 <= len(normalized) <= 80:
            raise InvestmentAccountError(
                code="INVALID_ACCOUNT_NAME",
                message="账户名称长度必须为 1–80 个字符",
            )
        return normalized
