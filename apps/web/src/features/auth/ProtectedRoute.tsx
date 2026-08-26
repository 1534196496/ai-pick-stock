import { Navigate, Outlet, useLocation, useNavigate } from 'react-router-dom';

import { useLogout, useSession } from './hooks';

/** 等待会话恢复，并阻止未登录用户访问业务路由。 */
export function ProtectedRoute() {
  const session = useSession();
  const location = useLocation();
  if (session.isPending) return <main className="center-status" role="status">正在恢复会话…</main>;
  if (session.data === null) return <Navigate replace to="/login" state={{ from: location.pathname }} />;
  if (session.isError) return <main className="center-status" role="alert">会话服务暂时不可用，请稍后刷新。</main>;
  return <Outlet />;
}

/** 展示当前邮箱和明确的退出动作。 */
export function UserMenu() {
  const session = useSession();
  const mutation = useLogout();
  const navigate = useNavigate();
  return <div className="user-menu">
    <span className="account-label">{session.data?.email}</span>
    <button className="text-button" disabled={mutation.isPending} type="button" onClick={() => void mutation.mutateAsync().then(() => navigate('/login', { replace: true }))}>退出</button>
  </div>;
}
