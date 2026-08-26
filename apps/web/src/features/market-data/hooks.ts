import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  getMarketDataSchedule,
  getMarketDataStatus,
  manuallySyncMarketData,
  updateMarketDataSchedule,
} from './api';

export const marketDataScheduleQueryKey = ['market-data-schedule'] as const;
export const marketDataStatusQueryKey = ['market-data-status'] as const;

/** 读取后台行情任务调度配置。 */
export function useMarketDataSchedule() {
  return useQuery({ queryKey: marketDataScheduleQueryKey, queryFn: getMarketDataSchedule });
}

/** 读取后台行情任务最近执行状态。 */
export function useMarketDataStatus() {
  return useQuery({ queryKey: marketDataStatusQueryKey, queryFn: getMarketDataStatus });
}

/** 保存调度配置并立即替换当前页面缓存。 */
export function useUpdateMarketDataSchedule() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: updateMarketDataSchedule,
    onSuccess: (schedule) => client.setQueryData(marketDataScheduleQueryKey, schedule),
  });
}

/** 手动同步完成后刷新所有可能包含行情计算结果的页面缓存。 */
export function useManualMarketDataSync() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: manuallySyncMarketData,
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: marketDataStatusQueryKey }),
        client.invalidateQueries({ queryKey: ['positions'] }),
        client.invalidateQueries({ queryKey: ['position-summary'] }),
        client.invalidateQueries({ queryKey: ['watchlist-items'] }),
        client.invalidateQueries({ queryKey: ['instruments'] }),
      ]);
    },
  });
}
