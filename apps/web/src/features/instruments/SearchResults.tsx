import type { Instrument } from './api';
import { PriceStatus } from './PriceStatus';

interface SearchResultsProps {
  items: Instrument[];
  hasSearched: boolean;
  isPending: boolean;
  isError: boolean;
  onSelect: (instrument: Instrument) => void;
}

const ASSET_TYPE_LABEL = { STOCK: '股票', FUND: '基金' } as const;
const EXCHANGE_LABEL = {
  SSE: '沪市',
  SZSE: '深市',
  BSE: '北交所',
  FUND_CN: '公募基金',
} as const;

/** 展示资产搜索的引导、加载、失败、空结果和可选择列表。 */
export function SearchResults({
  items,
  hasSearched,
  isPending,
  isError,
  onSelect,
}: SearchResultsProps) {
  if (!hasSearched) {
    return <p className="instrument-search__hint">输入代码或名称，例如“600519”或“沪深300”。</p>;
  }
  if (isPending) {
    return <p className="instrument-search__hint" role="status">正在查找本地资产…</p>;
  }
  if (isError) {
    return <p className="instrument-search__error" role="alert">搜索失败，请稍后重试。</p>;
  }
  if (items.length === 0) {
    return <p className="instrument-search__hint" role="status">没有找到匹配的股票或基金。</p>;
  }

  return (
    <ul className="instrument-results" id="instrument-search-results">
      {items.map((instrument) => (
        <li key={instrument.id}>
          <button type="button" onClick={() => onSelect(instrument)}>
            <span className="instrument-results__identity">
              <strong>{instrument.name}</strong>
              <span>{instrument.ticker}</span>
            </span>
            <span className="instrument-results__meta">
              <span className="instrument-results__tags">
                <span>{ASSET_TYPE_LABEL[instrument.assetType]}</span>
                <span>{EXCHANGE_LABEL[instrument.exchange]}</span>
              </span>
              <PriceStatus
                compact
                currency={instrument.currency}
                prices={instrument.latestPrices}
              />
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
