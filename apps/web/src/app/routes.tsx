import type { NavLinkRenderProps } from 'react-router-dom';
import { Link, Navigate, NavLink, Outlet, Route, Routes } from 'react-router-dom';

import { LoginPage, RegisterPage } from '../features/auth/pages';
import { ForgotPasswordPage, ResetPasswordPage } from '../features/auth/PasswordResetPages';
import { ProtectedRoute, UserMenu } from '../features/auth/ProtectedRoute';
import { HoldingsPage } from '../features/holdings/HoldingsPage';
import { WatchlistsPage } from '../features/watchlists/WatchlistsPage';

/** 根据当前地址为主导航提供明确的选中状态。 */
function getNavigationClassName({ isActive }: NavLinkRenderProps) {
  return isActive ? 'primary-nav__link primary-nav__link--active' : 'primary-nav__link';
}

/** 展示登录后的产品外壳和唯一两项业务导航。 */
function PortfolioLayout() {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <header className="site-header">
        <Link className="brand" to="/holdings" aria-label="持仓簿首页">
          <span className="brand__mark" aria-hidden="true">
            簿
          </span>
          <span>持仓簿</span>
        </Link>
        <nav className="primary-nav" aria-label="主要导航">
          <NavLink className={getNavigationClassName} to="/holdings">
            持有
          </NavLink>
          <NavLink className={getNavigationClassName} to="/watchlists">
            自选
          </NavLink>
        </nav>
        <UserMenu />
      </header>
      <main id="main-content" className="main-content" tabIndex={-1}>
        <Outlet />
      </main>
    </div>
  );
}

/** 声明登录前账户路由与受会话保护的业务路由。 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route element={<ProtectedRoute />}>
        <Route element={<PortfolioLayout />}>
          <Route path="/holdings" element={<HoldingsPage />} />
          <Route path="/watchlists" element={<WatchlistsPage />} />
        </Route>
      </Route>
      <Route path="/" element={<Navigate replace to="/holdings" />} />
      <Route path="*" element={<Navigate replace to="/holdings" />} />
    </Routes>
  );
}
