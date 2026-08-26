import { useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { ApiClientError } from '../../shared/api/client';
import { useModalDialog } from '../../shared/ui/useModalDialog';
import type { WatchlistGroup } from '../watchlists/api';
import type { Instrument } from '../instruments/api';
import { getPosition, type Position } from './api';
import { divideDecimal, multiplyDecimal } from './decimal';
import { formatCurrency } from './format';
import { useCreatePosition, useUpdatePosition } from './hooks';

interface StockPositionDialogProps {
  instrument: Pick<Instrument, 'id' | 'name' | 'ticker' | 'exchange'>;
  groups: WatchlistGroup[];
  defaultGroupId: string | null;
  position?: Position;
  onExistingPosition?: (position: Position) => void;
  onClose: () => void;
}

/** 返回上海时区的当前日期，避免 UTC 跨日造成录入日期偏差。 */
function shanghaiToday(): string {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${value.year}-${value.month}-${value.day}`;
}

/** 录入股票数量和一种成本，并展示不依赖浮点数的计算预览。 */
export function StockPositionDialog({
  instrument,
  groups,
  defaultGroupId,
  position,
  onExistingPosition,
  onClose,
}: StockPositionDialogProps) {
  const { dialogRef, closeDialog } = useModalDialog(onClose);
  const queryClient = useQueryClient();
  const createMutation = useCreatePosition();
  const updateMutation = useUpdatePosition();
  const mutation = position === undefined ? createMutation : updateMutation;
  const initialCostMode = 'TOTAL_COST' as const;
  const [groupId, setGroupId] = useState(
    position?.groupId ?? defaultGroupId ?? groups[0]?.id ?? '',
  );
  const [inputDate, setInputDate] = useState(position?.lastTradeDate ?? shanghaiToday);
  const [quantity, setQuantity] = useState(position?.quantity ?? '');
  const [costMode, setCostMode] = useState<'TOTAL_COST' | 'AVERAGE_COST'>(initialCostMode);
  const [cost, setCost] = useState(
    position?.totalCost ?? '',
  );
  const totalPreview = costMode === 'TOTAL_COST' ? cost : multiplyDecimal(quantity, cost);
  const averagePreview = costMode === 'AVERAGE_COST' ? cost : divideDecimal(cost, quantity);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      if (position === undefined) {
        await createMutation.mutateAsync({
          inputMode: 'STOCK_SHARES',
          groupId,
          instrumentId: instrument.id,
          inputDate,
          quantity,
          costInputMode: costMode,
          totalCost: costMode === 'TOTAL_COST' ? cost : null,
          averageCost: costMode === 'AVERAGE_COST' ? cost : null,
        });
      } else {
        await updateMutation.mutateAsync({
          positionId: position.id,
          input: {
            inputMode: 'STOCK_SHARES',
            version: position.version,
            groupId,
            inputDate,
            quantity,
            costInputMode: costMode,
            ...(costMode === 'TOTAL_COST' ? { totalCost: cost } : { averageCost: cost }),
          },
        });
      }
      closeDialog();
    } catch (error) {
      const existingId = error instanceof ApiClientError
        && error.code === 'POSITION_ALREADY_EXISTS'
        && typeof error.details?.positionId === 'string'
        ? error.details.positionId
        : null;
      if (position === undefined && existingId !== null && onExistingPosition !== undefined) {
        try {
          onExistingPosition(await getPosition(existingId));
        } catch {
          // 读取失败时保留原表单和重复提示。
        }
      }
    }
  }

  const error = mutation.error;
  return (
    <dialog
      className="stock-position-dialog"
      ref={dialogRef}
      aria-labelledby="stock-position-title"
      onCancel={(event) => { event.preventDefault(); closeDialog(); }}
    >
      <header className="dialog-heading">
        <div>
          <p className="eyebrow">{position === undefined ? '添加股票持仓' : '编辑股票持仓'}</p>
          <h2 id="stock-position-title">{instrument.name}</h2>
          <p>{instrument.ticker} · {instrument.exchange}</p>
        </div>
        <button className="text-button" type="button" onClick={closeDialog}>关闭</button>
      </header>
      <form className="position-form" onSubmit={(event) => void submit(event)}>
        <label>
          <span>持仓分组</span>
          <select required value={groupId} onChange={(event) => setGroupId(event.target.value)}>
            {groups.map((group) => <option key={group.id} value={group.id}>{group.name}</option>)}
          </select>
        </label>
        <label>
          <span>数据日期</span>
          <input required type="date" value={inputDate} onChange={(event) => setInputDate(event.target.value)} />
        </label>
        <label>
          <span>持有数量</span>
          <input required inputMode="decimal" placeholder="例如 100" value={quantity} onChange={(event) => setQuantity(event.target.value)} />
        </label>
        <fieldset className="cost-mode">
          <legend>成本填写方式</legend>
          <label><input name="cost-mode" type="radio" checked={costMode === 'TOTAL_COST'} onChange={() => { setCostMode('TOTAL_COST'); setCost(''); }} />总成本</label>
          <label><input name="cost-mode" type="radio" checked={costMode === 'AVERAGE_COST'} onChange={() => { setCostMode('AVERAGE_COST'); setCost(''); }} />平均成本</label>
        </fieldset>
        <label>
          <span>{costMode === 'TOTAL_COST' ? '总成本' : '平均成本'}</span>
          <input required inputMode="decimal" placeholder="请输入十进制金额" value={cost} onChange={(event) => setCost(event.target.value)} />
        </label>
        <dl className="position-preview" aria-label="持仓计算预览">
          <div><dt>预计总成本</dt><dd>{totalPreview ? formatCurrency(totalPreview) : '—'}</dd></div>
          <div><dt>预计平均成本</dt><dd>{averagePreview ? formatCurrency(averagePreview) : '—'}</dd></div>
        </dl>
        {error !== null && (
          <p className="form-error" role="alert">
            {error instanceof ApiClientError ? error.message : '保存失败，请稍后重试'}
          </p>
        )}
        {error instanceof ApiClientError && error.code === 'POSITION_VERSION_CONFLICT' && (
          <button
            className="text-button position-form__reload"
            type="button"
            onClick={() => void queryClient.invalidateQueries({ queryKey: ['positions'] }).then(closeDialog)}
          >
            重新加载最新持仓
          </button>
        )}
        <button className="primary-button" disabled={mutation.isPending || groupId === ''} type="submit">
          {mutation.isPending ? '正在保存…' : position === undefined ? '保存持仓' : '保存修改'}
        </button>
      </form>
    </dialog>
  );
}
