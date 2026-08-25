import { apiRequest } from '../../shared/api/client';
import type { components } from '../../shared/api/schema';

export type WatchlistGroup = components['schemas']['WatchlistGroupResponse'];
export type WatchlistGroupList = components['schemas']['WatchlistGroupListResponse'];
export type WatchlistItem = components['schemas']['WatchlistItemResponse'];
export type WatchlistItemList = components['schemas']['WatchlistItemListResponse'];

/** 读取当前用户全部自选分组。 */
export function listWatchlistGroups(): Promise<WatchlistGroupList> {
  return apiRequest('/api/v1/watchlist-groups');
}

/** 创建名称唯一的普通自选分组。 */
export function createWatchlistGroup(name: string): Promise<WatchlistGroup> {
  return apiRequest('/api/v1/watchlist-groups', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });
}

/** 按乐观锁版本重命名或调整自选分组排序。 */
export function updateWatchlistGroup(
  group: WatchlistGroup,
  changes: { name?: string; sortOrder?: number },
): Promise<WatchlistGroup> {
  return apiRequest(`/api/v1/watchlist-groups/${group.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ version: group.version, ...changes }),
  });
}

/** 删除当前用户的普通空分组。 */
export function deleteWatchlistGroup(groupId: string): Promise<void> {
  return apiRequest(`/api/v1/watchlist-groups/${groupId}`, { method: 'DELETE' });
}

/** 读取指定分组第一页观察标的及本地行情。 */
export function listWatchlistItems(groupId: string): Promise<WatchlistItemList> {
  return apiRequest(`/api/v1/watchlist-groups/${groupId}/items?page=1&pageSize=100`);
}

/** 向指定分组添加股票或基金。 */
export function createWatchlistItem(input: {
  groupId: string;
  instrumentId: string;
  note?: string | null;
}): Promise<WatchlistItem> {
  return apiRequest(`/api/v1/watchlist-groups/${input.groupId}/items`, {
    method: 'POST',
    body: JSON.stringify({ instrumentId: input.instrumentId, note: input.note }),
  });
}

/** 按乐观锁版本移动观察标的、修改备注或调整排序。 */
export function updateWatchlistItem(
  item: WatchlistItem,
  changes: { groupId?: string; note?: string | null; sortOrder?: number },
): Promise<WatchlistItem> {
  return apiRequest(`/api/v1/watchlist-items/${item.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ version: item.version, ...changes }),
  });
}

/** 删除当前用户指定观察标的。 */
export function deleteWatchlistItem(itemId: string): Promise<void> {
  return apiRequest(`/api/v1/watchlist-items/${itemId}`, { method: 'DELETE' });
}
