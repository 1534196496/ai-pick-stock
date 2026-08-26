import { useState } from 'react';

import { ApiClientError } from '../../shared/api/client';
import { FundPositionDialog } from '../holdings/FundPositionDialog';
import type { Position } from '../holdings/api';
import { StockPositionDialog } from '../holdings/StockPositionDialog';
import { InstrumentDialog } from '../instruments/InstrumentDialog';
import type { Instrument } from '../instruments/api';
import type { WatchlistGroup } from './api';
import type { WatchlistItem } from './api';
import {
  useCreateWatchlistItem,
  useUpdateWatchlistGroup,
  useWatchlistGroups,
  useWatchlistItems,
} from './hooks';
import { WatchlistGroupDialog } from './WatchlistGroupDialog';
import { WatchlistItemDialog } from './WatchlistItemDialog';
import { WatchlistItems } from './WatchlistItems';
import './watchlists.css';

interface HoldingTarget {
  instrument: Pick<Instrument, 'id' | 'assetType' | 'name' | 'ticker' | 'exchange'>;
  position?: Position;
}

/** 展示响应式自选分组导航，并为观察标的区域提供稳定选择状态。 */
export function WatchlistsPage() {
  const groups = useWatchlistGroups();
  const updateGroup = useUpdateWatchlistGroup();
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  const [groupDialogOpen, setGroupDialogOpen] = useState(false);
  const [editingGroup, setEditingGroup] = useState<WatchlistGroup | null>(null);
  const [instrumentDialogOpen, setInstrumentDialogOpen] = useState(false);
  const [editingItem, setEditingItem] = useState<WatchlistItem | null>(null);
  const [holdingTarget, setHoldingTarget] = useState<HoldingTarget | null>(null);
  const items = groups.data?.items ?? [];
  const effectiveGroupId = items.some((group) => group.id === selectedGroupId)
    ? selectedGroupId
    : (items.find((group) => group.isDefault) ?? items[0])?.id ?? null;
  const selectedGroup = items.find((group) => group.id === effectiveGroupId) ?? null;
  const watchlistItems = useWatchlistItems(effectiveGroupId);
  const createItem = useCreateWatchlistItem();

  /** 用现有乐观锁契约调整分组排序，失败时保留当前界面。 */
  async function moveGroup(group: WatchlistGroup, direction: -1 | 1) {
    const currentIndex = items.findIndex((item) => item.id === group.id);
    const targetIndex = currentIndex + direction;
    const neighbor = items[targetIndex];
    if (currentIndex < 1 || targetIndex < 1 || neighbor === undefined) return;
    try {
      await updateGroup.mutateAsync({
        group,
        changes: { sortOrder: neighbor.sortOrder },
      });
      await updateGroup.mutateAsync({
        group: neighbor,
        changes: { sortOrder: group.sortOrder },
      });
    } catch {
      // 分组列表保留服务端顺序，错误由后续管理操作统一恢复。
    }
  }

  /** 把选择的资产加入当前分组，重复项错误留在页面供恢复。 */
  async function addInstrument(instrument: Instrument) {
    if (selectedGroup === null) return;
    try {
      await createItem.mutateAsync({
        groupId: selectedGroup.id,
        instrumentId: instrument.id,
      });
    } catch {
      // 资产选择框关闭后在页面展示服务端稳定错误。
    }
  }

  return (
    <section className="ledger-page" aria-labelledby="watchlists-title">
      <header className="ledger-heading watchlists-heading">
        <div>
          <p className="eyebrow">观察清单</p>
          <h1 id="watchlists-title">自选</h1>
        </div>
        <button
          className="primary-button"
          disabled={selectedGroup === null || createItem.isPending}
          type="button"
          onClick={() => setInstrumentDialogOpen(true)}
        >
          添加股票或基金
        </button>
      </header>

      {groups.isError && <p className="form-error" role="alert">自选分组加载失败，请稍后重试。</p>}
      <div className="watchlists-layout">
        <aside className="watchlist-groups" aria-label="自选分组">
          <div className="watchlist-groups__heading">
            <h2>分组</h2>
            <button
              className="text-button"
              type="button"
              onClick={() => { setEditingGroup(null); setGroupDialogOpen(true); }}
            >
              新建
            </button>
          </div>
          {groups.isPending && <p className="watchlist-groups__status" role="status">正在读取分组…</p>}
          <label className="watchlist-group-select">
            <span>当前分组</span>
            <select value={effectiveGroupId ?? ''} onChange={(event) => setSelectedGroupId(event.target.value)}>
              {items.map((group) => (
                <option key={group.id} value={group.id}>
                  {group.name}（持仓 {group.positionCount} · 自选 {group.itemCount}）
                </option>
              ))}
            </select>
          </label>
          <ul className="watchlist-group-list">
            {items.map((group) => (
              <li className={group.id === effectiveGroupId ? 'watchlist-group watchlist-group--active' : 'watchlist-group'} key={group.id}>
                <button className="watchlist-group__select" type="button" onClick={() => setSelectedGroupId(group.id)}>
                  <span><strong>{group.name}</strong>{group.isDefault && <small>默认</small>}</span>
                  <span>{group.positionCount} 持仓 · {group.itemCount} 自选</span>
                </button>
                {group.id === effectiveGroupId && (
                  <div className="watchlist-group__actions">
                    {!group.isDefault && items.findIndex((item) => item.id === group.id) > 1 && <button aria-label={`上移${group.name}`} type="button" onClick={() => void moveGroup(group, -1)}>↑</button>}
                    {!group.isDefault && items.findIndex((item) => item.id === group.id) < items.length - 1 && <button aria-label={`下移${group.name}`} type="button" onClick={() => void moveGroup(group, 1)}>↓</button>}
                    <button type="button" onClick={() => { setEditingGroup(group); setGroupDialogOpen(true); }}>管理</button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </aside>

        <div className="watchlist-content">
          {createItem.error !== null && (
            <p className="form-error watchlist-content__error" role="alert">
              {createItem.error instanceof ApiClientError ? createItem.error.message : '添加失败，请稍后重试'}
            </p>
          )}
          {selectedGroup !== null ? (
            <>
              <header className="watchlist-content__heading">
                <div><p className="eyebrow">当前分组</p><h2>{selectedGroup.name}</h2></div>
                <span>{selectedGroup.itemCount} 个标的</span>
              </header>
              <WatchlistItems
                items={watchlistItems.data?.items ?? []}
                isPending={watchlistItems.isPending}
                isError={watchlistItems.isError}
                canAddToHoldings={items.length > 0}
                onEdit={setEditingItem}
                onAddToHoldings={(item) => setHoldingTarget({ instrument: item.instrument })}
              />
            </>
          ) : !groups.isPending && !groups.isError ? (
            <div className="empty-state empty-state--compact" role="status">
              <h2>还没有自选分组</h2>
              <p>创建第一个分组后即可添加观察标的。</p>
            </div>
          ) : null}
        </div>
      </div>

      {groupDialogOpen && (
        <WatchlistGroupDialog
          group={editingGroup ?? undefined}
          onClose={() => setGroupDialogOpen(false)}
        />
      )}
      <InstrumentDialog
        open={instrumentDialogOpen}
        initialAssetType={null}
        onClose={() => setInstrumentDialogOpen(false)}
        onSelect={(instrument) => void addInstrument(instrument)}
      />
      {editingItem !== null && (
        <WatchlistItemDialog
          item={editingItem}
          groups={items}
          onClose={() => setEditingItem(null)}
        />
      )}
      {holdingTarget?.instrument.assetType === 'STOCK' && (
        <StockPositionDialog
          key={holdingTarget.position?.id ?? holdingTarget.instrument.id}
          instrument={holdingTarget.instrument}
          groups={items}
          defaultGroupId={effectiveGroupId}
          position={holdingTarget.position}
          onExistingPosition={(position) => setHoldingTarget({
            instrument: position.instrument,
            position,
          })}
          onClose={() => setHoldingTarget(null)}
        />
      )}
      {holdingTarget?.instrument.assetType === 'FUND' && (
        <FundPositionDialog
          key={holdingTarget.position?.id ?? holdingTarget.instrument.id}
          instrument={holdingTarget.instrument}
          groups={items}
          defaultGroupId={effectiveGroupId}
          position={holdingTarget.position}
          onExistingPosition={(position) => setHoldingTarget({
            instrument: position.instrument,
            position,
          })}
          onClose={() => setHoldingTarget(null)}
        />
      )}
    </section>
  );
}
