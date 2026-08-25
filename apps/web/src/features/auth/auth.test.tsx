// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';

import { LoginPage } from './pages';
import { ProtectedRoute } from './ProtectedRoute';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function renderWithProviders(node: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter>{node}</MemoryRouter></QueryClientProvider>);
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

describe('认证页面与守卫', () => {
  it('键盘可提交登录并在错误中显示请求 ID', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(jsonResponse({ error: { code: 'AUTHENTICATION_REQUIRED', message: '请先登录', requestId: 'req_session' } }, 401)).mockResolvedValueOnce(jsonResponse({ error: { code: 'INVALID_CREDENTIALS', message: '邮箱或密码错误', requestId: 'req_login' } }, 401)));
    renderWithProviders(<Routes><Route path="*" element={<LoginPage />} /></Routes>);
    fireEvent.change(await screen.findByLabelText('邮箱'), { target: { value: 'owner@example.com' } });
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'wrong-long-password' } });
    fireEvent.submit(screen.getByRole('button', { name: '登录' }).closest('form')!);
    expect(await screen.findByRole('alert')).toHaveTextContent('请求：req_login');
  });

  it('未登录用户被守卫送回登录页', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ error: { code: 'AUTHENTICATION_REQUIRED', message: '请先登录', requestId: 'req_session' } }, 401)));
    renderWithProviders(<Routes><Route element={<ProtectedRoute />}><Route path="*" element={<h1>私有页面</h1>} /></Route><Route path="/login" element={<h1>登录入口</h1>} /></Routes>);
    await waitFor(() => expect(screen.getByRole('heading', { name: '登录入口' })).toBeInTheDocument());
  });
});
