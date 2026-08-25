import { useState, type FormEvent } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { ApiClientError } from '../../shared/api/client';
import { useModalDialog } from '../../shared/ui/useModalDialog';
import type { InvestmentAccount } from '../accounts/api';
import type { Instrument } from '../instruments/api';
import { getPosition, type Position } from './api';
import { divideDecimal, multiplyDecimal, subtractDecimal } from './decimal';
import { formatCurrency } from './format';
import { useCreatePosition, useUpdatePosition } from './hooks';

interface FundPositionDialogProps {
  instrument: Pick<Instrument, 'id' | 'name' | 'ticker' | 'exchange'>;
  accounts: InvestmentAccount[];
  defaultAccountId: string | null;
  position?: Position;
  onExistingPosition?: (position: Position) => void;
  onClose: () => void;
}

type FundInputMode = 'FUND_AMOUNT' | 'FUND_SHARES';
type CostMode = 'TOTAL_COST' | 'AVERAGE_COST';

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

/** 支持基金按金额快速录入和按份额精确录入，并保留原始输入口径。 */
export function FundPositionDialog({
  instrument,
  accounts,
  defaultAccountId,
  position,
  onExistingPosition,
  onClose,
}: FundPositionDialogProps) {
  const { dialogRef, closeDialog } = useModalDialog(onClose);
  const queryClient = useQueryClient();
  const createMutation = useCreatePosition();
  const updateMutation = useUpdatePosition();
  const mutation = position === undefined ? createMutation : updateMutation;
  const initialMode: FundInputMode = position?.inputMode === 'FUND_SHARES'
    ? 'FUND_SHARES'
    : 'FUND_AMOUNT';
  const initialCostMode: CostMode = position?.costInputMode ?? 'TOTAL_COST';
  const [mode, setMode] = useState<FundInputMode>(initialMode);
  const [accountId, setAccountId] = useState(
    position?.accountId ?? defaultAccountId ?? accounts[0]?.id ?? '',
  );
  const [inputDate, setInputDate] = useState(position?.inputDate ?? shanghaiToday);
  const [currentValue, setCurrentValue] = useState(position?.inputCurrentValue ?? '');
  const [holdingProfit, setHoldingProfit] = useState(position?.inputHoldingProfit ?? '');
  const [quantity, setQuantity] = useState(position?.inputQuantity ?? '');
  const [costMode, setCostMode] = useState<CostMode>(initialCostMode);
  const [cost, setCost] = useState(
    initialCostMode === 'AVERAGE_COST'
      ? position?.inputAverageCost ?? ''
      : position?.inputTotalCost ?? '',
  );
  const totalCostPreview = mode === 'FUND_AMOUNT'
    ? subtractDecimal(currentValue, holdingProfit)
    : costMode === 'TOTAL_COST' ? cost : multiplyDecimal(quantity, cost);
  const averageCostPreview = mode === 'FUND_SHARES'
    ? costMode === 'AVERAGE_COST' ? cost : divideDecimal(cost, quantity)
    : null;

  /** 根据当前基金录入模式构造严格区分的 API 请求。 */
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      if (position === undefined) {
        if (mode === 'FUND_AMOUNT') {
          await createMutation.mutateAsync({
            inputMode: 'FUND_AMOUNT',
            accountId,
            instrumentId: instrument.id,
            inputDate,
            currentValue,
            holdingProfit,
          });
        } else {
          await createMutation.mutateAsync({
            inputMode: 'FUND_SHARES',
            accountId,
            instrumentId: instrument.id,
            inputDate,
            quantity,
            costInputMode: costMode,
            totalCost: costMode === 'TOTAL_COST' ? cost : null,
            averageCost: costMode === 'AVERAGE_COST' ? cost : null,
          });
        }
      } else if (mode === 'FUND_AMOUNT') {
        await updateMutation.mutateAsync({
          positionId: position.id,
          input: {
            inputMode: 'FUND_AMOUNT',
            version: position.version,
            accountId,
            inputDate,
            currentValue,
            holdingProfit,
          },
        });
      } else {
        await updateMutation.mutateAsync({
          positionId: position.id,
          input: {
            inputMode: 'FUND_SHARES',
            version: position.version,
            accountId,
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
      aria-labelledby="fund-position-title"
      onCancel={(event) => { event.preventDefault(); closeDialog(); }}
    >
      <header className="dialog-heading">
        <div>
          <p className="eyebrow">{position === undefined ? '添加基金持仓' : '编辑基金持仓'}</p>
          <h2 id="fund-position-title">{instrument.name}</h2>
          <p>{instrument.ticker} · {instrument.exchange}</p>
        </div>
        <button className="text-button" type="button" onClick={closeDialog}>关闭</button>
      </header>
      <form className="position-form" onSubmit={(event) => void submit(event)}>
        {position === undefined ? (
          <fieldset className="cost-mode position-input-mode">
            <legend>录入方式</legend>
            <label>
              <input
                name="fund-input-mode"
                type="radio"
                checked={mode === 'FUND_AMOUNT'}
                onChange={() => setMode('FUND_AMOUNT')}
              />
              按金额（推荐）
            </label>
            <label>
              <input
                name="fund-input-mode"
                type="radio"
                checked={mode === 'FUND_SHARES'}
                onChange={() => setMode('FUND_SHARES')}
              />
              按份额
            </label>
          </fieldset>
        ) : (
          <p className="fund-input-note">
            当前按{mode === 'FUND_AMOUNT' ? '金额' : '份额'}维护，编辑会保留原口径。
          </p>
        )}
        <label>
          <span>投资账户</span>
          <select required value={accountId} onChange={(event) => setAccountId(event.target.value)}>
            {accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}
          </select>
        </label>
        <label>
          <span>数据日期</span>
          <input required type="date" value={inputDate} onChange={(event) => setInputDate(event.target.value)} />
        </label>

        {mode === 'FUND_AMOUNT' ? (
          <>
            <label>
              <span>当前金额</span>
              <input required inputMode="decimal" placeholder="例如 12500" value={currentValue} onChange={(event) => setCurrentValue(event.target.value)} />
            </label>
            <label>
              <span>持有收益</span>
              <input required inputMode="decimal" placeholder="亏损填负数，如 -320" value={holdingProfit} onChange={(event) => setHoldingProfit(event.target.value)} />
            </label>
            <p className="fund-input-note">
              系统会用该日期的官方净值推算份额；暂无当天净值时先保存金额，后续再补齐份额。
            </p>
            <dl className="position-preview" aria-label="基金成本预览">
              <div><dt>推算总成本</dt><dd>{totalCostPreview ? formatCurrency(totalCostPreview) : '—'}</dd></div>
              <div><dt>计算方式</dt><dd>当前金额 − 持有收益</dd></div>
            </dl>
          </>
        ) : (
          <>
            <label>
              <span>持有份额</span>
              <input required inputMode="decimal" placeholder="例如 8234.56" value={quantity} onChange={(event) => setQuantity(event.target.value)} />
            </label>
            <fieldset className="cost-mode">
              <legend>成本填写方式</legend>
              <label><input name="fund-cost-mode" type="radio" checked={costMode === 'TOTAL_COST'} onChange={() => { setCostMode('TOTAL_COST'); setCost(''); }} />总成本</label>
              <label><input name="fund-cost-mode" type="radio" checked={costMode === 'AVERAGE_COST'} onChange={() => { setCostMode('AVERAGE_COST'); setCost(''); }} />平均成本</label>
            </fieldset>
            <label>
              <span>{costMode === 'TOTAL_COST' ? '总成本' : '平均成本'}</span>
              <input required inputMode="decimal" placeholder="请输入十进制金额" value={cost} onChange={(event) => setCost(event.target.value)} />
            </label>
            <dl className="position-preview" aria-label="基金成本预览">
              <div><dt>预计总成本</dt><dd>{totalCostPreview ? formatCurrency(totalCostPreview) : '—'}</dd></div>
              <div><dt>预计平均成本</dt><dd>{averageCostPreview ? formatCurrency(averageCostPreview) : '—'}</dd></div>
            </dl>
          </>
        )}

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
        <button className="primary-button" disabled={mutation.isPending || accountId === ''} type="submit">
          {mutation.isPending ? '正在保存…' : position === undefined ? '保存持仓' : '保存修改'}
        </button>
      </form>
    </dialog>
  );
}
