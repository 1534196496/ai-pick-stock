import type { components } from '../../shared/api/schema';
import './price-status.css';

type Currency = components['schemas']['Currency'];
type LatestPrice = components['schemas']['LatestPriceResponse'];
type PriceType = components['schemas']['PriceType'];

interface PriceStatusProps {
  prices: LatestPrice[];
  currency: Currency;
  compact?: boolean;
}

const PRICE_LABEL: Record<PriceType, string> = {
  STOCK_LAST: '最新价',
  FUND_OFFICIAL_NAV: '官方单位净值',
  FUND_ESTIMATED_NAV: '盘中估算',
};

const SOURCE_LABEL: Record<string, string> = {
  tencent_stock_quote: '腾讯行情',
  sina_stock_quote: '新浪行情',
  eastmoney_fund_official_bulk: '天天基金官方净值',
  eastmoney_fund_official_single: '天天基金官方净值',
  eastmoney_fund_estimate_single: '东方财富估算',
  eastmoney_fund_estimate_bulk: '天天基金盘中估算',
};

/** 在不使用浮点运算的前提下把行情值限制为最多四位小数。 */
function formatDecimal(value: string): string {
  const [rawInteger, rawFraction = ''] = value.split('.', 2);
  const sign = rawInteger.startsWith('-') ? '-' : '';
  const integer = rawInteger.replace('-', '').replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const fraction = rawFraction.slice(0, 4).replace(/0+$/, '');
  return `${sign}${integer}${fraction ? `.${fraction}` : ''}`;
}

/** 把带时区业务时点转换为上海时区的紧凑展示。 */
function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value));
}

/** 选择搜索列表中的权威主价格，基金估算只在缺官方净值时退居展示。 */
function primaryPrice(prices: LatestPrice[]): LatestPrice | undefined {
  return prices.find((price) => price.priceType === 'STOCK_LAST')
    ?? prices.find((price) => price.priceType === 'FUND_OFFICIAL_NAV')
    ?? prices.find((price) => price.priceType === 'FUND_ESTIMATED_NAV');
}

/** 统一展示股票价格、基金官方净值、估算净值及其时间与新鲜度。 */
export function PriceStatus({ prices, currency, compact = false }: PriceStatusProps) {
  const visiblePrices = compact ? [primaryPrice(prices)].filter(Boolean) as LatestPrice[] : prices;
  if (visiblePrices.length === 0) {
    return <span className="price-status price-status--missing">暂无行情</span>;
  }

  return (
    <span className={compact ? 'price-stack price-stack--compact' : 'price-stack'}>
      {visiblePrices.map((price) => {
        const stale = price.freshness === 'STALE';
        const businessTime = price.asOfDate ?? price.asOfAt;
        const timeLabel = price.asOfDate
          ? `净值日期 ${price.asOfDate}`
          : price.asOfAt
            ? `行情时间 ${formatDateTime(price.asOfAt)}`
            : '业务时间未知';
        return (
          <span className="price-status" key={price.priceType}>
            <span className="price-status__main">
              <span className="price-status__label">{PRICE_LABEL[price.priceType]}</span>
              <strong>{currency === 'CNY' && price.priceType === 'STOCK_LAST' ? '¥' : ''}{formatDecimal(price.value)}</strong>
            </span>
            <span className={stale ? 'price-status__freshness price-status__freshness--stale' : 'price-status__freshness'}>
              <span aria-hidden="true">{stale ? '△' : '●'}</span>
              {stale ? '数据陈旧' : '数据正常'}
            </span>
            {!compact && (
              <span className="price-status__detail">
                <time dateTime={businessTime ?? undefined}>{timeLabel}</time>
                <span>{SOURCE_LABEL[price.source] ?? price.source}</span>
              </span>
            )}
          </span>
        );
      })}
    </span>
  );
}
