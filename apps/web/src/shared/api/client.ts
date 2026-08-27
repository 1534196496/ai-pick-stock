import type { components } from './schema';

export type ApiErrorPayload = components['schemas']['ErrorResponse'];

/** 表示后端已按统一错误契约拒绝请求。 */
export class ApiClientError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown> | null;
  readonly requestId: string;

  /** 保存可安全展示的错误信息与排障请求 ID。 */
  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.error.message);
    this.name = 'ApiClientError';
    this.status = status;
    this.code = payload.error.code;
    this.details = payload.error.details ?? null;
    this.requestId = payload.error.requestId;
  }
}

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);
let csrfToken: string | null = null;

/** 为同源状态变更请求生成不持久化到服务器的高熵 CSRF 请求头。 */
function getCsrfToken(): string {
  if (csrfToken === null) {
    csrfToken = crypto.randomUUID().replaceAll('-', '');
  }
  return csrfToken;
}

/** 通过同源 Cookie 发起请求，并为普通 JSON 与流式接口统一补齐请求头。 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const method = (init.method ?? 'GET').toUpperCase();
  const headers = new Headers(init.headers);
  if (!headers.has('Accept')) {
    headers.set('Accept', 'application/json');
  }
  if (init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  if (!SAFE_METHODS.has(method)) {
    headers.set('X-CSRF-Token', getCsrfToken());
  }

  return fetch(path, {
    ...init,
    credentials: 'same-origin',
    headers,
  });
}

/** 把非成功响应解析为项目统一的客户端错误。 */
export async function apiErrorFromResponse(response: Response): Promise<ApiClientError> {
  const payload = await response.json() as ApiErrorPayload;
  return new ApiClientError(response.status, payload);
}

/** 通过同源 Cookie 调用 API，并统一解析成功与错误契约。 */
export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await apiFetch(path, init);
  if (response.status === 204) {
    return undefined as T;
  }
  const payload: unknown = await response.json();
  if (!response.ok) {
    throw new ApiClientError(response.status, payload as ApiErrorPayload);
  }
  return payload as T;
}
