import { useState, type FormEvent } from 'react';

interface AuthFormProps {
  mode: 'login' | 'register';
  pending: boolean;
  error: string | null;
  onSubmit: (email: string, password: string) => Promise<void>;
}

/** 提供可键盘操作、允许粘贴且带浏览器自动填充语义的认证表单。 */
export function AuthForm({ mode, pending, error, onSubmit }: AuthFormProps) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      await onSubmit(email, password);
    } catch {
      // Mutation 状态负责展示统一错误，避免表单事件产生未处理拒绝。
    }
  }

  return (
    <form className="auth-form" onSubmit={(event) => void handleSubmit(event)}>
      <label>
        邮箱
        <input
          autoComplete="email"
          inputMode="email"
          name="email"
          required
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </label>
      <label>
        密码
        <input
          autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          minLength={12}
          maxLength={128}
          name="password"
          required
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </label>
      {error !== null && <p className="form-error" role="alert">{error}</p>}
      <button className="primary-button" disabled={pending} type="submit">
        {pending ? '正在提交…' : mode === 'login' ? '登录' : '创建账户'}
      </button>
    </form>
  );
}
