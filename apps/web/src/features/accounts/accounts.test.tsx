// @vitest-environment jsdom

import '@testing-library/jest-dom/vitest';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { AccountDialog } from './AccountDialog';
import { deleteInvestmentAccount } from './api';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const account = { id: '4f9e1d63-7d3a-4ddd-8a8c-712a0a8a3bb4', name: '默认账户', baseCurrency: 'CNY', sortOrder: 0, version: 1, createdAt: '2026-08-24T00:00:00Z', updatedAt: '2026-08-24T00:00:00Z' };
function response(body: unknown, status = 200) { return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }); }
function renderDialog() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><AccountDialog open onClose={() => undefined} /></QueryClientProvider>); }

describe('Account API', () => {
  it('删除空账户使用受 CSRF 保护的 DELETE 请求', async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(null, 204));
    vi.stubGlobal('fetch', fetchMock);
    await deleteInvestmentAccount(account.id);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe('DELETE');
    expect(new Headers(init.headers).get('X-CSRF-Token')).toHaveLength(32);
  });
});

describe('AccountDialog', () => {
  it('在用户菜单对话框内创建并重命名账户', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response({ items: [account], page: 1, pageSize: 100, total: 1 })).mockResolvedValueOnce(response({ ...account, id: 'new-id', name: '证券账户' }, 201)).mockResolvedValueOnce(response({ items: [account], page: 1, pageSize: 100, total: 1 })).mockResolvedValueOnce(response({ ...account, name: '长期账户', version: 2 })).mockResolvedValue(response({ items: [{ ...account, name: '长期账户', version: 2 }], page: 1, pageSize: 100, total: 1 }));
    vi.stubGlobal('fetch', fetchMock);
    renderDialog();
    expect(await screen.findByText('默认账户')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('新账户名称'), { target: { value: '证券账户' } });
    fireEvent.click(screen.getByRole('button', { name: '创建' }));
    await screen.findByText('默认账户');
    fireEvent.click(screen.getByRole('button', { name: '重命名' }));
    fireEvent.change(screen.getByLabelText('默认账户的新名称'), { target: { value: '长期账户' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/investment-accounts'), expect.anything());
  });

  it('版本冲突时保留编辑输入并显示可恢复错误', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response({ items: [account], page: 1, pageSize: 100, total: 1 })).mockResolvedValueOnce(response({ error: { code: 'ACCOUNT_VERSION_CONFLICT', message: '账户已在其他页面更新，请重新加载', requestId: 'req_conflict' } }, 409)));
    renderDialog();
    await screen.findByText('默认账户');
    fireEvent.click(screen.getByRole('button', { name: '重命名' }));
    const input = screen.getByLabelText('默认账户的新名称');
    fireEvent.change(input, { target: { value: '保留的名称' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('重新加载');
    expect(input).toHaveValue('保留的名称');
  });
});
