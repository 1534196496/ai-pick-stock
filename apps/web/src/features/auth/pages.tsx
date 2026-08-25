import { Link, Navigate, useNavigate } from 'react-router-dom';

import { ApiClientError } from '../../shared/api/client';
import { AuthForm } from './AuthForm';
import { useLogin, useRegister, useSession } from './hooks';

interface AuthPanelProps {
  title: string;
  description: string;
  children: React.ReactNode;
  links: Array<{ label: string; to: string }>;
}

/** 展示账户流程共用的安静账本式页面。 */
function AuthPanel({ title, description, children, links }: AuthPanelProps) {
  return <main className="auth-shell">
    <section className="auth-intro" aria-labelledby="auth-title">
      <Link className="brand brand--auth" to="/login"><span className="brand__mark" aria-hidden="true">簿</span><span>持仓簿</span></Link>
      <p className="eyebrow">个人股票与基金账本</p>
      <h1 id="auth-title">{title}</h1><p className="auth-intro__description">{description}</p>
    </section>
    <section className="auth-panel" aria-label={`${title}操作区`}>
      {children}
      <nav className="auth-links" aria-label="账户帮助">{links.map((link) => <Link key={link.to} to={link.to}>{link.label}</Link>)}</nav>
    </section>
  </main>;
}

function errorMessage(error: unknown): string | null {
  if (error instanceof ApiClientError) return `${error.message}（请求：${error.requestId}）`;
  return error instanceof Error ? error.message : null;
}

/** 登录页面在成功后进入持有页。 */
export function LoginPage() {
  const navigate = useNavigate();
  const session = useSession();
  const mutation = useLogin();
  if (session.data !== null && session.data !== undefined) return <Navigate replace to="/holdings" />;
  return <AuthPanel title="登录" description="查看自己的持仓、自选和账户。" links={[{ label: '创建账户', to: '/register' }, { label: '忘记密码', to: '/forgot-password' }]}>
    <AuthForm mode="login" pending={mutation.isPending} error={errorMessage(mutation.error)} onSubmit={async (email, password) => { await mutation.mutateAsync({ email, password }); navigate('/holdings', { replace: true }); }} />
  </AuthPanel>;
}

/** 注册页面成功后引导用户使用新账户登录。 */
export function RegisterPage() {
  const navigate = useNavigate();
  const mutation = useRegister();
  return <AuthPanel title="创建账户" description="用一个账户管理不同渠道的股票与基金。" links={[{ label: '已有账户，去登录', to: '/login' }]}>
    <AuthForm mode="register" pending={mutation.isPending} error={errorMessage(mutation.error)} onSubmit={async (email, password) => { await mutation.mutateAsync({ email, password }); navigate('/login', { replace: true, state: { registered: true } }); }} />
  </AuthPanel>;
}
