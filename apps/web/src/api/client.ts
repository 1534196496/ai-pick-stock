import { client } from './generated/client.gen';

const unsafeMethods = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

/** 从可读的双提交 Cookie 中解析当前 CSRF Token。 */
function readCsrfToken() {
  const prefix = import.meta.env.PROD ? '__Host-aipickstock_csrf=' : 'aipickstock_csrf=';
  const cookie = document.cookie
    .split('; ')
    .find((value) => value.startsWith(prefix));
  return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : undefined;
}

client.setConfig({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? '',
  credentials: 'include',
});

client.interceptors.request.use((request) => {
  if (unsafeMethods.has(request.method.toUpperCase())) {
    const csrfToken = readCsrfToken();
    if (csrfToken) {
      request.headers.set('X-CSRF-Token', csrfToken);
    }
  }
  return request;
});

/** 共享生成客户端；所有页面请求均携带会话 Cookie 与写请求 CSRF 头。 */
export const apiClient = client;
