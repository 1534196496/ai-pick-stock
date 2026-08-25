import { PriceStatus } from '../instruments/PriceStatus';
import type { WatchlistItem } from './api';

interface WatchlistItemsProps {
  items: WatchlistItem[];
  isPending: boolean;
  isError: boolean;
  canAddToHoldings: boolean;
  onEdit: (item: WatchlistItem) => void;
  onAddToHoldings: (item: WatchlistItem) => void;
}

/** 展示股票与基金观察项、全部价格口径和用户备注。 */
export function WatchlistItems({
  items,
  isPending,
  isError,
  canAddToHoldings,
  onEdit,
  onAddToHoldings,
}: WatchlistItemsProps) {
  if (isPending) return <p className="watchlist-items__status" role="status">正在读取自选标的…</p>;
  if (isError) return <p className="form-error" role="alert">自选标的加载失败，请稍后重试。</p>;
  if (items.length === 0) {
    return (
      <div className="empty-state empty-state--compact" role="status">
        <h3>这个分组还没有标的</h3>
        <p>添加正在观察的股票或基金，行情会由后台定时更新。</p>
      </div>
    );
  }

  return (
    <div className="watchlist-item-list">
      {items.map((item) => (
        <article className="watchlist-item" key={item.id}>
          <div className="watchlist-item__identity">
            <strong>{item.instrument.name}</strong>
            <span>{item.instrument.ticker} · {item.instrument.assetType === 'STOCK' ? '股票' : '基金'}</span>
          </div>
          <div className="watchlist-item__prices">
            <PriceStatus currency={item.instrument.currency} prices={item.instrument.latestPrices} />
          </div>
          <div className="watchlist-item__note">
            <span>备注</span>
            <p>{item.note ?? '暂无备注'}</p>
          </div>
          <div className="watchlist-item__actions">
            <button disabled={!canAddToHoldings} type="button" onClick={() => onAddToHoldings(item)}>加入持有</button>
            <button type="button" onClick={() => onEdit(item)}>管理</button>
          </div>
        </article>
      ))}
    </div>
  );
}
