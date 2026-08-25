import {
  useDeferredValue,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
} from 'react';

import type { AssetType, Instrument } from './api';
import { useInstrumentSearch } from './hooks';
import { SearchResults } from './SearchResults';
import './instruments.css';

interface InstrumentDialogProps {
  open: boolean;
  onClose: () => void;
  onSelect: (instrument: Instrument) => void;
  initialAssetType?: AssetType | null;
  allowedAssetTypes?: readonly AssetType[];
}

const FILTERS: ReadonlyArray<{ value: AssetType | null; label: string }> = [
  { value: null, label: '全部' },
  { value: 'STOCK', label: '股票' },
  { value: 'FUND', label: '基金' },
];

/** 提供持仓与自选共用、可键盘操作的本地资产选择对话框。 */
export function InstrumentDialog({
  open,
  onClose,
  onSelect,
  initialAssetType = null,
  allowedAssetTypes,
}: InstrumentDialogProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState('');
  const [assetType, setAssetType] = useState<AssetType | null>(initialAssetType);
  const deferredQuery = useDeferredValue(query.trim());
  const search = useInstrumentSearch({
    query: deferredQuery,
    assetType,
    enabled: open && deferredQuery.length > 0,
  });
  const filters = FILTERS.filter(
    (filter) => filter.value === null
      ? allowedAssetTypes === undefined || allowedAssetTypes.length > 1
      : allowedAssetTypes === undefined || allowedAssetTypes.includes(filter.value),
  );

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog === null) return;
    if (open && !dialog.open) {
      dialog.showModal();
      inputRef.current?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  function changeAssetType(event: ChangeEvent<HTMLInputElement>) {
    setAssetType(event.target.value === '' ? null : event.target.value as AssetType);
  }

  function select(instrument: Instrument) {
    onSelect(instrument);
    onClose();
  }

  return (
    <dialog
      className="instrument-dialog"
      ref={dialogRef}
      aria-labelledby="instrument-dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      <header className="instrument-dialog__heading">
        <div>
          <p className="eyebrow">资产库</p>
          <h2 id="instrument-dialog-title">选择股票或基金</h2>
        </div>
        <button className="text-button" type="button" onClick={onClose}>关闭</button>
      </header>

      <div className="instrument-search" role="search">
        <label htmlFor="instrument-query">代码或名称</label>
        <input
          id="instrument-query"
          ref={inputRef}
          type="search"
          autoComplete="off"
          maxLength={160}
          value={query}
          aria-controls="instrument-search-results"
          placeholder="搜索 A 股或国内基金"
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      <fieldset className="instrument-filters">
        <legend>资产类型</legend>
        {filters.map((filter) => (
          <label key={filter.label}>
            <input
              type="radio"
              name="asset-type"
              value={filter.value ?? ''}
              checked={assetType === filter.value}
              onChange={changeAssetType}
            />
            <span>{filter.label}</span>
          </label>
        ))}
      </fieldset>

      <div className="instrument-dialog__results">
        <SearchResults
          items={search.data?.items ?? []}
          hasSearched={deferredQuery.length > 0}
          isPending={search.isPending && search.isFetching}
          isError={search.isError}
          onSelect={select}
        />
      </div>
    </dialog>
  );
}
