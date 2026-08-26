import { useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { ApiClientError } from '../../shared/api/client';
import { useModalDialog } from '../../shared/ui/useModalDialog';
import type { WatchlistGroup } from './api';
import {
  useCreateWatchlistGroup,
  useDeleteWatchlistGroup,
  useUpdateWatchlistGroup,
  watchlistGroupsQueryKey,
} from './hooks';
import './watchlists.css';

interface WatchlistGroupDialogProps {
  group?: WatchlistGroup;
  onCreated?: (group: WatchlistGroup) => void;
  onClose: () => void;
}

/** 创建、重命名或删除统一分组，并保留冲突时的用户输入。 */
export function WatchlistGroupDialog({ group, onCreated, onClose }: WatchlistGroupDialogProps) {
  const { dialogRef, closeDialog } = useModalDialog(onClose);
  const queryClient = useQueryClient();
  const createMutation = useCreateWatchlistGroup();
  const updateMutation = useUpdateWatchlistGroup();
  const deleteMutation = useDeleteWatchlistGroup();
  const mutation = group === undefined ? createMutation : updateMutation;
  const [name, setName] = useState(group?.name ?? '');
  const [confirmDelete, setConfirmDelete] = useState(false);

  /** 保存新分组或按当前版本重命名已有分组。 */
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      if (group === undefined) {
        const createdGroup = await createMutation.mutateAsync(name);
        onCreated?.(createdGroup);
      } else {
        await updateMutation.mutateAsync({ group, changes: { name } });
      }
      closeDialog();
    } catch {
      // 保留输入，让用户根据稳定错误提示恢复。
    }
  }

  /** 删除已确认的普通空分组。 */
  async function remove() {
    if (group === undefined) return;
    try {
      await deleteMutation.mutateAsync(group.id);
      closeDialog();
    } catch {
      // 保持对话框打开并展示服务端保护原因。
    }
  }

  const error = mutation.error ?? deleteMutation.error;
  return (
    <dialog
      className="watchlist-dialog"
      ref={dialogRef}
      aria-labelledby="watchlist-group-dialog-title"
      onCancel={(event) => { event.preventDefault(); closeDialog(); }}
    >
      <header className="dialog-heading">
        <div>
          <p className="eyebrow">持仓与自选共用</p>
          <h2 id="watchlist-group-dialog-title">{group === undefined ? '新建分组' : '管理分组'}</h2>
        </div>
        <button className="text-button" type="button" onClick={closeDialog}>关闭</button>
      </header>
      <form className="watchlist-dialog__form" onSubmit={(event) => void submit(event)}>
        <label>
          <span>分组名称</span>
          <input autoFocus maxLength={80} required value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        {group?.isDefault && <p className="watchlist-dialog__note">这是默认分组，可以重命名，但不能删除。</p>}
        {group !== undefined && !group.isDefault && (group.itemCount > 0 || group.positionCount > 0) && (
          <p className="watchlist-dialog__note">
            请先移走组内 {group.positionCount} 个持仓和 {group.itemCount} 个自选，再删除分组。
          </p>
        )}
        {error !== null && (
          <p className="form-error" role="alert">
            {error instanceof ApiClientError ? error.message : '操作失败，请稍后重试'}
          </p>
        )}
        {error instanceof ApiClientError && error.code === 'WATCHLIST_GROUP_VERSION_CONFLICT' && (
          <button
            className="text-button watchlist-dialog__reload"
            type="button"
            onClick={() => void queryClient.invalidateQueries({ queryKey: watchlistGroupsQueryKey }).then(closeDialog)}
          >
            重新加载最新分组
          </button>
        )}
        <div className="watchlist-dialog__actions">
          {group !== undefined && !group.isDefault && group.itemCount === 0 && group.positionCount === 0 && (
            confirmDelete ? (
              <>
                <button className="danger-button" disabled={deleteMutation.isPending} type="button" onClick={() => void remove()}>确认删除</button>
                <button className="text-button" type="button" onClick={() => setConfirmDelete(false)}>取消</button>
              </>
            ) : (
              <button className="text-button danger-text" type="button" onClick={() => setConfirmDelete(true)}>删除分组</button>
            )
          )}
          <button className="primary-button" disabled={mutation.isPending} type="submit">
            {mutation.isPending ? '正在保存…' : group === undefined ? '创建分组' : '保存名称'}
          </button>
        </div>
      </form>
    </dialog>
  );
}
