import { useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { ApiClientError } from '../../shared/api/client';
import { useModalDialog } from '../../shared/ui/useModalDialog';
import type { WatchlistGroup, WatchlistItem } from './api';
import { useDeleteWatchlistItem, useUpdateWatchlistItem } from './hooks';

interface WatchlistItemDialogProps {
  item: WatchlistItem;
  groups: WatchlistGroup[];
  onClose: () => void;
}

/** 修改观察标的备注、移动分组或在二次确认后删除。 */
export function WatchlistItemDialog({ item, groups, onClose }: WatchlistItemDialogProps) {
  const { dialogRef, closeDialog } = useModalDialog(onClose);
  const queryClient = useQueryClient();
  const updateMutation = useUpdateWatchlistItem();
  const deleteMutation = useDeleteWatchlistItem();
  const [groupId, setGroupId] = useState(item.groupId);
  const [note, setNote] = useState(item.note ?? '');
  const [confirmDelete, setConfirmDelete] = useState(false);

  /** 保存分组和备注的完整当前值，空备注显式清除。 */
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await updateMutation.mutateAsync({
        item,
        changes: { groupId, note: note.trim() || null },
      });
      closeDialog();
    } catch {
      // 冲突或重复时保留目标分组和备注。
    }
  }

  /** 删除用户已确认的观察标的。 */
  async function remove() {
    try {
      await deleteMutation.mutateAsync(item.id);
      closeDialog();
    } catch {
      // 对话框保持打开并展示统一错误。
    }
  }

  const error = updateMutation.error ?? deleteMutation.error;
  return (
    <dialog
      className="watchlist-dialog"
      ref={dialogRef}
      aria-labelledby="watchlist-item-dialog-title"
      onCancel={(event) => { event.preventDefault(); closeDialog(); }}
    >
      <header className="dialog-heading">
        <div>
          <p className="eyebrow">管理自选</p>
          <h2 id="watchlist-item-dialog-title">{item.instrument.name}</h2>
          <p className="watchlist-dialog__instrument">{item.instrument.ticker} · {item.instrument.exchange}</p>
        </div>
        <button className="text-button" type="button" onClick={closeDialog}>关闭</button>
      </header>
      <form className="watchlist-dialog__form" onSubmit={(event) => void submit(event)}>
        <label>
          <span>所属分组</span>
          <select required value={groupId} onChange={(event) => setGroupId(event.target.value)}>
            {groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
          </select>
        </label>
        <label>
          <span>备注（可选）</span>
          <textarea maxLength={500} rows={4} placeholder="例如：等待下一份财报" value={note} onChange={(event) => setNote(event.target.value)} />
        </label>
        <p className="watchlist-dialog__note">{note.length}/500 个字符</p>
        {error !== null && (
          <p className="form-error" role="alert">
            {error instanceof ApiClientError ? error.message : '操作失败，请稍后重试'}
          </p>
        )}
        {error instanceof ApiClientError && error.code === 'WATCHLIST_ITEM_VERSION_CONFLICT' && (
          <button
            className="text-button watchlist-dialog__reload"
            type="button"
            onClick={() => void queryClient.invalidateQueries({ queryKey: ['watchlist-items'] }).then(closeDialog)}
          >
            重新加载最新自选
          </button>
        )}
        <div className="watchlist-dialog__actions">
          {confirmDelete ? (
            <>
              <button className="danger-button" disabled={deleteMutation.isPending} type="button" onClick={() => void remove()}>确认移除</button>
              <button className="text-button" type="button" onClick={() => setConfirmDelete(false)}>取消</button>
            </>
          ) : (
            <button className="text-button danger-text" type="button" onClick={() => setConfirmDelete(true)}>移出自选</button>
          )}
          <button className="primary-button" disabled={updateMutation.isPending} type="submit">
            {updateMutation.isPending ? '正在保存…' : '保存修改'}
          </button>
        </div>
      </form>
    </dialog>
  );
}
