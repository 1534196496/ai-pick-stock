"""投资账户 HTTP 路由。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies import get_current_identity, get_investment_account_repository
from app.core.errors import ApiError
from app.modules.auth.domain import UserIdentity
from app.modules.portfolios.domain import InvestmentAccountRecord
from app.modules.portfolios.repository import InvestmentAccountRepository
from app.modules.portfolios.schemas import (
    CreateInvestmentAccountRequest,
    InvestmentAccountListResponse,
    InvestmentAccountResponse,
    UpdateInvestmentAccountRequest,
)
from app.modules.portfolios.service import InvestmentAccountError, InvestmentAccountService

router = APIRouter(prefix="/investment-accounts", tags=["investment-accounts"])


@router.get("", response_model=InvestmentAccountListResponse)
async def list_investment_accounts(
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[
        InvestmentAccountRepository,
        Depends(get_investment_account_repository),
    ],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 20,
) -> InvestmentAccountListResponse:
    """分页返回当前会话用户的投资账户。"""
    records, total = await InvestmentAccountService(repository).list_accounts(
        user_id=identity.id,
        page=page,
        page_size=page_size,
    )
    return InvestmentAccountListResponse(
        items=[_response(record) for record in records],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=InvestmentAccountResponse)
async def create_investment_account(
    payload: CreateInvestmentAccountRequest,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[
        InvestmentAccountRepository,
        Depends(get_investment_account_repository),
    ],
) -> InvestmentAccountResponse:
    """为当前用户创建名称唯一的人民币投资账户。"""
    try:
        record = await InvestmentAccountService(repository).create_account(
            user_id=identity.id,
            name=payload.name,
        )
    except InvestmentAccountError as error:
        raise _api_error(error) from error
    return _response(record)


@router.get("/{account_id}", response_model=InvestmentAccountResponse)
async def get_investment_account(
    account_id: UUID,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[
        InvestmentAccountRepository,
        Depends(get_investment_account_repository),
    ],
) -> InvestmentAccountResponse:
    """返回当前用户拥有的指定账户。"""
    try:
        record = await InvestmentAccountService(repository).get_account(
            user_id=identity.id,
            account_id=account_id,
        )
    except InvestmentAccountError as error:
        raise _api_error(error) from error
    return _response(record)


@router.patch("/{account_id}", response_model=InvestmentAccountResponse)
async def update_investment_account(
    account_id: UUID,
    payload: UpdateInvestmentAccountRequest,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[
        InvestmentAccountRepository,
        Depends(get_investment_account_repository),
    ],
) -> InvestmentAccountResponse:
    """按乐观锁版本重命名或调整当前用户账户排序。"""
    try:
        record = await InvestmentAccountService(repository).update_account(
            user_id=identity.id,
            account_id=account_id,
            version=payload.version,
            name=payload.name,
            sort_order=payload.sort_order,
        )
    except InvestmentAccountError as error:
        raise _api_error(error) from error
    return _response(record)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_investment_account(
    account_id: UUID,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[
        InvestmentAccountRepository,
        Depends(get_investment_account_repository),
    ],
) -> Response:
    """删除当前用户空账户。"""
    try:
        await InvestmentAccountService(repository).delete_account(
            user_id=identity.id,
            account_id=account_id,
        )
    except InvestmentAccountError as error:
        raise _api_error(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _response(record: InvestmentAccountRecord) -> InvestmentAccountResponse:
    """裁剪用户归属字段并生成公开响应。"""
    return InvestmentAccountResponse(
        id=record.id,
        name=record.name,
        base_currency=record.base_currency,
        sort_order=record.sort_order,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _api_error(error: InvestmentAccountError) -> ApiError:
    """把账户领域错误映射到稳定 HTTP 状态。"""
    if error.code == "ACCOUNT_NOT_FOUND":
        status_code = status.HTTP_404_NOT_FOUND
    elif error.code in {
        "ACCOUNT_NAME_ALREADY_EXISTS",
        "ACCOUNT_VERSION_CONFLICT",
        "ACCOUNT_NOT_EMPTY",
    }:
        status_code = status.HTTP_409_CONFLICT
    else:
        status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return ApiError(status_code=status_code, code=error.code, message=error.message)
