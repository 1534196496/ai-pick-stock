import type { PositionSummary } from './api';
import { formatCurrency, formatRate, formatSignedCurrency, valueTone } from './format';

interface HoldingsSummaryProps {
  summary: PositionSummary | undefined;
  isPending: boolean;
  isError: boolean;
}

/** 展示列表金额合计、当日收益和持有收益，并明确缺价和陈旧状态。 */
export function HoldingsSummary({ summary, isPending, isError }: HoldingsSummaryProps) {
  const unavailable = isPending || isError || summary === undefined;
  const estimatedFundPositionCount = summary?.estimatedFundPositionCount ?? 0;
  const usesEstimate = !unavailable && estimatedFundPositionCount > 0;
  const marketValue = summary?.marketValue ?? null;
  const holdingProfit = usesEstimate
    ? summary.intradayHoldingProfit
    : summary?.holdingProfit ?? null;
  const returnRate = usesEstimate ? summary.intradayReturnRate : summary?.returnRate ?? null;
  const todayProfit = summary?.todayProfit ?? null;
  return (
    <>
      <dl className="ledger-summary" aria-label="持仓汇总">
        <div>
          <dt>总金额</dt>
          <dd>
            {unavailable ? '—' : formatCurrency(marketValue)}
          </dd>
        </div>
        <div>
          <dt>当日收益</dt>
          <dd className={unavailable ? '' : valueTone(todayProfit)}>
            {unavailable ? '—' : formatSignedCurrency(todayProfit)}
            {!unavailable && todayProfit !== null && estimatedFundPositionCount > 0 && (
              <small>含 {estimatedFundPositionCount} 项预估</small>
            )}
          </dd>
        </div>
        <div>
          <dt>持有收益</dt>
          <dd className={unavailable ? '' : valueTone(holdingProfit)}>
            {unavailable ? '—' : formatSignedCurrency(holdingProfit)}
            {!unavailable && returnRate !== null && (
              <small>持仓收益率 {formatRate(returnRate)}</small>
            )}
          </dd>
        </div>
      </dl>
      {isError && <p className="data-notice data-notice--error" role="alert">汇总加载失败，请稍后重试。</p>}
      {summary?.status === 'INCOMPLETE' && (
        <p className="data-notice" role="status">
          {summary.positionCount - summary.pricedPositionCount} 项持仓缺少权威价格，暂不计算总金额和总收益。
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
