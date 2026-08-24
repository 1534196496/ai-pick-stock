// @vitest-environment jsdom

/** 应用级路由与主导航契约测试。 */

import '@testing-library/jest-dom/vitest';

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import { AppRoutes } from './routes';

afterEach(cleanup);

/** 从指定地址渲染不依赖浏览器历史的应用路由。 */
function renderRoute(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

describe('AppRoutes', () => {
  it('登录页不展示登录后的业务导航', () => {
    renderRoute('/login');

    expect(screen.getByRole('heading', { level: 1, name: '登录' })).toBeInTheDocument();
    expect(screen.queryByRole('navigation', { name: '主要导航' })).not.toBeInTheDocument();
  });

  it('登录后只有持有和自选两个业务入口，并可完成页面切换', () => {
    renderRoute('/holdings');

    const navigation = screen.getByRole('navigation', { name: '主要导航' });
    const links = within(navigation).getAllByRole('link');

    expect(links).toHaveLength(2);
    expect(links.map((link) => link.textContent)).toEqual(['持有', '自选']);
    expect(screen.getByRole('heading', { level: 1, name: '持有' })).toBeInTheDocument();

    fireEvent.click(within(navigation).getByRole('link', { name: '自选' }));

    expect(screen.getByRole('heading', { level: 1, name: '自选' })).toBeInTheDocument();
  });
});
