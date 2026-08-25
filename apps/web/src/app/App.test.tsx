// @vitest-environment jsdom

/** 应用级路由、会话守卫与主导航契约测试。 */

import '@testing-library/jest-dom/vitest';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { AppRoutes } from './routes';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

/** 从指定地址渲染带独立 Query 缓存的应用路由。 */
function renderRoute(path: string) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter></QueryClientProvider>);
}

describe('AppRoutes', () => {
  it('登录页不展示登录后的业务导航', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ error: { code: 'AUTHENTICATION_REQUIRED', message: '请先登录', requestId: 'req_test' } }, 401)));
    renderRoute('/login');
    expect(await screen.findByRole('heading', { level: 1, name: '登录' })).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: '主要导航' })).not.toBeInTheDocument();
  });

  it('登录后只有持有和自选两个业务入口，并可完成页面切换', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ id: '4f9e1d63-7d3a-4ddd-8a8c-712a0a8a3bb4', email: 'owner@example.com', status: 'ACTIVE', createdAt: '2026-08-24T00:00:00Z' })));
    renderRoute('/holdings');
    const navigation = await screen.findByRole('navigation', { name: '主要导航' });
    const links = within(navigation).getAllByRole('link');
    expect(links).toHaveLength(2);
    expect(links.map((link) => link.textContent)).toEqual(['持有', '自选']);
    expect(screen.getByRole('heading', { level: 1, name: '持有' })).toBeInTheDocument();
    fireEvent.click(within(navigation).getByRole('link', { name: '自选' }));
    expect(screen.getByRole('heading', { level: 1, name: '自选' })).toBeInTheDocument();
  });
});
