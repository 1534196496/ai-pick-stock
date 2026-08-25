"""投资账户分页、冲突与用户隔离 API 测试。"""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_identity, get_investment_account_repository
from app.main import create_app
from app.modules.auth.domain import UserIdentity
from app.modules.auth.enums import UserStatus
from app.modules.portfolios.domain import InvestmentAccountRecord

DUMMY_DATABASE_URL = "postgresql+psycopg://app:app@localhost:5432/app"
SECURE_HEADERS = {
    "Origin": "http://testserver",
    "X-CSRF-Token": "csrf-test-token-1234567890",
}


class FakeAccountRepository:
    """以内存记录模拟用户隔离、唯一、版本和非空状态。"""

    def __init__(self) -> None:
        """初始化账户集合和持仓占用集合。"""
        self.accounts: dict[UUID, InvestmentAccountRecord] = {}
        self.nonempty: set[UUID] = set()

    async def next_sort_order(self, *, user_id: UUID) -> int:
        """返回用户账户数量作为下一个排序值。"""
        return sum(account.user_id == user_id for account in self.accounts.values())

    async def list_for_user(
        self,
        *,
        user_id: UUID,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[InvestmentAccountRecord], int]:
        """按排序分页返回当前用户账户。"""
        records = sorted(
            (record for record in self.accounts.values() if record.user_id == user_id),
            key=lambda record: (record.sort_order, record.created_at, record.id),
        )
        return records[offset : offset + limit], len(records)

    async def get_for_user(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
    ) -> InvestmentAccountRecord | None:
        """越权读取返回空。"""
        record = self.accounts.get(account_id)
        return record if record is not None and record.user_id == user_id else None

    async def create_for_user(
        self,
        *,
        user_id: UUID,
        name: str,
        sort_order: int,
    ) -> InvestmentAccountRecord | None:
        """同用户同名时返回空。"""
        if any(
            record.user_id == user_id and record.name == name for record in self.accounts.values()
        ):
            return None
        now = datetime.now(UTC)
        record = InvestmentAccountRecord(
            id=uuid4(),
            user_id=user_id,
            name=name,
            base_currency="CNY",
            sort_order=sort_order,
            version=1,
            created_at=now,
            updated_at=now,
        )
        self.accounts[record.id] = record
        return record

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
        """版本和归属匹配时更新。"""
        current = await self.get_for_user(user_id=user_id, account_id=account_id)
        if current is None or current.version != version:
            return None
        updated = replace(
            current,
            name=name if name is not None else current.name,
            sort_order=sort_order if sort_order is not None else current.sort_order,
            version=current.version + 1,
            updated_at=changed_at,
        )
        self.accounts[account_id] = updated
        return updated

    async def has_positions_for_user(
        self,
        *,
        user_id: UUID,
        account_id: UUID,
    ) -> bool:
        """返回测试账户是否被持仓占用。"""
        return account_id in self.nonempty

    async def delete_for_user(self, *, user_id: UUID, account_id: UUID) -> bool:
        """仅删除当前用户账户。"""
        if await self.get_for_user(user_id=user_id, account_id=account_id) is None:
            return False
        del self.accounts[account_id]
        return True


@pytest.fixture
def account_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, FakeAccountRepository, UserIdentity, UserIdentity]:
    """创建注入当前用户和内存账户 Repository 的客户端。"""
    monkeypatch.setenv("AIPICKSTOCK_DATABASE_URL", DUMMY_DATABASE_URL)
    now = datetime.now(UTC)
    first = UserIdentity(
        id=uuid4(),
        email_normalized="first@example.com",
        status=UserStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    second = replace(first, id=uuid4(), email_normalized="second@example.com")
    repository = FakeAccountRepository()
    application = create_app()
    application.dependency_overrides[get_current_identity] = lambda: first
    application.dependency_overrides[get_investment_account_repository] = lambda: repository
    return TestClient(application, headers=SECURE_HEADERS), repository, first, second


def test_account_crud_pagination_and_version_increment(
    account_client: tuple[TestClient, FakeAccountRepository, UserIdentity, UserIdentity],
) -> None:
    """创建、分页、重命名、排序和删除空账户形成完整契约。"""
    client, _, _, _ = account_client
    with client:
        created = client.post(
            "/api/v1/investment-accounts",
            json={"name": " 证券账户 "},
        )
        listing = client.get("/api/v1/investment-accounts?page=1&pageSize=20")
        account_id = created.json()["id"]
        updated = client.patch(
            f"/api/v1/investment-accounts/{account_id}",
            json={"version": 1, "name": "长期账户", "sortOrder": 3},
        )
        deleted = client.delete(f"/api/v1/investment-accounts/{account_id}")
    assert created.status_code == 201
    assert created.json()["name"] == "证券账户"
    assert listing.json()["total"] == 1
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["sortOrder"] == 3
    assert deleted.status_code == 204


def test_duplicate_version_conflict_and_nonempty_delete_use_409(
    account_client: tuple[TestClient, FakeAccountRepository, UserIdentity, UserIdentity],
) -> None:
    """名称重复、旧版本和非空删除使用不同稳定错误码。"""
    client, repository, _, _ = account_client
    with client:
        first = client.post(
            "/api/v1/investment-accounts",
            json={"name": "证券账户"},
        )
        duplicate = client.post(
            "/api/v1/investment-accounts",
            json={"name": "证券账户"},
        )
        account_id = first.json()["id"]
        conflict = client.patch(
            f"/api/v1/investment-accounts/{account_id}",
            json={"version": 99, "name": "新名称"},
        )
        repository.nonempty.add(UUID(account_id))
        nonempty = client.delete(f"/api/v1/investment-accounts/{account_id}")
    assert duplicate.status_code == conflict.status_code == nonempty.status_code == 409
    assert duplicate.json()["error"]["code"] == "ACCOUNT_NAME_ALREADY_EXISTS"
    assert conflict.json()["error"]["code"] == "ACCOUNT_VERSION_CONFLICT"
    assert nonempty.json()["error"]["code"] == "ACCOUNT_NOT_EMPTY"


def test_cross_user_account_read_returns_same_404_as_missing(
    account_client: tuple[TestClient, FakeAccountRepository, UserIdentity, UserIdentity],
) -> None:
    """其他用户账户 ID 与随机 ID 都返回相同不存在语义。"""
    client, repository, _, second = account_client
    original_identity = client.app.dependency_overrides[get_current_identity]
    client.app.dependency_overrides[get_current_identity] = lambda: second
    with client:
        created = client.post(
            "/api/v1/investment-accounts",
            json={"name": "他人账户"},
        )
    client.app.dependency_overrides[get_current_identity] = original_identity
    with client:
        forbidden = client.get(f"/api/v1/investment-accounts/{created.json()['id']}")
        missing = client.get(f"/api/v1/investment-accounts/{uuid4()}")
    assert forbidden.status_code == missing.status_code == 404
    assert forbidden.json()["error"]["code"] == missing.json()["error"]["code"]
    assert len(repository.accounts) == 1
