import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  createInvestmentAccount,
  deleteInvestmentAccount,
  listInvestmentAccounts,
  updateInvestmentAccount,
  type InvestmentAccount,
} from './api';

export const accountsQueryKey = ['investment-accounts'] as const;

/** 读取投资账户并复用会话内缓存。 */
export function useInvestmentAccounts() {
  return useQuery({ queryKey: accountsQueryKey, queryFn: listInvestmentAccounts });
}

/** 创建账户后刷新账户列表。 */
export function useCreateInvestmentAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: createInvestmentAccount,
    onSuccess: () => client.invalidateQueries({ queryKey: accountsQueryKey }),
  });
}

/** 修改账户后刷新列表，冲突时保留调用方输入。 */
export function useUpdateInvestmentAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ account, changes }: { account: InvestmentAccount; changes: { name?: string; sortOrder?: number } }) =>
      updateInvestmentAccount(account, changes),
    onSuccess: () => client.invalidateQueries({ queryKey: accountsQueryKey }),
  });
}

/** 删除空账户后刷新列表。 */
export function useDeleteInvestmentAccount() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: deleteInvestmentAccount,
    onSuccess: () => client.invalidateQueries({ queryKey: accountsQueryKey }),
  });
}
