import { apiRequest } from '../../shared/api/client';
import type { components } from '../../shared/api/schema';

export type MarketDataSchedule = components['schemas']['MarketDataScheduleResponse'];
export type UpdateMarketDataScheduleInput = components['schemas']['UpdateMarketDataScheduleRequest'];
export type MarketDataStatus = components['schemas']['MarketDataStatusResponse'];
export type ManualMarketDataSyncResult = components['schemas']['ManualMarketDataSyncResponse'];
export type SyncJobType = components['schemas']['SyncJobType'];

/** 读取后台 Worker 当前生效的调度配置。 */
export function getMarketDataSchedule(): Promise<MarketDataSchedule> {
  return apiRequest('/api/v1/market-data/schedule');
}

/** 保存后台 Job 频率和每日运行窗口。 */
export function updateMarketDataSchedule(
  input: UpdateMarketDataScheduleInput,
): Promise<MarketDataSchedule> {
  return apiRequest('/api/v1/market-data/schedule', {
    method: 'PUT',
    body: JSON.stringify(input),
  });
}

/** 读取各类后台 Job 最近一次执行结果。 */
export function getMarketDataStatus(): Promise<MarketDataStatus> {
  return apiRequest('/api/v1/market-data/status');
}

/** 立即执行一个或多个与自动任务相同的行情同步 Job。 */
export function manuallySyncMarketData(
  jobTypes: SyncJobType[],
): Promise<ManualMarketDataSyncResult> {
  return apiRequest('/api/v1/market-data/sync', {
    method: 'POST',
    body: JSON.stringify({ jobTypes }),
  });
}
