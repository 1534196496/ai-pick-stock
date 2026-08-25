import { useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { ApiClientError } from '../../shared/api/client';
import { usePasswordReset, usePasswordResetRequest } from './hooks';

/** 提供找回密码请求表单，成功文案不泄露邮箱存在性。 */
export function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const mutation = usePasswordResetRequest();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await mutation.mutateAsync(email);
    } catch {
      // Mutation 状态负责展示稳定错误。
    }
  }

  return <main className="standalone-auth"><section className="auth-panel" aria-labelledby="forgot-title">
    <p className="eyebrow">账户安全</p><h1 id="forgot-title">找回密码</h1>
    {mutation.isSuccess ? <div role="status"><p>{mutation.data.message}</p><p className="muted-copy">请检查收件箱和垃圾邮件；链接 30 分钟内有效。</p></div> : <form className="auth-form" onSubmit={(event) => void submit(event)}>
      <label>注册邮箱<input autoComplete="email" inputMode="email" required type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
      {mutation.isError && <p className="form-error" role="alert">暂时无法提交，请稍后重试。</p>}
      <button className="primary-button" disabled={mutation.isPending} type="submit">{mutation.isPending ? '正在提交…' : '发送重置邮件'}</button>
    </form>}
    <nav className="auth-links" aria-label="账户帮助"><Link to="/login">返回登录</Link></nav>
  </section></main>;
}

/** 使用 URL 中的单次令牌设置并确认新密码。 */
export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);
  const mutation = usePasswordReset();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (password !== confirmation) {
      setLocalError('两次输入的密码不一致');
      return;
    }
    setLocalError(null);
    try {
      await mutation.mutateAsync({ token, newPassword: password });
    } catch {
      // Mutation 状态负责展示后端统一令牌错误。
    }
  }

  if (token === '') return <ResetFailure message="重置链接缺少令牌" />;
  if (mutation.isSuccess) return <main className="standalone-auth"><section className="auth-panel" role="status"><h1>密码已更新</h1><p>所有旧会话已退出，请使用新密码登录。</p><Link to="/login">返回登录</Link></section></main>;
  const apiMessage = mutation.error instanceof ApiClientError ? mutation.error.message : null;
  return <main className="standalone-auth"><section className="auth-panel" aria-labelledby="reset-title">
    <p className="eyebrow">账户安全</p><h1 id="reset-title">设置新密码</h1>
    <form className="auth-form" onSubmit={(event) => void submit(event)}>
      <label>新密码<input autoComplete="new-password" minLength={12} maxLength={128} required type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
      <label>再次输入新密码<input autoComplete="new-password" minLength={12} maxLength={128} required type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
      {(localError ?? apiMessage) !== null && <p className="form-error" role="alert">{localError ?? apiMessage}</p>}
      <button className="primary-button" disabled={mutation.isPending} type="submit">{mutation.isPending ? '正在更新…' : '设置新密码'}</button>
    </form>
    {mutation.isError && <nav className="auth-links"><Link to="/forgot-password">重新申请链接</Link></nav>}
  </section></main>;
}

/** 展示不可恢复的令牌缺失状态和重新申请入口。 */
function ResetFailure({ message }: { message: string }) {
  return <main className="standalone-auth"><section className="auth-panel" role="alert"><h1>无法重置密码</h1><p>{message}</p><Link to="/forgot-password">重新申请链接</Link></section></main>;
}
