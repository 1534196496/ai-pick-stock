import { expect, test } from '@playwright/test';

const password = 'correct-account-password-123';

test('用户菜单内完成投资账户管理且一级菜单保持两项', async ({ page }) => {
  const email = `accounts-${Date.now()}@example.com`;
  await page.goto('/register');
  await page.getByLabel('邮箱').fill(email);
  await page.getByLabel('密码').fill(password);
  await page.getByRole('button', { name: '创建账户' }).click();
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel('邮箱').fill(email);
  await page.getByLabel('密码').fill(password);
  await page.getByRole('button', { name: '登录' }).click();
  await expect(page).toHaveURL(/\/holdings$/);

  const navigation = page.getByRole('navigation', { name: '主要导航' });
  await expect(navigation.getByRole('link')).toHaveCount(2);
  await expect(navigation.getByRole('link').allTextContents()).resolves.toEqual(['持有', '自选']);

  await page.getByRole('button', { name: '投资账户' }).click();
  const dialog = page.getByRole('dialog', { name: '投资账户' });
  await expect(dialog.getByText('默认账户')).toBeVisible();
  await dialog.getByLabel('新账户名称').fill('证券账户');
  await dialog.getByRole('button', { name: '创建' }).click();
  await expect(dialog.getByText('证券账户')).toBeVisible();

  const row = dialog.getByRole('listitem').filter({ hasText: '证券账户' });
  await row.getByRole('button', { name: '重命名' }).click();
  await dialog.getByLabel('证券账户的新名称').fill('长期账户');
  await dialog.getByRole('button', { name: '保存' }).click();
  await expect(dialog.getByText('长期账户')).toBeVisible();

  const renamed = dialog.getByRole('listitem').filter({ hasText: '长期账户' });
  await renamed.getByRole('button', { name: '删除' }).click();
  await renamed.getByRole('button', { name: '确认删除' }).click();
  await expect(dialog.getByText('长期账户')).toHaveCount(0);
});
