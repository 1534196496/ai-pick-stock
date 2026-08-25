import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createPosition,
  deletePosition,
  getPositionSummary,
  listPositions,
  updatePosition,
} from './api';

/** 刷新所有账户范围下的持仓列表和汇总缓存。 */
async function invalidateHoldings(client: ReturnType<typeof useQueryClient>) {
  await Promise.all([
    client.invalidateQueries({ queryKey: ['positions'] }),
    client.invalidateQueries({ queryKey: ['position-summary'] }),
  ]);
}

/** 读取当前账户筛选下的持仓列表并周期刷新本地数据库结果。 */
export function usePositions(accountId: string | null) {
  return useQuery({
    queryKey: ['positions', accountId],
    queryFn: () => listPositions(accountId),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });
}

/** 读取与持仓列表相同账户范围的组合汇总。 */
export function usePositionSummary(accountId: string | null) {
  return useQuery({
    queryKey: ['position-summary', accountId],
    queryFn: () => getPositionSummary(accountId),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });
}

/** 创建股票或基金持仓后刷新所有账户范围的列表和汇总。 */
export function useCreatePosition() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: createPosition,
    onSuccess: () => invalidateHoldings(client),
  });
}

/** 更新或移动股票或基金持仓后刷新列表和汇总。 */
export function useUpdatePosition() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ positionId, input }: {
      positionId: string;
      input: Parameters<typeof updatePosition>[1];
    }) => updatePosition(positionId, input),
    onSuccess: () => invalidateHoldings(client),
  });
}

/** 删除持仓后刷新列表和汇总。 */
export function useDeletePosition() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: deletePosition,
    onSuccess: () => invalidateHoldings(client),
  });
}
