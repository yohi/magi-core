import { test, expect } from '@playwright/test';

test.describe('Settings Persistence and Fallback', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('1. Verify that input API keys are correctly saved to localStorage and hydrated upon page refresh', async ({ page }) => {
    // Open System Settings
    await page.click('#btn-system-settings');
    
    // 1.1 Set an API key
    // Select Anthropic provider (it's the first one in SUPPORTED_PROVIDERS)
    await page.fill('input[placeholder="ENTER API KEY FOR THIS PROVIDER"]', 'sk-test-anthropic-key');
    await page.click('button:has-text("REGISTER / UPDATE")');
    
    // Verify it's in the list (masked)
    await expect(page.locator('text=ANTHROPIC: ********')).toBeVisible();
    
    // 1.2 Enable persistence (Opt-in)
    await page.check('#persist-api-keys');
    
    // 1.3 Save
    await page.click('#btn-save');
    
    // 1.4 Verify in localStorage immediately
    let storage = await page.evaluate(() => JSON.parse(localStorage.getItem('magi_system_settings') || '{}'));
    expect(storage.providers.anthropic).toBe('sk-test-anthropic-key');
    expect(storage.persistApiKeys).toBe(true);
    
    // 1.5 Reload page
    await page.reload();
    
    // 1.6 Verify hydration
    await page.click('#btn-system-settings');
    await expect(page.locator('text=ANTHROPIC: ********')).toBeVisible();
    await expect(page.locator('#persist-api-keys')).toBeChecked();
    
    // 1.7 Verify persistence still active in localStorage
    storage = await page.evaluate(() => JSON.parse(localStorage.getItem('magi_system_settings') || '{}'));
    expect(storage.providers.anthropic).toBe('sk-test-anthropic-key');
  });

  test('2. Verify that the model selection list contains Flixa models when the /api/models API call fails', async ({ page }) => {
    // Intercept /api/models and return error to trigger fallback
    await page.route('**/api/models', async route => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'Internal Server Error' }),
      });
    });
    
    await page.reload();
    
    // Open Melchior unit settings
    await page.click('.monolith.melchior');
    
    // Select Flixa provider
    // Note: Provider labels are uppercase in select options in unit-fields
    await page.selectOption('label:has-text("PROVIDER:") + select', 'flixa');
    
    // Check model dropdown for Flixa models
    const modelSelect = page.locator('label:has-text("MODEL:") + input + select');
    const options = modelSelect.locator('option');
    
    // Verify specific Flixa models from the fallback list are present
    await expect(options.filter({ hasText: 'Flixa GPT-4o' })).toBeVisible();
    await expect(options.filter({ hasText: 'Flixa GPT-4 Turbo' })).toBeVisible();
    await expect(options.filter({ hasText: 'Flixa GPT-4' })).toBeVisible();
    await expect(options.filter({ hasText: 'Flixa GPT-3.5 Turbo' })).toBeVisible();
  });

  test('3. Confirm that existing unit settings do not lose their API keys after component effect triggers a save', async ({ page }) => {
    // 3.1 Open System Settings and enable persistence first
    await page.click('#btn-system-settings');
    await page.check('#persist-api-keys');
    await page.click('#btn-save');
    
    // 3.2 Open Balthasar unit settings
    await page.click('.monolith.balthasar');
    
    // 3.3 Set an override key
    const overrideInput = page.locator('input[placeholder="LEAVE BLANK TO USE PROVIDER KEY"]');
    await overrideInput.fill('sk-balthasar-override-key');
    
    // 3.4 Save
    await page.click('#btn-save');
    
    // 3.5 Verify in localStorage
    let storage = await page.evaluate(() => JSON.parse(localStorage.getItem('magi_unit_settings') || '{}'));
    expect(storage.balthasar.apiKey).toBe('sk-balthasar-override-key');
    
    // 3.6 Reload
    await page.reload();
    
    // 3.7 Verify hydration and check that it's NOT lost after subsequent automatic save
    // (Wait a bit for effects to run)
    await page.waitForTimeout(500); 
    
    storage = await page.evaluate(() => JSON.parse(localStorage.getItem('magi_unit_settings') || '{}'));
    expect(storage.balthasar.apiKey).toBe('sk-balthasar-override-key');
    
    // 3.8 Open modal again to see if it's in UI
    await page.click('.monolith.balthasar');
    await expect(page.locator('input[placeholder="LEAVE BLANK TO USE PROVIDER KEY"]')).toHaveValue('sk-balthasar-override-key');
  });

  test('Security Check: Verify that API keys are NOT saved when opt-in is disabled', async ({ page }) => {
    await page.click('#btn-system-settings');
    
    // Ensure persistence is unchecked
    const persistCheckbox = page.locator('#persist-api-keys');
    await expect(persistCheckbox).not.toBeChecked();
    
    // Set a key
    await page.fill('input[placeholder="ENTER API KEY FOR THIS PROVIDER"]', 'sk-sensitive-key');
    await page.click('button:has-text("REGISTER / UPDATE")');
    
    // Save
    await page.click('#btn-save');
    
    // Reload
    await page.reload();
    
    // Verify NOT in localStorage
    const storage = await page.evaluate(() => JSON.parse(localStorage.getItem('magi_system_settings') || '{}'));
    expect(storage.providers.anthropic).toBeUndefined();
    
    // Verify UI state (should be empty)
    await page.click('#btn-system-settings');
    await expect(page.locator('text=ANTHROPIC: ********')).not.toBeVisible();
  });
});
