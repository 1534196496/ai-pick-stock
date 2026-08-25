import { afterEach, describe, expect, it, vi } from 'vitest';

import { ApiClientError, apiRequest } from './client';

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('apiRequest', () => {
  it('状态变更请求携带同源凭据和高熵 CSRF 请求头', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    await apiRequest('/api/v1/test', { method: 'POST', body: '{}' });

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(init.credentials).toBe('same-origin');
    expect(headers.get('X-CSRF-Token')).toHaveLength(32);
  });

  it('统一错误响应转换为带请求 ID 的 ApiClientError', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: 'AUTHENTICATION_REQUIRED',
              message: '请先登录',
              requestId: 'req_test',
            },
          }),
          { status: 401, headers: { 'Content-Type': 'application/json' } },
        ),
      ),
    );

    try {
      await apiRequest('/api/v1/auth/session');
      expect.unreachable('请求应抛出统一 API 错误');
    } catch (error) {
      expect(error).toBeInstanceOf(ApiClientError);
      const apiError = error as ApiClientError;
      expect(apiError.code).toBe('AUTHENTICATION_REQUIRED');
      expect(apiError.requestId).toBe('req_test');
      expect(apiError.status).toBe(401);
    }
  });
});
