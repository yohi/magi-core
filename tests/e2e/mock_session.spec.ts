import { test, expect } from '@playwright/test';

test.describe('MAGI WebUI E2E', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('should verify UI structure (Hardening)', async ({ page }) => {
    const container = page.locator('#magi-system');
    await expect(container).toBeVisible();

    const statusBar = page.locator('.status-bar');
    await expect(statusBar).toBeVisible();
    
    // フェーズ表示要素の存在確認（文言依存を回避）
    const phaseTxt = page.locator('#phase-txt');
    await expect(phaseTxt).toBeVisible();

    await expect(page.locator('.monolith.melchior')).toBeVisible();
    await expect(page.locator('.monolith.balthasar')).toBeVisible();
    await expect(page.locator('.monolith.casper')).toBeVisible();

    await expect(page.locator('.panel.log-panel')).toBeVisible();

    await expect(page.locator('#prompt-input')).toBeVisible();
    await expect(page.locator('#btn-start')).toBeVisible();
  });

  test('should verify session flow (Mock/Real)', async ({ page }) => {
    const promptInput = page.locator('#prompt-input');
    const startBtn = page.locator('#btn-start');
    const phaseTxt = page.locator('#phase-txt');

    await promptInput.fill('Test Prompt from E2E');
    await startBtn.click();

    // セッション開始を確認
    await expect(phaseTxt).not.toHaveText('IDLE', { timeout: 10000 });
    
    // ログエントリの表示確認
    const logs = page.locator('.log-entry');
    await expect(logs.first()).toBeVisible();

    // セッション完了を検証（最終フェーズ到達）
    await expect(phaseTxt).toHaveText(/COMPLETED|FINISHED|DONE/, { timeout: 30000 });
    
    // 結果コンソールの表示確認
    const resultConsole = page.locator('.result-console, .output-panel, [data-testid="result-output"]');
    await expect(resultConsole.first()).toBeVisible({ timeout: 5000 });
  });
});
