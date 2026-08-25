import type { components } from '../../shared/api/schema';
import { apiRequest } from '../../shared/api/client';

export type Session = components['schemas']['SessionResponse'];
export type Registration = components['schemas']['RegistrationResponse'];

/** 创建用户账户。 */
export function register(email: string, password: string): Promise<Registration> {
  return apiRequest('/api/v1/auth/registrations', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

/** 创建服务端会话并接收 HttpOnly Cookie。 */
export function login(email: string, password: string): Promise<Session> {
  return apiRequest('/api/v1/auth/sessions', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

/** 恢复当前浏览器会话。 */
export function getSession(): Promise<Session> {
  return apiRequest('/api/v1/auth/session');
}

/** 撤销当前会话。 */
export function logout(): Promise<void> {
  return apiRequest('/api/v1/auth/session', { method: 'DELETE' });
}

export type PasswordResetRequestResult =
  components['schemas']['PasswordResetRequestResponse'];

/** 请求统一的密码重置邮件结果。 */
export function requestPasswordReset(email: string): Promise<PasswordResetRequestResult> {
  return apiRequest('/api/v1/auth/password-reset-requests', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });
}

/** 使用单次令牌设置新密码。 */
export function resetPassword(token: string, newPassword: string): Promise<void> {
  return apiRequest('/api/v1/auth/password-resets', {
    method: 'POST',
    body: JSON.stringify({ token, newPassword }),
  });
}
