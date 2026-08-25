import { expect, test } from '@playwright/test';

test('找回密码保持统一成功文案', async ({ page }) => {
  await page.route('**/api/v1/auth/password-reset-requests', async (route) => {
    await route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ message: '如果该邮箱已注册，我们会发送密码重置邮件' }) });
  });
  await page.goto('/forgot-password');
  await page.getByLabel('注册邮箱').fill('missing@example.com');
  await page.getByRole('button', { name: '发送重置邮件' }).click();
  await expect(page.getByRole('status')).toContainText('如果该邮箱已注册');
  await expect(page.getByText('missing@example.com')).toHaveCount(0);
});

test('过期重置链接提供重新申请路径', async ({ page }) => {
  await page.route('**/api/v1/auth/password-resets', async (route) => {
    await route.fulfill({ status: 422, contentType: 'application/json', body: JSON.stringify({ error: { code: 'INVALID_OR_EXPIRED_RESET_TOKEN', message: '重置链接无效或已过期', requestId: 'req_e2e_reset' } }) });
  });
  await page.goto('/reset-password?token=expired-token');
  await page.getByLabel('新密码', { exact: true }).fill('new-correct-password-123');
  await page.getByLabel('再次输入新密码').fill('new-correct-password-123');
  await page.getByRole('button', { name: '设置新密码' }).click();
  await expect(page.getByRole('alert')).toContainText('无效或已过期');
  await expect(page.getByRole('link', { name: '重新申请链接' })).toBeVisible();
});
