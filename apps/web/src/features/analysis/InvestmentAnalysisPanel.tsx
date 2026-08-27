import {
  type FormEvent,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { ApiClientError } from '../../shared/api/client';
import {
  AIStreamError,
  type AIConversation,
  type AIConversationMessage,
  type AnalysisTarget,
  createAIConversation,
  getAIConversation,
  getLatestAIConversation,
  streamAIConversationMessage,
} from './api';

interface InvestmentAnalysisPanelProps {
  instrument: AnalysisTarget;
  onClose?: () => void;
}

/** 提供可嵌入任意页面容器的持久 Session、多轮追问和实时输出。 */
export function InvestmentAnalysisPanel({
  instrument,
  onClose,
}: InvestmentAnalysisPanelProps) {
  const assetLabel = instrument.assetType === 'FUND' ? '基金' : '股票';
  const skillName = instrument.assetType === 'FUND' ? 'fund-analysis' : 'stock-analysis';
  const headingId = useId();
  const [conversation, setConversation] = useState<AIConversation | null>(null);
  const [messages, setMessages] = useState<AIConversationMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(true);
  const [streaming, setStreaming] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const streamActiveRef = useRef(false);
  const autoStartedConversationRef = useRef<string | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);

  /** 发送一轮消息，并按 SSE 增量更新同一个助手消息。 */
  const runTurn = useCallback(async (
    targetConversation: AIConversation,
    content: string,
  ): Promise<void> => {
    if (streamActiveRef.current) {
      return;
    }
    streamActiveRef.current = true;
    setStreaming(true);
    setError(null);
    setStatus('正在连接分析助手…');
    const createdAt = new Date().toISOString();
    const userMessageId = `local-user-${crypto.randomUUID()}`;
    const pendingAssistantId = `local-assistant-${crypto.randomUUID()}`;
    let assistantMessageId = pendingAssistantId;
    setMessages((current) => [
      ...current,
      {
        id: userMessageId,
        role: 'USER',
        status: 'COMPLETED',
        content,
        createdAt,
      },
      {
        id: pendingAssistantId,
        role: 'ASSISTANT',
        status: 'STREAMING',
        content: '',
        createdAt,
      },
    ]);

    try {
      await streamAIConversationMessage(targetConversation.id, content, {
        onStart: (messageId) => {
          assistantMessageId = messageId;
          setMessages((current) => current.map((message) => (
            message.id === pendingAssistantId ? { ...message, id: messageId } : message
          )));
        },
        onStatus: setStatus,
        onDelta: (text) => {
          setMessages((current) => current.map((message) => (
            message.id === assistantMessageId || message.id === pendingAssistantId
              ? { ...message, content: message.content + text }
              : message
          )));
        },
        onDone: (messageId, finalContent) => {
          assistantMessageId = messageId;
          setMessages((current) => current.map((message) => (
            message.id === messageId || message.id === pendingAssistantId
              ? {
                  ...message,
                  id: messageId,
                  status: 'COMPLETED',
                  content: finalContent,
                }
              : message
          )));
        },
      });
      const refreshed = await getAIConversation(targetConversation.id);
      setConversation(refreshed);
      setMessages(refreshed.messages);
    } catch (cause) {
      setError(formatChatError(cause));
      setMessages((current) => current.map((message) => (
        message.id === assistantMessageId || message.id === pendingAssistantId
          ? { ...message, status: 'FAILED' }
          : message
      )));
    } finally {
      streamActiveRef.current = false;
      setStreaming(false);
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    /** 打开分析面板时恢复最近 Session；空会话自动开始首次 Skill 分析。 */
    async function openConversation(): Promise<void> {
      setLoading(true);
      setError(null);
      try {
        const latest = await getLatestAIConversation(instrument.id);
        const opened = latest ?? await createAIConversation(instrument.id);
        setConversation(opened);
        setMessages(opened.messages);
        if (
          opened.messages.length === 0
          && autoStartedConversationRef.current !== opened.id
        ) {
          autoStartedConversationRef.current = opened.id;
          await runTurn(opened, `分析 ${instrument.ticker}`);
        }
      } catch (cause) {
        setError(formatChatError(cause));
      } finally {
        setLoading(false);
      }
    }

    void openConversation();
  }, [instrument.id, instrument.ticker, runTurn]);

  useEffect(() => {
    transcriptRef.current?.scrollTo({
      top: transcriptRef.current.scrollHeight,
      behavior: streaming ? 'smooth' : 'auto',
    });
  }, [messages, status, streaming]);

  /** 创建全新 Session，并立即执行首次标的分析。 */
  async function handleNewConversation(): Promise<void> {
    if (streamActiveRef.current) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const created = await createAIConversation(instrument.id);
      autoStartedConversationRef.current = created.id;
      setConversation(created);
      setMessages([]);
      await runTurn(created, `分析 ${instrument.ticker}`);
    } catch (cause) {
      setError(formatChatError(cause));
    } finally {
      setLoading(false);
    }
  }

  /** 提交用户追问，空文本和生成期间不重复发送。 */
  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const content = input.trim();
    if (content === '' || conversation === null || streaming) {
      return;
    }
    setInput('');
    void runTurn(conversation, content);
  }

  /** Enter 发送，Shift+Enter 保留为换行。 */
  function handleInputKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <section className="ai-conversation-panel" aria-labelledby={headingId}>
      <header className="dialog-heading ai-analysis-heading ai-chat-heading">
        <div>
          <p className="eyebrow">{assetLabel}研究助手</p>
          <h2 id={headingId}>{instrument.name}</h2>
          <p>{instrument.ticker} · {skillName} Skill</p>
        </div>
        <div className="ai-chat-heading-actions">
          <button
            className="text-button"
            type="button"
            disabled={streaming || loading}
            onClick={() => void handleNewConversation()}
          >
            新会话
          </button>
          {onClose !== undefined && (
            <button
              className="text-button"
              type="button"
              aria-label="关闭 AI 分析"
              onClick={onClose}
            >
              关闭
            </button>
          )}
        </div>
      </header>

      <div className="ai-chat-transcript" ref={transcriptRef} aria-live="polite">
        {loading && messages.length === 0 && (
          <p className="ai-analysis-status" role="status">正在打开分析会话…</p>
        )}
        {!loading && messages.length === 0 && error === null && (
          <p className="ai-analysis-status">正在准备首次分析…</p>
        )}
        {messages.map((message) => (
          <article
            className={`ai-chat-message ai-chat-message--${message.role.toLowerCase()}`}
            key={message.id}
          >
            <div className="ai-chat-message-label">
              {message.role === 'USER' ? '你' : 'AI'}
            </div>
            <div className="ai-chat-message-content">
              {message.role === 'ASSISTANT' ? (
                message.content === '' ? (
                  <span className="ai-chat-cursor" aria-label="正在生成" />
                ) : (
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {normalizeMarkdown(message.content)}
                  </ReactMarkdown>
                )
              ) : <p>{message.content}</p>}
              {message.status === 'FAILED' && (
                <small>本轮未完整生成，可以直接重试。</small>
              )}
            </div>
          </article>
        ))}
        {status !== null && <p className="ai-chat-live-status" role="status">{status}</p>}
      </div>

      <form className="ai-chat-composer" onSubmit={handleSubmit}>
        {error !== null && <p className="form-error" role="alert">{error}</p>}
        <div>
          <textarea
            aria-label="继续追问"
            value={input}
            maxLength={4000}
            rows={2}
            placeholder="继续追问，例如：这个位置适合加仓吗？"
            disabled={conversation === null || loading}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleInputKeyDown}
          />
          <button
            className="primary-button"
            type="submit"
            disabled={conversation === null || streaming || input.trim() === ''}
          >
            {streaming ? '分析中…' : '发送'}
          </button>
        </div>
        <small>Enter 发送，Shift+Enter 换行 · 仅供个人研究参考</small>
      </form>
    </section>
  );
}

/** 给中文粗体内容补充分隔空格，避免 CommonMark 把星号当作普通文本。 */
function normalizeMarkdown(content: string): string {
  return content.replace(/\*\*([^*\n]+)\*\*(?=\S)/g, '**$1** ');
}

/** 把 HTTP 与流内错误转换为简短可恢复文案。 */
function formatChatError(error: unknown): string {
  if (error instanceof ApiClientError || error instanceof AIStreamError) {
    return error.message;
  }
  return 'AI 分析暂时不可用，请重试';
}
