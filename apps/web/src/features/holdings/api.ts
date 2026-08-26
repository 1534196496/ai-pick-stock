import { apiRequest } from '../../shared/api/client';
import type { components } from '../../shared/api/schema';

export type Position = components['schemas']['PositionResponse'];
export type PositionList = components['schemas']['PositionListResponse'];
export type PositionSummary = components['schemas']['PositionSummaryResponse'];
export type CreateStockPositionInput = components['schemas']['CreateStockPositionRequest'];
export type CreateFundAmountPositionInput = components['schemas']['CreateFundAmountPositionRequest'];
export type CreateFundSharesPositionInput = components['schemas']['CreateFundSharesPositionRequest'];
export type CreatePositionInput =
  | CreateStockPositionInput
  | CreateFundAmountPositionInput
  | CreateFundSharesPositionInput;
export type UpdateStockPositionInput = components['schemas']['UpdateStockPositionRequest'];
export type UpdateFundAmountPositionInput = components['schemas']['UpdateFundAmountPositionRequest'];
export type UpdateFundSharesPositionInput = components['schemas']['UpdateFundSharesPositionRequest'];
export type UpdatePositionInput =
  | UpdateStockPositionInput
  | UpdateFundAmountPositionInput
  | UpdateFundSharesPositionInput;

/** 分页读取全部分组或指定分组的持仓与本地行情估值。 */
export function listPositions(groupId: string | null): Promise<PositionList> {
  const parameters = new URLSearchParams({ page: '1', pageSize: '100' });
  if (groupId !== null) parameters.set('groupId', groupId);
  return apiRequest(`/api/v1/positions?${parameters.toString()}`);
}

/** 读取全部分组或指定分组的组合汇总。 */
export function getPositionSummary(groupId: string | null): Promise<PositionSummary> {
  const suffix = groupId === null ? '' : `?groupId=${encodeURIComponent(groupId)}`;
  return apiRequest(`/api/v1/position-summary${suffix}`);
}

/** 读取当前用户指定持仓，供重复新增恢复到编辑流程。 */
export function getPosition(positionId: string): Promise<Position> {
  return apiRequest(`/api/v1/positions/${positionId}`);
}

/** 按录入模式创建股票或基金持仓，财务字段保持十进制字符串。 */
export function createPosition(input: CreatePositionInput): Promise<Position> {
  return apiRequest('/api/v1/positions', {
    method: 'POST',
    body: JSON.stringify(input),
  });
}

/** 按录入模式和乐观锁版本更新持仓原始输入或所属分组。 */
export function updatePosition(
  positionId: string,
  input: UpdatePositionInput,
): Promise<Position> {
  return apiRequest(`/api/v1/positions/${positionId}`, {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
}

/** 删除当前用户指定持仓。 */
export function deletePosition(positionId: string): Promise<void> {
  return apiRequest(`/api/v1/positions/${positionId}`, { method: 'DELETE' });
}
