import { useMemo, useState } from 'react';

import { ApiClientError } from '../../shared/api/client';
import type { WatchlistGroup } from '../watchlists/api';
import type { Position } from './api';
import {
  formatAmount,
  formatDecimal,
  formatRate,
  formatSignedAmount,
  valueTone,
} from './format';
import { useDeletePosition } from './hooks';
import { sortPositions, type PositionSort } from './positionSorting';

interface PositionListProps {
  title: string;
  assetType: 'STOCK' | 'FUND';
  items: Position[];
  sort: PositionSort;
  groups: WatchlistGroup[];
  showGroupName: boolean;
  isPending: boolean;
  isError: boolean;
  onEdit: (position: Position) => void;
}

/** 按资产类型展示独立持仓表，避免股票和基金口径混在同一列中。 */
export function PositionList({
  title,
  assetType,
  items,
  sort,
  groups,
  showGroupName,
  isPending,
  isError,
  onEdit,
}: PositionListProps) {
  const deleteMutation = useDeletePosition();
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const groupNames = new Map(groups.map((group) => [group.id, group.name]));
  const isFund = assetType === 'FUND';
  const sortedItems = useMemo(() => sortPositions(items, sort), [items, sort]);

  return (
    <section className="position-section" aria-label={title}>
      {isPending && <p className="positions-status" role="status">正在读取持仓…</p>}
      {isError && (
        <p className="positions-status positions-status--error" role="alert">
          持仓加载失败，请稍后重试。
        </p>
      )}
      {!isPending && !isError && items.length === 0 && (
        <p className="positions-status">暂无{isFund ? '基金' : '股票'}持仓</p>
      )}
      {deleteMutation.error !== null && (
        <p className="positions-status positions-status--error" role="alert">
          {deleteMutation.error instanceof ApiClientError
            ? deleteMutation.error.message
            : '删除失败，请稍后重试。'}
        </p>
      )}
      {!isPending && !isError && items.length > 0 && (
        <div className="position-table" role="table" aria-label={title}>
          <div className="position-table__header" role="row">
            <span role="columnheader">{isFund ? '基金' : '股票'}</span>
            <span role="columnheader">金额</span>
            <span role="columnheader">{isFund ? '最新净值' : '现价'}</span>
            <span role="columnheader">今日收益</span>
            <span role="columnheader">持仓收益</span>
            <span role="columnheader">操作</span>
          </div>
          <div className="position-table__mobile-header" aria-hidden="true">
            <span>{isFund ? '基金 / 金额' : '股票 / 金额'}</span>
            <span>今日收益</span>
            <span>持仓收益</span>
          </div>
          {sortedItems.map((position) => (
            <PositionRow
              key={position.id}
              position={position}
              groupName={groupNames.get(position.groupId) ?? '未知分组'}
              showGroupName={showGroupName}
              confirmDeleteId={confirmDeleteId}
              deleting={deleteMutation.isPending}
              onEdit={onEdit}
              onRequestDelete={setConfirmDeleteId}
              onDelete={() => void deleteMutation.mutateAsync(position.id)
                .then(() => setConfirmDeleteId(null))
                .catch(() => undefined)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

interface PositionRowProps {
  position: Position;
  groupName: string;
  showGroupName: boolean;
  confirmDeleteId: string | null;
  deleting: boolean;
  onEdit: (position: Position) => void;
  onRequestDelete: (positionId: string | null) => void;
  onDelete: () => void;
}

/** 展示一条持仓及其动态行情计算结果。 */
function PositionRow({
  position,
  groupName,
  showGroupName,
  confirmDeleteId,
  deleting,
  onEdit,
  onRequestDelete,
  onDelete,
}: PositionRowProps) {
  const official = position.valuation;
  const estimate = position.estimatedValuation;
  const todayValuation = official?.todayProfit != null
    ? official
    : estimate?.todayProfit != null
      ? estimate
      : null;
  const activeValuation = todayValuation ?? estimate ?? official;
  const officialMarketValue = official?.marketValue ?? null;
  const holdingQuantity = position.quantity === null
    ? '份额待补'
    : `${isFundPosition(position) ? '份额' : '数量'} ${formatDecimal(position.quantity)}`;
  const holdingProfit = activeValuation?.holdingProfit ?? null;
  const holdingReturnRate = activeValuation?.returnRate ?? null;
  const todayProfit = todayValuation?.todayProfit ?? null;
  const todayChangeRate = todayValuation?.price.changeRate ?? null;

  return (
    <article className="position-row" role="row">
      <div className="position-row__identity" role="cell">
        <button
          className="position-row__identity-button"
          type="button"
          aria-label={`编辑${position.instrument.name}`}
          onClick={() => onEdit(position)}
        >
          <strong>{position.instrument.name}</strong>
          <span>
            {position.instrument.ticker}
            {showGroupName && ` · ${groupName}`}
          </span>
          <span className="position-row__mobile-value">
            {formatAmount(officialMarketValue)}
            <small>{holdingQuantity}</small>
          </span>
        </button>
      </div>
      <span className="number-cell position-holding-value-cell" role="cell">
        <strong>{formatAmount(officialMarketValue)}</strong>
        <small>{holdingQuantity}</small>
      </span>
      <span className="position-price-cell" role="cell">
        {official == null ? (
          <span className="missing-price">—<small>等待官方数据</small></span>
        ) : (
          <>
            <strong>
              {position.instrument.assetType === 'STOCK' && position.instrument.currency === 'CNY'
                ? '¥'
                : ''}
              {formatDecimal(
                official.price.value,
                4,
                position.instrument.assetType === 'FUND' ? 4 : 0,
              )}
            </strong>
            <small className={official.price.freshness === 'STALE' ? 'data-meta data-meta--warning' : 'data-meta'}>
              {formatPriceTime(
                official.price.asOfAt,
                official.price.asOfDate,
                position.instrument.assetType,
              )}
              {official.price.freshness === 'STALE' && ' · 数据较旧'}
            </small>
          </>
        )}
      </span>
      <span
        className={`number-cell today-rate-cell ${valueTone(todayProfit)}`}
        role="cell"
      >
        <strong>
          {todayValuation?.price.priceType === 'FUND_ESTIMATED_NAV' && (
            <span className="today-profit-estimate-label">预估</span>
          )}
          {formatSignedAmount(todayProfit)}
        </strong>
        {todayChangeRate !== null && (
          <small>
            <span className="holding-rate-label">收益率 </span>
            {formatRate(todayChangeRate)}
          </small>
        )}
      </span>
      <span
        className={`number-cell position-profit-cell ${valueTone(holdingProfit)}`}
        role="cell"
      >
        <strong>{formatSignedAmount(holdingProfit)}</strong>
        {holdingReturnRate !== null && (
          <small><span className="holding-rate-label">收益率 </span>{formatRate(holdingReturnRate)}</small>
        )}
      </span>
      <span className="position-actions" role="cell">
        <button className="position-actions__edit" type="button" onClick={() => onEdit(position)}>
          编辑
        </button>
        {confirmDeleteId === position.id ? (
          <>
            <button
              className="position-actions__danger"
              type="button"
              disabled={deleting}
              onClick={onDelete}
            >
              确认删除
            </button>
            <button type="button" onClick={() => onRequestDelete(null)}>取消</button>
          </>
        ) : (
          <button type="button" onClick={() => onRequestDelete(position.id)}>删除</button>
        )}
      </span>
    </article>
  );
}

/** 判断持仓是否为基金，以统一金额和份额的辅助文案。 */
function isFundPosition(position: Position): boolean {
  return position.instrument.assetType === 'FUND';
}

/** 把行情业务时间压缩为持仓表格可快速辨认的上海时间。 */
function formatBusinessTime(asOfAt: string | null, asOfDate: string | null): string {
  if (asOfDate !== null) return formatShortDate(asOfDate);
  if (asOfAt === null) return '时间未知';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(asOfAt));
}

/** 为最新价格生成唯一一行来源时间，正常状态不额外占据视觉空间。 */
function formatPriceTime(
  asOfAt: string | null,
  asOfDate: string | null,
  assetType: 'STOCK' | 'FUND',
): string {
  if (assetType === 'FUND') {
    return asOfDate === null ? '净值日期未知' : `${formatShortDate(asOfDate)} 净值`;
  }
  return asOfAt === null ? '行情时间未知' : `${formatBusinessTime(asOfAt, null)} 更新`;
}

/** 将 ISO 日期压缩为表格所需的月日。 */
function formatShortDate(value: string): string {
  const [, month, day] = value.split('-', 3);
  return month === undefined || day === undefined ? value : `${month}-${day}`;
}
