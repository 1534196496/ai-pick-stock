"""AI 会话和消息状态枚举。"""

from enum import StrEnum


class AIConversationStatus(StrEnum):
    """表示一个会话当前是否可接受下一轮消息。"""

    IDLE = "IDLE"
    RUNNING = "RUNNING"
    FAILED = "FAILED"


class AIMessageRole(StrEnum):
    """区分用户输入和 Agent 回复。"""

    USER = "USER"
    ASSISTANT = "ASSISTANT"


class AIMessageStatus(StrEnum):
    """记录单条消息是否仍在生成或已经结束。"""

    STREAMING = "STREAMING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
