import type { NavLinkRenderProps } from 'react-router-dom';
import { Link, Navigate, NavLink, Outlet, Route, Routes } from 'react-router-dom';

import { LoginPage, RegisterPage } from '../features/auth/pages';
import { ForgotPasswordPage, ResetPasswordPage } from '../features/auth/PasswordResetPages';
import { ProtectedRoute, UserMenu } from '../features/auth/ProtectedRoute';

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

/** 展示持有页的账本抬头和可行动空状态。 */
function HoldingsPage() {
  return (
    <section className="ledger-page" aria-labelledby="holdings-title">
      <header className="ledger-heading">
        <div>
          <p className="eyebrow">全部账户</p>
          <h1 id="holdings-title">持有</h1>
        </div>
        <p>股票与基金将按投资账户汇总。</p>
      </header>
      <dl className="ledger-summary" aria-label="持仓汇总">
        <div>
          <dt>总资产</dt>
          <dd>—</dd>
        </div>
        <div>
          <dt>持仓成本</dt>
          <dd>—</dd>
        </div>
        <div>
          <dt>持有收益</dt>
          <dd>—</dd>
        </div>
      </dl>
      <div className="empty-state" role="status">
        <h2>还没有持仓</h2>
        <p>账户功能完成后，可在这里记录第一只股票或基金。</p>
      </div>
    </section>
  );
}

/** 展示自选页的分组区域和可行动空状态。 */
function WatchlistsPage() {
  return (
    <section className="ledger-page" aria-labelledby="watchlists-title">
      <header className="ledger-heading">
        <div>
          <p className="eyebrow">观察清单</p>
          <h1 id="watchlists-title">自选</h1>
        </div>
        <p>按分组整理正在观察的股票和基金。</p>
      </header>
      <div className="empty-state empty-state--compact" role="status">
        <h2>还没有自选标的</h2>
        <p>自选分组完成后，可把关注的资产加入这里。</p>
      </div>
    </section>
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
