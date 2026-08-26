import { useState } from 'react';

import { useWatchlistGroups } from '../watchlists/hooks';
import { WatchlistGroupDialog } from '../watchlists/WatchlistGroupDialog';
import type { Instrument } from '../instruments/api';
import { InstrumentDialog } from '../instruments/InstrumentDialog';
import { MarketDataDialog } from '../market-data/MarketDataDialog';
import { FundPositionDialog } from './FundPositionDialog';
import { HoldingsSummary } from './HoldingsSummary';
import type { Position } from './api';
import { usePositions, usePositionSummary } from './hooks';
import { PositionWorkspace } from './PositionWorkspace';
import { StockPositionDialog } from './StockPositionDialog';
import './holdings.css';

type AssetType = Instrument['assetType'];

/** 展示分组筛选、组合汇总和响应式持仓列表。 */
export function HoldingsPage() {
  const [selectedGroupId, setSelectedGroupId] = useState<string | null | undefined>(undefined);
  const [activeAssetType, setActiveAssetType] = useState<AssetType>('FUND');
  const [groupDialogOpen, setGroupDialogOpen] = useState(false);
  const [instrumentSearchOpen, setInstrumentSearchOpen] = useState(false);
  const [selectedInstrument, setSelectedInstrument] = useState<Instrument | null>(null);
  const [editingPosition, setEditingPosition] = useState<Position | null>(null);
  const [marketDataDialogOpen, setMarketDataDialogOpen] = useState(false);
  const groups = useWatchlistGroups();
  const groupItems = groups.data?.items ?? [];
  const groupId = selectedGroupId === undefined ? groupItems[0]?.id ?? null : selectedGroupId;
  const activeGroupName = groupId === null
    ? '全部分组'
    : groupItems.find((group) => group.id === groupId)?.name ?? '当前分组';
  const positions = usePositions(groupId);
  const summary = usePositionSummary(groupId);
  const stockPositions = (positions.data?.items ?? []).filter(
    (position) => position.instrument.assetType === 'STOCK',
  );
  const fundPositions = (positions.data?.items ?? []).filter(
    (position) => position.instrument.assetType === 'FUND',
  );

  return (
    <section className="ledger-page" aria-labelledby="holdings-title">
      <header className="ledger-heading holdings-heading">
        <div>
          <p className="eyebrow">{activeGroupName}</p>
          <h1 id="holdings-title">持有</h1>
        </div>
        <div className="holdings-heading__actions">
          <button className="secondary-button" type="button" onClick={() => setMarketDataDialogOpen(true)}>
            行情刷新
          </button>
          <button
            className="primary-button"
            type="button"
            disabled={groupItems.length === 0}
            onClick={() => setInstrumentSearchOpen(true)}
          >
            添加{activeAssetType === 'FUND' ? '基金' : '股票'}
          </button>
        </div>
      </header>
      <HoldingsSummary
        summary={summary.data}
        isPending={summary.isPending}
        isError={summary.isError}
      />
      <PositionWorkspace
        groups={groupItems}
        selectedGroupId={groupId}
        activeAssetType={activeAssetType}
        stockPositions={stockPositions}
        fundPositions={fundPositions}
        isPending={positions.isPending || groups.isPending}
        isError={positions.isError || groups.isError}
        onSelectGroup={setSelectedGroupId}
        onCreateGroup={() => setGroupDialogOpen(true)}
        onSelectAssetType={setActiveAssetType}
        onEdit={setEditingPosition}
      />
      {groupDialogOpen && (
        <WatchlistGroupDialog
          onCreated={(group) => setSelectedGroupId(group.id)}
          onClose={() => setGroupDialogOpen(false)}
        />
      )}
      {marketDataDialogOpen && (
        <MarketDataDialog onClose={() => setMarketDataDialogOpen(false)} />
      )}
      <InstrumentDialog
        open={instrumentSearchOpen}
        initialAssetType={activeAssetType}
        onClose={() => setInstrumentSearchOpen(false)}
        onSelect={(instrument) => {
          setActiveAssetType(instrument.assetType);
          setSelectedInstrument(instrument);
        }}
      />
      {selectedInstrument?.assetType === 'STOCK' && (
        <StockPositionDialog
          instrument={selectedInstrument}
          groups={groups.data?.items ?? []}
          defaultGroupId={groupId}
          onExistingPosition={(position) => {
            setSelectedInstrument(null);
            setEditingPosition(position);
          }}
          onClose={() => setSelectedInstrument(null)}
        />
      )}
      {selectedInstrument?.assetType === 'FUND' && (
        <FundPositionDialog
          instrument={selectedInstrument}
          groups={groups.data?.items ?? []}
          defaultGroupId={groupId}
          onExistingPosition={(position) => {
            setSelectedInstrument(null);
            setEditingPosition(position);
          }}
          onClose={() => setSelectedInstrument(null)}
        />
      )}
      {editingPosition?.instrument.assetType === 'STOCK' && (
        <StockPositionDialog
          instrument={editingPosition.instrument}
          groups={groups.data?.items ?? []}
          defaultGroupId={editingPosition.groupId}
          position={editingPosition}
          onClose={() => setEditingPosition(null)}
        />
      )}
      {editingPosition?.instrument.assetType === 'FUND' && (
        <FundPositionDialog
          instrument={editingPosition.instrument}
          groups={groups.data?.items ?? []}
          defaultGroupId={editingPosition.groupId}
          position={editingPosition}
          onClose={() => setEditingPosition(null)}
        />
      )}
    </section>
  );
}
