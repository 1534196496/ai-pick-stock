import { useState } from 'react';

import { useInvestmentAccounts } from '../accounts/hooks';
import type { Instrument } from '../instruments/api';
import { InstrumentDialog } from '../instruments/InstrumentDialog';
import { FundPositionDialog } from './FundPositionDialog';
import { HoldingsSummary } from './HoldingsSummary';
import type { Position } from './api';
import { usePositions, usePositionSummary } from './hooks';
import { PositionList } from './PositionList';
import { StockPositionDialog } from './StockPositionDialog';
import './holdings.css';

/** 展示账户筛选、组合汇总和响应式持仓列表。 */
export function HoldingsPage() {
  const [accountId, setAccountId] = useState<string | null>(null);
  const [instrumentSearchOpen, setInstrumentSearchOpen] = useState(false);
  const [selectedInstrument, setSelectedInstrument] = useState<Instrument | null>(null);
  const [editingPosition, setEditingPosition] = useState<Position | null>(null);
  const accounts = useInvestmentAccounts();
  const positions = usePositions(accountId);
  const summary = usePositionSummary(accountId);

  return (
    <section className="ledger-page" aria-labelledby="holdings-title">
      <header className="ledger-heading holdings-heading">
        <div>
          <p className="eyebrow">{accountId === null ? '全部账户' : '单一账户'}</p>
          <h1 id="holdings-title">持有</h1>
        </div>
        <div className="holdings-actions">
          <label className="account-filter">
            <span>投资账户</span>
            <select
              value={accountId ?? ''}
              onChange={(event) => setAccountId(event.target.value || null)}
            >
              <option value="">全部账户</option>
              {(accounts.data?.items ?? []).map((account) => (
                <option key={account.id} value={account.id}>{account.name}</option>
              ))}
            </select>
          </label>
          <button
            className="primary-button"
            type="button"
            disabled={(accounts.data?.items.length ?? 0) === 0}
            onClick={() => setInstrumentSearchOpen(true)}
          >
            添加持仓
          </button>
        </div>
      </header>
      <HoldingsSummary
        summary={summary.data}
        isPending={summary.isPending}
        isError={summary.isError}
      />
      <PositionList
        items={positions.data?.items ?? []}
        accounts={accounts.data?.items ?? []}
        isPending={positions.isPending}
        isError={positions.isError || accounts.isError}
        onEdit={setEditingPosition}
      />
      <InstrumentDialog
        open={instrumentSearchOpen}
        initialAssetType={null}
        onClose={() => setInstrumentSearchOpen(false)}
        onSelect={setSelectedInstrument}
      />
      {selectedInstrument?.assetType === 'STOCK' && (
        <StockPositionDialog
          instrument={selectedInstrument}
          accounts={accounts.data?.items ?? []}
          defaultAccountId={accountId}
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
          accounts={accounts.data?.items ?? []}
          defaultAccountId={accountId}
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
          accounts={accounts.data?.items ?? []}
          defaultAccountId={editingPosition.accountId}
          position={editingPosition}
          onClose={() => setEditingPosition(null)}
        />
      )}
      {editingPosition?.instrument.assetType === 'FUND' && (
        <FundPositionDialog
          instrument={editingPosition.instrument}
          accounts={accounts.data?.items ?? []}
          defaultAccountId={editingPosition.accountId}
          position={editingPosition}
          onClose={() => setEditingPosition(null)}
        />
      )}
    </section>
  );
}
