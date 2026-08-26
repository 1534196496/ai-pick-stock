import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createWatchlistGroup,
  createWatchlistItem,
  deleteWatchlistGroup,
  deleteWatchlistItem,
  listWatchlistGroups,
  listWatchlistItems,
  updateWatchlistGroup,
  updateWatchlistItem,
  type WatchlistGroup,
  type WatchlistGroupList,
  type WatchlistItem,
} from './api';

export const watchlistGroupsQueryKey = ['watchlist-groups'] as const;

/** 返回指定分组观察标的的稳定查询键。 */
export function watchlistItemsQueryKey(groupId: string) {
  return ['watchlist-items', groupId] as const;
}

/** 刷新分组数量和全部已读取观察列表。 */
async function invalidateWatchlists(client: ReturnType<typeof useQueryClient>) {
  await Promise.all([
    client.invalidateQueries({ queryKey: watchlistGroupsQueryKey }),
    client.invalidateQueries({ queryKey: ['watchlist-items'] }),
  ]);
}

/** 读取当前用户自选分组并复用会话内缓存。 */
export function useWatchlistGroups() {
  return useQuery({ queryKey: watchlistGroupsQueryKey, queryFn: listWatchlistGroups });
}

/** 只在选中分组后读取观察标的，并在页面可见时周期刷新。 */
export function useWatchlistItems(groupId: string | null) {
  return useQuery({
    queryKey: ['watchlist-items', groupId],
    queryFn: () => listWatchlistItems(groupId ?? ''),
    enabled: groupId !== null,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
  });
}

/** 创建分组后刷新分组列表。 */
export function useCreateWatchlistGroup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: createWatchlistGroup,
    onSuccess: () => client.invalidateQueries({ queryKey: watchlistGroupsQueryKey }),
  });
}

/** 修改分组后刷新分组列表。 */
export function useUpdateWatchlistGroup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ group, changes }: {
      group: WatchlistGroup;
      changes: { name?: string; sortOrder?: number };
    }) => updateWatchlistGroup(group, changes),
    onSuccess: () => client.invalidateQueries({ queryKey: watchlistGroupsQueryKey }),
  });
}

/** 删除空分组后刷新分组列表。 */
export function useDeleteWatchlistGroup() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: deleteWatchlistGroup,
    onSuccess: async (_data, groupId) => {
      await client.cancelQueries({ queryKey: watchlistItemsQueryKey(groupId) });
      client.setQueryData<WatchlistGroupList>(watchlistGroupsQueryKey, (current) => (
        current === undefined
          ? current
          : { ...current, items: current.items.filter((group) => group.id !== groupId) }
      ));
      client.removeQueries({ queryKey: watchlistItemsQueryKey(groupId), exact: true });
      await client.invalidateQueries({ queryKey: watchlistGroupsQueryKey });
    },
  });
}

/** 添加观察标的后刷新分组数量和观察列表。 */
export function useCreateWatchlistItem() {
  const client = useQueryClient();
  return useMutation({ mutationFn: createWatchlistItem, onSuccess: () => invalidateWatchlists(client) });
}

/** 修改或移动观察标的后刷新所有自选缓存。 */
export function useUpdateWatchlistItem() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ item, changes }: {
      item: WatchlistItem;
      changes: { groupId?: string; note?: string | null; sortOrder?: number };
    }) => updateWatchlistItem(item, changes),
    onSuccess: () => invalidateWatchlists(client),
  });
}

/** 删除观察标的后刷新分组数量和观察列表。 */
export function useDeleteWatchlistItem() {
  const client = useQueryClient();
  return useMutation({ mutationFn: deleteWatchlistItem, onSuccess: () => invalidateWatchlists(client) });
}
