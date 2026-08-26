import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createPosition,
  deletePosition,
  getPositionSummary,
  listPositions,
  updatePosition,
} from './api';

/** 刷新所有分组范围下的持仓、汇总和分组计数缓存。 */
async function invalidateHoldings(client: ReturnType<typeof useQueryClient>) {
  await Promise.all([
    client.invalidateQueries({ queryKey: ['positions'] }),
    client.invalidateQueries({ queryKey: ['position-summary'] }),
    client.invalidateQueries({ queryKey: ['watchlist-groups'] }),
  ]);
}

/** 读取当前分组筛选下的持仓列表并周期刷新本地数据库结果。 */
export function usePositions(groupId: string | null) {
  return useQuery({
    queryKey: ['positions', groupId],
    queryFn: () => listPositions(groupId),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });
}

/** 读取与持仓列表相同分组范围的组合汇总。 */
export function usePositionSummary(groupId: string | null) {
  return useQuery({
    queryKey: ['position-summary', groupId],
    queryFn: () => getPositionSummary(groupId),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });
}

/** 创建股票或基金持仓后刷新所有分组范围的列表和汇总。 */
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
