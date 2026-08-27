import {
  ApiClientError,
  apiErrorFromResponse,
  apiFetch,
  apiRequest,
} from '../../shared/api/client';
import type { components } from '../../shared/api/schema';

export type AIAnalysis = components['schemas']['AIAnalysisResponse'];
export type AnalysisConclusion = components['schemas']['AnalysisConclusion'];

export interface AnalysisTarget {
  id: string;
  assetType: 'STOCK' | 'FUND';
  name: string;
  ticker: string;
}

export type AIConversationStatus = 'IDLE' | 'RUNNING' | 'FAILED';
export type AIMessageRole = 'USER' | 'ASSISTANT';
export type AIMessageStatus = 'STREAMING' | 'COMPLETED' | 'FAILED';

export interface AIConversationMessage {
  id: string;
  role: AIMessageRole;
  status: AIMessageStatus;
  content: string;
  createdAt: string;
}

export interface AIConversation {
  id: string;
  instrument: {
    id: string;
    assetType: 'STOCK' | 'FUND';
    ticker: string;
    name: string;
  };
  title: string;
  status: AIConversationStatus;
  messages: AIConversationMessage[];
  createdAt: string;
  updatedAt: string;
}

export interface AIStreamCallbacks {
  onStart: (assistantMessageId: string) => void;
  onStatus: (message: string) => void;
  onDelta: (text: string) => void;
  onDone: (assistantMessageId: string, content: string) => void;
}

interface SSEFrame {
  event: string;
  data: Record<string, unknown>;
}

/** 表示模型已经开始流式响应后返回的业务错误。 */
export class AIStreamError extends Error {
  readonly code: string;

  /** 保存 SSE error 事件中的稳定错误码和可展示文案。 */
  constructor(code: string, message: string) {
    super(message);
    this.name = 'AIStreamError';
    this.code = code;
  }
}

/** 读取最近一次分析；兼容服务端新旧空状态且不触发模型调用。 */
export async function getAIAnalysis(instrumentId: string): Promise<AIAnalysis | null> {
  try {
    return await apiRequest(`/api/v1/instruments/${instrumentId}/ai-analysis`);
  } catch (error) {
    if (error instanceof ApiClientError && error.code === 'AI_ANALYSIS_NOT_FOUND') {
      return null;
    }
    throw error;
  }
}

/** 手动生成分析，并覆盖当前用户该标的的最近一份报告。 */
export function generateAIAnalysis(instrumentId: string): Promise<AIAnalysis> {
  return apiRequest(`/api/v1/instruments/${instrumentId}/ai-analysis`, { method: 'POST' });
}

/** 读取股票最近一次 Codex 多轮会话。 */
export function getLatestAIConversation(instrumentId: string): Promise<AIConversation | null> {
  return apiRequest(`/api/v1/instruments/${instrumentId}/ai-conversations/latest`);
}

/** 创建新的独立 Codex Session。 */
export function createAIConversation(instrumentId: string): Promise<AIConversation> {
  return apiRequest(`/api/v1/instruments/${instrumentId}/ai-conversations`, { method: 'POST' });
}

/** 重新读取会话消息，供流式结束或重新打开弹窗时恢复。 */
export function getAIConversation(conversationId: string): Promise<AIConversation> {
  return apiRequest(`/api/v1/ai-conversations/${conversationId}`);
}

/** 通过 POST SSE 逐帧消费 Codex 状态和文本增量。 */
export async function streamAIConversationMessage(
  conversationId: string,
  content: string,
  callbacks: AIStreamCallbacks,
): Promise<void> {
  const response = await apiFetch(`/api/v1/ai-conversations/${conversationId}/messages/stream`, {
    method: 'POST',
    headers: { Accept: 'text/event-stream' },
    body: JSON.stringify({ content }),
  });
  if (!response.ok) {
    throw await apiErrorFromResponse(response);
  }
  if (response.body === null) {
    throw new AIStreamError('AI_STREAM_UNAVAILABLE', '浏览器未收到分析数据流');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() ?? '';
    for (const rawFrame of frames) {
      dispatchSSEFrame(parseSSEFrame(rawFrame), callbacks);
    }
    if (done) {
      break;
    }
  }
  if (buffer.trim() !== '') {
    dispatchSSEFrame(parseSSEFrame(buffer), callbacks);
  }
}

/** 解析一个只包含 event 和 data 的服务器事件帧。 */
function parseSSEFrame(rawFrame: string): SSEFrame {
  let event = 'message';
  const dataLines: string[] = [];
  for (const line of rawFrame.split(/\r?\n/)) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  const data = JSON.parse(dataLines.join('\n')) as Record<string, unknown>;
  return { event, data };
}

/** 把 SSE 帧分派给对话状态更新回调。 */
function dispatchSSEFrame(frame: SSEFrame, callbacks: AIStreamCallbacks): void {
  if (frame.event === 'start') {
    callbacks.onStart(String(frame.data.assistantMessageId ?? ''));
  } else if (frame.event === 'status') {
    callbacks.onStatus(String(frame.data.message ?? ''));
  } else if (frame.event === 'delta') {
    callbacks.onDelta(String(frame.data.text ?? ''));
  } else if (frame.event === 'done') {
    callbacks.onDone(
      String(frame.data.assistantMessageId ?? ''),
      String(frame.data.content ?? ''),
    );
  } else if (frame.event === 'error') {
    throw new AIStreamError(
      String(frame.data.code ?? 'AI_AGENT_UNAVAILABLE'),
      String(frame.data.message ?? 'AI 分析暂时不可用，请重试'),
    );
  }
}
