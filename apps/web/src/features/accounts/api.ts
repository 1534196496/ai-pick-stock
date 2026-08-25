import type { components } from '../../shared/api/schema';
import { apiRequest } from '../../shared/api/client';

export type InvestmentAccount = components['schemas']['InvestmentAccountResponse'];
export type InvestmentAccountList = components['schemas']['InvestmentAccountListResponse'];

/** 读取当前用户第一页投资账户。 */
export function listInvestmentAccounts(): Promise<InvestmentAccountList> {
  return apiRequest('/api/v1/investment-accounts?page=1&pageSize=100');
}

/** 创建投资账户。 */
export function createInvestmentAccount(name: string): Promise<InvestmentAccount> {
  return apiRequest('/api/v1/investment-accounts', {
    method: 'POST',
    body: JSON.stringify({ name }),
  });
}

/** 按乐观锁版本重命名或排序账户。 */
export function updateInvestmentAccount(
  account: InvestmentAccount,
  changes: { name?: string; sortOrder?: number },
): Promise<InvestmentAccount> {
  return apiRequest(`/api/v1/investment-accounts/${account.id}`, {
    method: 'PATCH',
    body: JSON.stringify({ version: account.version, ...changes }),
  });
}

/** 删除当前用户空账户。 */
export function deleteInvestmentAccount(accountId: string): Promise<void> {
  return apiRequest(`/api/v1/investment-accounts/${accountId}`, { method: 'DELETE' });
}
