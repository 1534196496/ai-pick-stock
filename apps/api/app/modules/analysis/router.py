"""当前用户持仓或自选标的的 AI 报告与多轮会话接口。"""

import json
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import (
    get_ai_conversation_agent_service,
    get_ai_conversation_repository,
    get_ai_model_client,
    get_analysis_repository,
    get_current_identity,
    get_fund_nav_provider,
    get_market_data_repository,
    get_stock_price_provider,
)
from app.core.errors import ApiError
from app.modules.analysis.chat_service import AIConversationAgentService, AIStreamEvent
from app.modules.analysis.conversation_repository import (
    AIConversationRepository,
    conversation_response,
)
from app.modules.analysis.provider import AIModelClient
from app.modules.analysis.repository import AnalysisRepository
from app.modules.analysis.schemas import (
    AIAnalysisResponse,
    AIConversationMessageCreate,
    AIConversationResponse,
)
from app.modules.analysis.service import AIAnalysisService, AnalysisError
from app.modules.auth.domain import UserIdentity
from app.modules.market_data.providers.contracts import FundNavProvider, StockPriceProvider
from app.modules.market_data.repository import MarketDataRepository

router = APIRouter(prefix="/instruments", tags=["ai-analysis"])
conversation_router = APIRouter(prefix="/ai-conversations", tags=["ai-conversations"])


@router.get("/{instrument_id}/ai-analysis", response_model=AIAnalysisResponse | None)
async def get_ai_analysis(
    instrument_id: UUID,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    stock_provider: Annotated[StockPriceProvider, Depends(get_stock_price_provider)],
    fund_provider: Annotated[FundNavProvider, Depends(get_fund_nav_provider)],
    ai_client: Annotated[AIModelClient | None, Depends(get_ai_model_client)],
) -> AIAnalysisResponse | None:
    """读取最近报告；尚无报告返回空值，不产生新的模型费用。"""
    try:
        return await _service(
            repository,
            market_data_repository,
            stock_provider,
            fund_provider,
            ai_client,
        ).get_latest_report(user_id=identity.id, instrument_id=instrument_id)
    except AnalysisError as error:
        raise _api_error(error) from error


@router.post("/{instrument_id}/ai-analysis", response_model=AIAnalysisResponse)
async def generate_ai_analysis(
    instrument_id: UUID,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[AnalysisRepository, Depends(get_analysis_repository)],
    market_data_repository: Annotated[
        MarketDataRepository,
        Depends(get_market_data_repository),
    ],
    stock_provider: Annotated[StockPriceProvider, Depends(get_stock_price_provider)],
    fund_provider: Annotated[FundNavProvider, Depends(get_fund_nav_provider)],
    ai_client: Annotated[AIModelClient | None, Depends(get_ai_model_client)],
) -> AIAnalysisResponse:
    """刷新真实历史数据并手动生成或覆盖最近报告。"""
    try:
        return await _service(
            repository,
            market_data_repository,
            stock_provider,
            fund_provider,
            ai_client,
        ).generate_report(user_id=identity.id, instrument_id=instrument_id)
    except AnalysisError as error:
        raise _api_error(error) from error


@router.get(
    "/{instrument_id}/ai-conversations/latest",
    response_model=AIConversationResponse | None,
)
async def get_latest_ai_conversation(
    instrument_id: UUID,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    conversation_repository: Annotated[
        AIConversationRepository,
        Depends(get_ai_conversation_repository),
    ],
    analysis_repository: Annotated[
        AnalysisRepository,
        Depends(get_analysis_repository),
    ],
) -> AIConversationResponse | None:
    """读取当前用户指定标的最近一次多轮会话。"""
    instrument = await analysis_repository.get_tracked_instrument(
        user_id=identity.id,
        instrument_id=instrument_id,
    )
    if instrument is None:
        raise ApiError(
            status_code=404,
            code="INSTRUMENT_NOT_TRACKED",
            message="该标的不在你的持仓或自选中",
        )
    context = await conversation_repository.latest(
        user_id=identity.id,
        instrument_id=instrument_id,
    )
    if context is None:
        return None
    return await conversation_response(conversation_repository, context)


@router.post(
    "/{instrument_id}/ai-conversations",
    response_model=AIConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_ai_conversation(
    instrument_id: UUID,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[
        AIConversationRepository,
        Depends(get_ai_conversation_repository),
    ],
) -> AIConversationResponse:
    """为持仓或自选中的标的创建一个新的 Codex Session。"""
    try:
        context = await repository.create(
            user_id=identity.id,
            instrument_id=instrument_id,
        )
    except LookupError as error:
        raise ApiError(
            status_code=404,
            code="INSTRUMENT_NOT_TRACKED",
            message="该标的不在你的持仓或自选中",
        ) from error
    return await conversation_response(repository, context)


@conversation_router.get(
    "/{conversation_id}",
    response_model=AIConversationResponse,
)
async def get_ai_conversation(
    conversation_id: UUID,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[
        AIConversationRepository,
        Depends(get_ai_conversation_repository),
    ],
) -> AIConversationResponse:
    """读取属于当前用户的完整多轮对话。"""
    context = await repository.get_owned(
        user_id=identity.id,
        conversation_id=conversation_id,
    )
    if context is None:
        raise ApiError(
            status_code=404,
            code="AI_CONVERSATION_NOT_FOUND",
            message="AI 会话不存在",
        )
    return await conversation_response(repository, context)


@conversation_router.post(
    "/{conversation_id}/messages/stream",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Codex Agent 增量事件流",
            "content": {"text/event-stream": {}},
        }
    },
)
async def stream_ai_conversation_message(
    conversation_id: UUID,
    payload: AIConversationMessageCreate,
    identity: Annotated[UserIdentity, Depends(get_current_identity)],
    repository: Annotated[
        AIConversationRepository,
        Depends(get_ai_conversation_repository),
    ],
    agent_service: Annotated[
        AIConversationAgentService | None,
        Depends(get_ai_conversation_agent_service),
    ],
) -> StreamingResponse:
    """用 SSE 实时发送 Codex Skill 状态和逐段回复。"""
    context = await repository.get_owned(
        user_id=identity.id,
        conversation_id=conversation_id,
    )
    if context is None:
        raise ApiError(
            status_code=404,
            code="AI_CONVERSATION_NOT_FOUND",
            message="AI 会话不存在",
        )
    if agent_service is None:
        raise ApiError(
            status_code=503,
            code="AI_AGENT_NOT_CONFIGURED",
            message="服务器尚未配置 Codex Agent",
        )

    async def event_stream() -> AsyncIterator[str]:
        """把应用事件编码为标准 SSE 帧。"""
        async for event in agent_service.stream_message(
            user_id=identity.id,
            conversation_id=conversation_id,
            content=payload.content,
        ):
            yield _sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


def _service(
    repository: AnalysisRepository,
    market_data_repository: MarketDataRepository,
    stock_provider: StockPriceProvider,
    fund_provider: FundNavProvider,
    ai_client: AIModelClient | None,
) -> AIAnalysisService:
    """组装一次请求使用的分析服务。"""
    return AIAnalysisService(
        repository,
        market_data_repository,
        stock_provider,
        fund_provider,
        ai_client,
    )


def _api_error(error: AnalysisError) -> ApiError:
    """把分析错误映射为项目统一错误契约。"""
    return ApiError(
        status_code=error.status_code,
        code=error.code,
        message=error.message,
    )


def _sse(event: AIStreamEvent) -> str:
    """把单个应用事件编码为浏览器可增量解析的 SSE 文本。"""
    data = json.dumps(event.payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event.kind.value}\ndata: {data}\n\n"
