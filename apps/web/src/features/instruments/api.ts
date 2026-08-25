import { apiRequest } from '../../shared/api/client';
import type { components } from '../../shared/api/schema';

export type AssetType = components['schemas']['AssetType'];
export type Instrument = components['schemas']['InstrumentResponse'];
export type InstrumentList = components['schemas']['InstrumentListResponse'];

export interface InstrumentSearchInput {
  query: string;
  assetType: AssetType | null;
  page?: number;
  pageSize?: number;
}

/** 搜索本地资产主数据，并允许查询库取消过期请求。 */
export function searchInstruments(
  input: InstrumentSearchInput,
  signal?: AbortSignal,
): Promise<InstrumentList> {
  const parameters = new URLSearchParams({
    query: input.query,
    page: String(input.page ?? 1),
    pageSize: String(input.pageSize ?? 20),
  });
  if (input.assetType !== null) {
    parameters.set('assetType', input.assetType);
  }
  return apiRequest(`/api/v1/instruments?${parameters.toString()}`, { signal });
}
