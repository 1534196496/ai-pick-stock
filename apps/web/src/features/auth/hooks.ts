import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { ApiClientError } from '../../shared/api/client';
import {
  getSession,
  login,
  logout,
  register,
  requestPasswordReset,
  resetPassword,
  type Session,
} from './api';

export const sessionQueryKey = ['auth', 'session'] as const;

/** 读取当前会话；未登录是正常空状态，不作为重试错误。 */
export function useSession() {
  return useQuery<Session | null>({
    queryKey: sessionQueryKey,
    queryFn: async () => {
      try {
        return await getSession();
      } catch (error) {
        if (error instanceof ApiClientError && error.status === 401) return null;
        throw error;
      }
    },
    retry: false,
    staleTime: 60_000,
  });
}

/** 登录成功后立即写入会话缓存。 */
export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      login(email, password),
    onSuccess: (session) => queryClient.setQueryData(sessionQueryKey, session),
  });
}

/** 提交注册表单并返回新用户身份。 */
export function useRegister() {
  return useMutation({
    mutationFn: ({ email, password }: { email: string; password: string }) =>
      register(email, password),
  });
}

/** 退出后清除所有用户私有缓存。 */
export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: logout,
    onSuccess: () => queryClient.clear(),
  });
}


/** 请求密码重置邮件，并保留防枚举的统一成功结果。 */
export function usePasswordResetRequest() {
  return useMutation({ mutationFn: (email: string) => requestPasswordReset(email) });
}

/** 消费单次令牌设置新密码。 */
export function usePasswordReset() {
  return useMutation({
    mutationFn: ({ token, newPassword }: { token: string; newPassword: string }) =>
      resetPassword(token, newPassword),
  });
}
