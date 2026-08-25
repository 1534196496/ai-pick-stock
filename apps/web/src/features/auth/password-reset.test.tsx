// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { ForgotPasswordPage, ResetPasswordPage } from './PasswordResetPages';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function renderPage(node: React.ReactNode, path = '/') {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[path]}>{node}</MemoryRouter></QueryClientProvider>);
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

describe('密码重置页面', () => {
  it('请求邮件后只显示统一成功文案', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ message: '如果该邮箱已注册，我们会发送密码重置邮件' }, 202)));
    renderPage(<ForgotPasswordPage />);
    fireEvent.change(screen.getByLabelText('注册邮箱'), { target: { value: 'owner@example.com' } });
    fireEvent.click(screen.getByRole('button', { name: '发送重置邮件' }));
    expect(await screen.findByRole('status')).toHaveTextContent('如果该邮箱已注册');
    expect(screen.queryByText(/owner@example.com/)).not.toBeInTheDocument();
  });

  it('过期令牌显示重新申请路径', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ error: { code: 'INVALID_OR_EXPIRED_RESET_TOKEN', message: '重置链接无效或已过期', requestId: 'req_reset' } }, 422)));
    renderPage(<ResetPasswordPage />, '/reset-password?token=expired-token');
    fireEvent.change(screen.getByLabelText('新密码'), { target: { value: 'new-correct-password-123' } });
    fireEvent.change(screen.getByLabelText('再次输入新密码'), { target: { value: 'new-correct-password-123' } });
    fireEvent.click(screen.getByRole('button', { name: '设置新密码' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('无效或已过期');
    expect(screen.getByRole('link', { name: '重新申请链接' })).toHaveAttribute('href', '/forgot-password');
  });
});
