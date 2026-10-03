import { test, expect } from '@playwright/test';

test('incomplete row prevents saving and approval until its value is corrected', async ({ page }) => {
  await page.goto('/login');
  await page.getByRole('button', { name: 'Open reference example' }).click();
  await expect(page.getByRole('heading', { name: 'Review data', exact: true })).toBeVisible({ timeout: 15000 });
  const first = page.getByRole('spinbutton', { name: 'Row 1 value', exact: true });
  await expect(first).toHaveValue('9.2');
  const originalRowCount = await page.locator('#result-table tbody tr').count();
  const mutations = [];
  page.on('request', (request) => {
    if (['PATCH', 'POST'].includes(request.method())
      && /\/api\/jobs\/[^/]+\/(result|approve)$/.test(new URL(request.url()).pathname)) {
      mutations.push(request);
    }
  });

  await first.fill('');
  await page.getByRole('button', { name: 'Save corrections', exact: true }).click();
  await expect(page.locator('#editor-change-note')).toHaveText('Row 1: Enter a finite numeric value, or remove this row.');
  await expect(first).toBeFocused();
  await expect(first).toHaveAttribute('aria-invalid', 'true');
  await expect(first).toHaveAttribute('aria-describedby', 'editor-change-note');
  await expect(page.locator('#result-table tbody tr')).toHaveCount(originalRowCount);
  expect(mutations).toHaveLength(0);

  await page.getByRole('button', { name: 'Save & approve', exact: true }).click();
  await expect(first).toBeFocused();
  await expect(first).toHaveValue('');
  await expect(page.getByRole('heading', { name: 'Review data', exact: true })).toBeVisible();
  expect(mutations).toHaveLength(0);

  await first.fill('0');
  await expect(page.locator('#editor-change-note')).toHaveText('Unsaved changes');
  await expect(first).not.toHaveAttribute('aria-invalid', 'true');
  await page.getByRole('button', { name: 'Save & approve', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Approved data', exact: true })).toBeVisible();
  await expect(first).toHaveValue('0');
  await expect(page.locator('#result-table tbody tr')).toHaveCount(originalRowCount);
  expect(mutations.map((request) => request.method())).toEqual(['PATCH', 'POST']);
  expect(mutations[0].postDataJSON().result.series[0].points[0].y).toBe(0);
});

test('reference correction, undo, paste, approval, export and version comparison', async ({ page }) => {
  await page.goto('/login');
  await page.getByRole('button', { name: 'Open reference example' }).click();
  await expect(page.getByRole('heading', { name: 'Review data', exact: true })).toBeVisible();
  const first = page.getByRole('spinbutton', { name: 'Row 1 value', exact: true });
  await expect(first).toHaveValue('9.2');
  await first.fill('9.3');
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(first).toHaveValue('9.2');
  await page.getByLabel('Row 1 category', { exact: true }).focus();
  await expect(page.getByRole('button', { name: 'Redo', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Redo', exact: true }).click();
  await expect(first).toHaveValue('9.3');
  await page.getByText('Paste a table from a spreadsheet', { exact: true }).click();
  await page.getByLabel('Tab-separated rows').fill('Alpha\t12.5\nBeta\t-3');
  await page.getByRole('button', { name: 'Replace table with pasted rows' }).click();
  await expect(page.getByLabel('Row 1 category', { exact: true })).toHaveValue('Alpha');
  await page.getByRole('button', { name: 'Reverse rows within each series' }).click();
  await expect(page.getByLabel('Row 1 category', { exact: true })).toHaveValue('Beta');
  await page.getByRole('button', { name: 'Save & approve', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Approved data', exact: true })).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: /Download workbook/ }).click();
  expect((await download).suggestedFilename()).toMatch(/\.xlsx$/);
  await page.getByRole('button', { name: 'Show versions' }).click();
  await page.getByRole('button', { name: 'Compare with current' }).last().click();
  await expect(page.locator('#version-comparison')).toContainText('changed rows');
  await page.getByRole('combobox', { name: 'Appearance' }).selectOption('dark');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('customer library organization and empty search keep filters reachable', async ({ page, request }) => {
  const email = `browser-${Date.now()}@example.test`;
  const password = 'Disposable browser acceptance password';
  const registration = await request.post('/api/auth/register', { data: { email, password } });
  expect(registration.status()).toBe(201);
  await page.goto('/login');
  await page.getByRole('textbox', { name: 'Email', exact: true }).fill(email);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'Sign in', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'My charts', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Use the saved example' }).click();
  await expect(page.getByRole('heading', { name: 'Review data', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Back to My charts' }).click();
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await page.getByRole('dialog').getByRole('textbox').fill('Acceptance project');
  await page.getByRole('dialog').getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeHidden();
  await page.getByRole('searchbox', { name: 'Find a chart' }).fill('nothing matches this');
  await expect(page.getByText('No charts match. Try another search or filter.')).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Filter by project' })).toBeVisible();
});
