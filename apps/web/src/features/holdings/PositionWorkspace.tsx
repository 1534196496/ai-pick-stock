import { useState } from 'react';

import type { Instrument } from '../instruments/api';
import type { WatchlistGroup } from '../watchlists/api';
import type { Position } from './api';
import { PositionList } from './PositionList';
import { PositionSortControl } from './PositionSortControl';
import {
  readPositionSort,
  savePositionSort,
  type PositionSort,
} from './positionSorting';

type AssetType = Instrument['assetType'];

interface PositionWorkspaceProps {
  groups: WatchlistGroup[];
  selectedGroupId: string | null;
  activeAssetType: AssetType;
  stockPositions: Position[];
  fundPositions: Position[];
  isPending: boolean;
  isError: boolean;
  onSelectGroup: (groupId: string | null) => void;
  onCreateGroup: () => void;
  onSelectAssetType: (assetType: AssetType) => void;
  onEdit: (position: Position) => void;
}

/** 以主分组标签和次级资产类型标签组织单张持仓表。 */
export function PositionWorkspace({
  groups,
  selectedGroupId,
  activeAssetType,
  stockPositions,
  fundPositions,
  isPending,
  isError,
  onSelectGroup,
  onCreateGroup,
  onSelectAssetType,
  onEdit,
}: PositionWorkspaceProps) {
  const [sorts, setSorts] = useState<Record<AssetType, PositionSort>>(() => ({
    STOCK: readPositionSort('STOCK'),
    FUND: readPositionSort('FUND'),
  }));
  const groupTabs = [
    { id: null, name: '全部' },
    ...groups,
  ];
  const activeGroupTabId = `position-group-tab-${selectedGroupId ?? 'all'}`;

  /** 更新当前资产类型的页面排序并保存浏览器偏好。 */
  function handleSortChange(sort: PositionSort): void {
    setSorts((current) => ({ ...current, [activeAssetType]: sort }));
    savePositionSort(activeAssetType, sort);
  }

  return (
    <section className="position-workspace" aria-label="持仓列表">
      <div className="position-group-navigation">
        <div className="position-group-tabs" role="tablist" aria-label="持仓分组">
          {groupTabs.map((group, index) => {
            const selected = group.id === selectedGroupId;
            const tabId = `position-group-tab-${group.id ?? 'all'}`;
            return (
              <button
                id={tabId}
                key={group.id ?? 'all'}
                className={`position-group-tab${selected ? ' position-group-tab--active' : ''}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls="position-group-panel"
                tabIndex={selected ? 0 : -1}
                onClick={() => onSelectGroup(group.id)}
                onKeyDown={(event) => {
                  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
                  event.preventDefault();
                  const lastIndex = groupTabs.length - 1;
                  const nextIndex = event.key === 'Home'
                    ? 0
                    : event.key === 'End'
                      ? lastIndex
                      : event.key === 'ArrowLeft'
                        ? (index - 1 + groupTabs.length) % groupTabs.length
                        : (index + 1) % groupTabs.length;
                  const nextGroup = groupTabs[nextIndex];
                  onSelectGroup(nextGroup.id);
                  document.getElementById(`position-group-tab-${nextGroup.id ?? 'all'}`)?.focus();
                }}
              >
                <span>{group.name}</span>
              </button>
            );
          })}
        </div>
        <button className="position-group-create" type="button" onClick={onCreateGroup}>
          ＋新建分组
        </button>
      </div>
      <div
        id="position-group-panel"
        className="position-workspace__body"
        role="tabpanel"
        aria-labelledby={activeGroupTabId}
      >
        <div className="position-asset-navigation">
          <div
            className="position-asset-tabs"
            role="tablist"
            aria-label="资产类型"
          >
            <AssetTab
              assetType="STOCK"
              activeAssetType={activeAssetType}
              count={stockPositions.length}
              onSelect={onSelectAssetType}
            >
              股票
            </AssetTab>
            <AssetTab
              assetType="FUND"
              activeAssetType={activeAssetType}
              count={fundPositions.length}
              onSelect={onSelectAssetType}
            >
              基金
            </AssetTab>
          </div>
          <PositionSortControl value={sorts[activeAssetType]} onChange={handleSortChange} />
        </div>
        <div className="position-workspace__content">
          <div
            id="position-asset-panel-stock"
            className="position-asset-panel"
            role="tabpanel"
            aria-labelledby="position-asset-tab-stock"
            hidden={activeAssetType !== 'STOCK'}
          >
            <PositionList
              title="股票持仓"
              assetType="STOCK"
              items={stockPositions}
              sort={sorts.STOCK}
              groups={groups}
              showGroupName={selectedGroupId === null}
              isPending={isPending}
              isError={isError}
              onEdit={onEdit}
            />
          </div>
          <div
            id="position-asset-panel-fund"
            className="position-asset-panel"
            role="tabpanel"
            aria-labelledby="position-asset-tab-fund"
            hidden={activeAssetType !== 'FUND'}
          >
            <PositionList
              title="基金持仓"
              assetType="FUND"
              items={fundPositions}
              sort={sorts.FUND}
              groups={groups}
              showGroupName={selectedGroupId === null}
              isPending={isPending}
              isError={isError}
              onEdit={onEdit}
            />
          </div>
        </div>
      </div>
    </section>
  );
}

interface AssetTabProps {
  assetType: AssetType;
  activeAssetType: AssetType;
  count: number;
  onSelect: (assetType: AssetType) => void;
  children: string;
}

/** 展示轻量且支持左右方向键切换的资产类型标签。 */
function AssetTab({
  assetType,
  activeAssetType,
  count,
  onSelect,
  children,
}: AssetTabProps) {
  const normalizedType = assetType.toLowerCase();
  const selected = assetType === activeAssetType;

  return (
    <button
      id={`position-asset-tab-${normalizedType}`}
      className={`position-asset-tab${selected ? ' position-asset-tab--active' : ''}`}
      type="button"
      role="tab"
      aria-selected={selected}
      aria-controls={`position-asset-panel-${normalizedType}`}
      tabIndex={selected ? 0 : -1}
      onClick={() => onSelect(assetType)}
      onKeyDown={(event) => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const nextType = event.key === 'ArrowLeft' || event.key === 'Home' ? 'STOCK' : 'FUND';
        onSelect(nextType);
        document.getElementById(`position-asset-tab-${nextType.toLowerCase()}`)?.focus();
      }}
    >
      <span>{children}</span>
      <span className="position-tab-count" aria-label={`${count} 项`}>{count}</span>
    </button>
  );
}
