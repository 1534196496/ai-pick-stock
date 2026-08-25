import { useState } from 'react';

import { ApiClientError } from '../../shared/api/client';
import { PriceStatus } from '../instruments/PriceStatus';
import type { InvestmentAccount } from '../accounts/api';
import type { Position } from './api';
import {
  formatCurrency,
  formatDecimal,
  formatRate,
  formatSignedCurrency,
  valueTone,
} from './format';
import { useDeletePosition } from './hooks';

interface PositionListProps {
  items: Position[];
  accounts: InvestmentAccount[];
  isPending: boolean;
  isError: boolean;
  onEdit: (position: Position) => void;
}

/** 在桌面表格和移动卡片中展示相同的持仓权威数据。 */
export function PositionList({
  items,
  accounts,
  isPending,
  isError,
  onEdit,
}: PositionListProps) {
  const deleteMutation = useDeletePosition();
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const accountNames = new Map(accounts.map((account) => [account.id, account.name]));
  if (isPending) return <p className="positions-status" role="status">正在读取持仓…</p>;
  if (isError) return <p className="positions-status positions-status--error" role="alert">持仓加载失败，请稍后重试。</p>;
  if (items.length === 0) {
    return (
      <div className="empty-state" role="status">
        <h2>还没有持仓</h2>
        <p>添加第一只股票或基金后，这里会按账户展示成本和权威估值。</p>
      </div>
    );
  }

  return (
    <div className="position-list">
      {deleteMutation.error !== null && (
        <p className="positions-status positions-status--error" role="alert">
          {deleteMutation.error instanceof ApiClientError
            ? deleteMutation.error.message
            : '删除失败，请稍后重试。'}
        </p>
      )}
      <div className="position-table" role="table" aria-label="持仓列表">
        <div className="position-table__header" role="row">
          <span role="columnheader">资产</span><span role="columnheader">账户</span>
          <span role="columnheader">数量</span><span role="columnheader">最新价格</span>
          <span role="columnheader">市值</span><span role="columnheader">收益</span>
          <span role="columnheader">操作</span>
        </div>
        {items.map((position) => {
          const official = position.valuation;
          const estimate = position.estimatedValuation;
          const awaitingShares = position.inputMode === 'FUND_AMOUNT' && position.quantity === null;
          const marketValue = official?.marketValue
            ?? estimate?.marketValue
            ?? (awaitingShares ? position.inputCurrentValue : null);
          const holdingProfit = official?.holdingProfit
            ?? estimate?.holdingProfit
            ?? (awaitingShares ? position.inputHoldingProfit : null);
          return (
          <article className="position-row" role="row" key={position.id}>
            <div className="position-row__identity" role="cell">
              <strong>{position.instrument.name}</strong>
              <span>{position.instrument.ticker} · {position.instrument.assetType === 'STOCK' ? '股票' : '基金'}</span>
            </div>
            <span role="cell">{accountNames.get(position.accountId) ?? '未知账户'}</span>
            <span className="number-cell" role="cell">
              {position.quantity === null ? '待推算' : formatDecimal(position.quantity)}
              {position.quantityEstimated && (
                <small>按 {position.quantityBasisNavDate ?? '最近官方净值'} 推算</small>
              )}
            </span>
            <span className="position-price-cell" role="cell">
              {official != null && <PriceStatus compact currency={position.instrument.currency} prices={[official.price]} />}
              {estimate != null && <PriceStatus compact currency={position.instrument.currency} prices={[estimate.price]} />}
              {official == null && estimate == null && (
                <span className="missing-price">
                  {awaitingShares ? '等待可用官方净值' : '缺少权威价格'}
                </span>
              )}
            </span>
            <span className="number-cell" role="cell">
              {formatCurrency(marketValue)}
              {official == null && estimate != null && <small className="estimate-note">盘中估算 · 不计入汇总</small>}
              {awaitingShares && <small>原始录入金额</small>}
            </span>
            <span className={`number-cell ${valueTone(holdingProfit)}`} role="cell">
              {formatSignedCurrency(holdingProfit)}
              {official != null && <small>{formatRate(official.returnRate)}</small>}
              {official == null && estimate != null && <small className="estimate-note">盘中估算</small>}
              {awaitingShares && <small>原始录入收益</small>}
            </span>
            <span className="position-actions" role="cell">
              <button type="button" onClick={() => onEdit(position)}>编辑</button>
              {confirmDeleteId === position.id ? (
                <>
                  <button
                    className="position-actions__danger"
                    type="button"
                    disabled={deleteMutation.isPending}
                    onClick={() => void deleteMutation.mutateAsync(position.id)
                      .then(() => setConfirmDeleteId(null))
                      .catch(() => undefined)}
                  >
                    确认删除
                  </button>
                  <button type="button" onClick={() => setConfirmDeleteId(null)}>取消</button>
                </>
              ) : (
                <button type="button" onClick={() => setConfirmDeleteId(position.id)}>删除</button>
              )}
            </span>
          </article>
          );
        })}
      </div>
    </div>
  );
}
