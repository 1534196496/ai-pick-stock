import type { NavLinkRenderProps } from 'react-router-dom';
import { Link, Navigate, NavLink, Outlet, Route, Routes } from 'react-router-dom';

interface AuthPageProps {
  title: string;
  description: string;
  links: Array<{ label: string; to: string }>;
}

/** 根据当前地址为主导航提供明确的选中状态。 */
function getNavigationClassName({ isActive }: NavLinkRenderProps) {
  return isActive ? 'primary-nav__link primary-nav__link--active' : 'primary-nav__link';
}

/** 展示登录前账户流程的统一页面骨架。 */
function AuthPage({ title, description, links }: AuthPageProps) {
  return (
    <main className="auth-shell">
      <section className="auth-intro" aria-labelledby="auth-title">
        <Link className="brand brand--auth" to="/login" aria-label="持仓簿首页">
          <span className="brand__mark" aria-hidden="true">
            簿
          </span>
          <span>持仓簿</span>
        </Link>
        <p className="eyebrow">个人股票与基金账本</p>
        <h1 id="auth-title">{title}</h1>
        <p className="auth-intro__description">{description}</p>
      </section>
      <section className="auth-panel" aria-label={`${title}操作区`}>
        <p>账户功能将在认证阶段接入。</p>
        <nav className="auth-links" aria-label="账户帮助">
          {links.map((link) => (
            <Link key={link.to} to={link.to}>
              {link.label}
            </Link>
          ))}
        </nav>
      </section>
    </main>
  );
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
        <span className="account-label">个人账户</span>
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

/** 声明登录前后路由骨架；认证守卫由后续认证任务接入。 */
export function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <AuthPage
            title="登录"
            description="查看自己的持仓、自选和账户。"
            links={[
              { label: '创建账户', to: '/register' },
              { label: '忘记密码', to: '/forgot-password' },
            ]}
          />
        }
      />
      <Route
        path="/register"
        element={
          <AuthPage
            title="创建账户"
            description="用一个账户管理不同渠道的股票与基金。"
            links={[{ label: '已有账户，去登录', to: '/login' }]}
          />
        }
      />
      <Route
        path="/forgot-password"
        element={
          <AuthPage
            title="找回密码"
            description="重置链接会发送到注册邮箱。"
            links={[{ label: '返回登录', to: '/login' }]}
          />
        }
      />
      <Route
        path="/reset-password"
        element={
          <AuthPage
            title="设置新密码"
            description="完成验证后，为账户设置新的登录密码。"
            links={[{ label: '返回登录', to: '/login' }]}
          />
        }
      />
      <Route element={<PortfolioLayout />}>
        <Route path="/holdings" element={<HoldingsPage />} />
        <Route path="/watchlists" element={<WatchlistsPage />} />
      </Route>
      <Route path="/" element={<Navigate replace to="/holdings" />} />
      <Route path="*" element={<Navigate replace to="/holdings" />} />
    </Routes>
  );
}
