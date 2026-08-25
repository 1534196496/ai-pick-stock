import { useState, type FormEvent } from 'react';

import { ApiClientError } from '../../shared/api/client';
import type { InvestmentAccount } from './api';
import {
  useCreateInvestmentAccount,
  useDeleteInvestmentAccount,
  useInvestmentAccounts,
  useUpdateInvestmentAccount,
} from './hooks';

interface AccountDialogProps { open: boolean; onClose: () => void; }

/** 在用户菜单内管理账户，不改变一级业务导航。 */
export function AccountDialog({ open, onClose }: AccountDialogProps) {
  const query = useInvestmentAccounts();
  const createMutation = useCreateInvestmentAccount();
  const updateMutation = useUpdateInvestmentAccount();
  const deleteMutation = useDeleteInvestmentAccount();
  const [newName, setNewName] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  if (!open) return null;
  const items = query.data?.items ?? [];
  const mutationError = createMutation.error ?? updateMutation.error ?? deleteMutation.error;

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try { await createMutation.mutateAsync(newName); setNewName(''); } catch { /* 保留输入供恢复。 */ }
  }

  async function rename(account: InvestmentAccount) {
    try { await updateMutation.mutateAsync({ account, changes: { name: editName } }); setEditingId(null); } catch { /* 冲突时保留编辑值。 */ }
  }

  async function move(account: InvestmentAccount, direction: -1 | 1) {
    const next = Math.max(0, account.sortOrder + direction);
    try { await updateMutation.mutateAsync({ account, changes: { sortOrder: next } }); } catch { /* 统一错误区展示。 */ }
  }

  return <dialog className="account-dialog" open aria-labelledby="account-dialog-title">
    <header className="dialog-heading"><div><p className="eyebrow">用户菜单</p><h2 id="account-dialog-title">投资账户</h2></div><button className="text-button" type="button" onClick={onClose}>关闭</button></header>
    <form className="inline-form" onSubmit={(event) => void create(event)}><label>新账户名称<input maxLength={80} required value={newName} onChange={(event) => setNewName(event.target.value)} /></label><button className="primary-button" disabled={createMutation.isPending} type="submit">创建</button></form>
    {query.isPending && <p role="status">正在加载账户…</p>}
    {query.isError && <p className="form-error" role="alert">账户加载失败，请稍后重试。</p>}
    <ul className="account-list">{items.map((account) => <li key={account.id}>
      {editingId === account.id ? <div className="account-edit"><input aria-label={`${account.name}的新名称`} value={editName} onChange={(event) => setEditName(event.target.value)} /><button type="button" onClick={() => void rename(account)}>保存</button><button type="button" onClick={() => setEditingId(null)}>取消</button></div> : <><div><strong>{account.name}</strong><span>{account.baseCurrency}</span></div><div className="row-actions"><button aria-label={`上移${account.name}`} type="button" onClick={() => void move(account, -1)}>↑</button><button aria-label={`下移${account.name}`} type="button" onClick={() => void move(account, 1)}>↓</button><button type="button" onClick={() => { setEditingId(account.id); setEditName(account.name); }}>重命名</button>{confirmDeleteId === account.id ? <><button type="button" onClick={() => void deleteMutation.mutateAsync(account.id).then(() => setConfirmDeleteId(null)).catch(() => undefined)}>确认删除</button><button type="button" onClick={() => setConfirmDeleteId(null)}>取消</button></> : <button type="button" onClick={() => setConfirmDeleteId(account.id)}>删除</button>}</div></>}
    </li>)}</ul>
    {mutationError !== null && <p className="form-error" role="alert">{mutationError instanceof ApiClientError ? mutationError.message : '操作失败，请重试'}</p>}
  </dialog>;
}
