import type { PositionSummary } from './api';
import { formatCurrency, formatRate, formatSignedCurrency, valueTone } from './format';

interface HoldingsSummaryProps {
  summary: PositionSummary | undefined;
  isPending: boolean;
  isError: boolean;
}

/** 展示组合权威总数，并明确缺价和陈旧状态。 */
export function HoldingsSummary({ summary, isPending, isError }: HoldingsSummaryProps) {
  const unavailable = isPending || isError || summary === undefined;
  return (
    <>
      <dl className="ledger-summary" aria-label="持仓汇总">
        <div>
          <dt>总资产</dt>
          <dd>{unavailable ? '—' : formatCurrency(summary.marketValue)}</dd>
        </div>
        <div>
          <dt>持仓成本</dt>
          <dd>{unavailable ? '—' : formatCurrency(summary.totalCost)}</dd>
        </div>
        <div>
          <dt>持有收益</dt>
          <dd className={unavailable ? '' : valueTone(summary.holdingProfit)}>
            {unavailable ? '—' : formatSignedCurrency(summary.holdingProfit)}
            {!unavailable && summary.returnRate !== null && (
              <small>{formatRate(summary.returnRate)}</small>
            )}
          </dd>
        </div>
      </dl>
      {isError && <p className="data-notice data-notice--error" role="alert">汇总加载失败，请稍后重试。</p>}
      {summary?.status === 'INCOMPLETE' && (
        <p className="data-notice" role="status">
          {summary.positionCount - summary.pricedPositionCount} 项持仓缺少权威价格，暂不计算总资产和总收益。
        </p>
      )}
      {summary?.status === 'STALE' && (
        <p className="data-notice" role="status">
          汇总包含 {summary.stalePositionCount} 项陈旧行情，请结合标注时间查看。
        </p>
      )}
    </>
  );
}
