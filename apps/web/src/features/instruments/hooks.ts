import { useQuery } from '@tanstack/react-query';

import { searchInstruments, type AssetType } from './api';

/** 按搜索词和资产类型缓存结果，并取消已经过期的请求。 */
export function useInstrumentSearch(input: {
  query: string;
  assetType: AssetType | null;
  enabled: boolean;
}) {
  return useQuery({
    queryKey: ['instruments', 'search', input.query, input.assetType],
    queryFn: ({ signal }) => searchInstruments(
      { query: input.query, assetType: input.assetType },
      signal,
    ),
    enabled: input.enabled,
    staleTime: 5 * 60_000,
  });
}
