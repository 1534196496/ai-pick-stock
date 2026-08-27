"""AI 分析内部输出与公开 API 契约。"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.schemas import ApiModel
from app.modules.analysis.enums import AIConversationStatus, AIMessageRole, AIMessageStatus
from app.modules.instruments.enums import AssetType, Currency, Exchange, Market

AnalysisText = Annotated[str, Field(min_length=2, max_length=500)]


class AnalysisConclusion(StrEnum):
    """用中性研究结论替代确定性买卖指令。"""

    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    CAUTIOUS = "CAUTIOUS"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class GeneratedAnalysis(BaseModel):
    """校验模型必须返回的最小结构化研究内容。"""

    model_config = ConfigDict(extra="forbid")

    conclusion: AnalysisConclusion
    summary: str = Field(min_length=20, max_length=1200)
    highlights: list[AnalysisText] = Field(min_length=1, max_length=5)
    risks: list[AnalysisText] = Field(min_length=1, max_length=5)
    actions: list[AnalysisText] = Field(min_length=1, max_length=4)

    @field_validator("summary", "highlights", "risks", "actions")
    @classmethod
    def strip_generated_text(cls, value: str | list[str]) -> str | list[str]:
        """清理模型输出首尾空白，并拒绝只有空白的内容。"""
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("模型文本不能为空")
            return stripped
        stripped_items = [item.strip() for item in value]
        if any(not item for item in stripped_items):
            raise ValueError("模型列表项不能为空")
        return stripped_items


class AnalysisInstrumentResponse(ApiModel):
    """返回分析结果对应的稳定资产身份。"""

    id: UUID
    asset_type: AssetType
    market: Market
    exchange: Exchange
    ticker: str
    name: str
    currency: Currency


class AnalysisMetricResponse(ApiModel):
    """返回页面直接展示的一项已计算指标。"""

    label: str
    value: str


class AIAnalysisResponse(ApiModel):
    """返回最近一次结构化 AI 分析及其数据溯源。"""

    id: UUID
    instrument: AnalysisInstrumentResponse
    provider: str
    model: str
    data_as_of: str
    data_sources: list[str]
    metrics: list[AnalysisMetricResponse]
    conclusion: AnalysisConclusion
    summary: str
    highlights: list[str]
    risks: list[str]
    actions: list[str]
    generated_at: datetime
    disclaimer: str = "仅供个人研究参考，不构成投资建议。"


class AIConversationMessageResponse(ApiModel):
    """返回一条已保存或正在生成的对话消息。"""

    id: UUID
    role: AIMessageRole
    status: AIMessageStatus
    content: str
    created_at: datetime


class AIConversationResponse(ApiModel):
    """返回当前用户独立的 Codex 会话及完整消息。"""

    id: UUID
    instrument: AnalysisInstrumentResponse
    title: str
    status: AIConversationStatus
    messages: list[AIConversationMessageResponse]
    created_at: datetime
    updated_at: datetime


class AIConversationMessageCreate(BaseModel):
    """校验用户发送给 Agent 的单轮文本。"""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        """去掉无意义空白并拒绝空消息。"""
        content = value.strip()
        if not content:
            raise ValueError("消息不能为空")
        return content
