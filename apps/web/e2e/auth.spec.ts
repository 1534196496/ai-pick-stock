import { expect, test, type BrowserContext } from '@playwright/test';

const password = 'correct-browser-password-123';

/** 通过公开页面注册并登录一个唯一测试用户。 */
async function registerAndLogin(context: BrowserContext, suffix: string) {
  const page = await context.newPage();
  const email = `browser-${Date.now()}-${suffix}@example.com`;
  await page.goto('/register');
  await page.getByLabel('邮箱').fill(email);
  await page.getByLabel('密码').fill(password);
  await page.getByRole('button', { name: '创建账户' }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel('邮箱').fill(email);
  await page.getByLabel('密码').fill(password);
  await page.getByRole('button', { name: '登录' }).click();
  await expect(page).toHaveURL(/\/holdings$/);
  return { email, page };
}

test('注册、登录、刷新保持会话和退出', async ({ context }) => {
  const { email, page } = await registerAndLogin(context, 'primary');
  await expect(page.getByText(email)).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: '持有' })).toBeVisible();
  await expect(page.getByText(email)).toBeVisible();
  await page.getByRole('button', { name: '退出' }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto('/holdings');
  await expect(page).toHaveURL(/\/login$/);
});

test('两个浏览器上下文的会话互不串用', async ({ browser }) => {
  const firstContext = await browser.newContext();
  const secondContext = await browser.newContext();
  try {
    const first = await registerAndLogin(firstContext, 'first');
    const second = await registerAndLogin(secondContext, 'second');
    await expect(first.page.getByText(first.email)).toBeVisible();
    await expect(first.page.getByText(second.email)).toHaveCount(0);
    await expect(second.page.getByText(second.email)).toBeVisible();
    await expect(second.page.getByText(first.email)).toHaveCount(0);
  } finally {
    await firstContext.close();
    await secondContext.close();
  }
});
