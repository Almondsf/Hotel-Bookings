import { closed, expect, field, modal, test, unique } from './fixtures';

test('housekeeping: generate the list, start and finish a task, skip one, inspect a room', async ({ page }) => {
  await page.goto('/housekeeping');
  await page.getByRole('button', { name: "Generate today's list" }).click();
  const tasks = page.locator('.card').first().locator('tbody tr');
  await expect(tasks.first()).toBeVisible();

  const startable = tasks.filter({ has: page.getByRole('button', { name: 'Start' }) }).first();
  const room = (await startable.locator('td strong').first().textContent())!.trim();
  await startable.getByRole('button', { name: 'Start' }).click();
  const row = tasks.filter({ hasText: room }).first();
  await expect(row.locator('.badge', { hasText: 'In progress' })).toBeVisible();
  await row.getByRole('button', { name: 'Done' }).click();
  await expect(row.locator('.badge', { hasText: 'Done' })).toBeVisible();

  const skippable = tasks.filter({ has: page.getByRole('button', { name: 'Skip' }) }).first();
  if (await skippable.count()) {
    await skippable.getByRole('button', { name: 'Skip' }).click();
    await field(modal(page), 'Reason').fill('Do Not Disturb sign');
    await modal(page).locator('button.danger, button.primary').last().click();
    await closed(page);
  }

  const status = page.locator('.card', { has: page.getByRole('heading', { name: 'Room status' }) });
  const clean = status.locator('.room-tile', { has: page.getByRole('button', { name: 'Mark inspected' }) }).first();
  const number = (await clean.locator('.number').textContent())!.trim();
  await clean.getByRole('button', { name: 'Mark inspected' }).click();
  await expect(status.locator('.room-tile', { hasText: number }).locator('.badge', { hasText: 'Inspected' })).toBeVisible();
});

test('maintenance: report a fault, work it and resolve it', async ({ page }) => {
  const issue = `Lobby light flickering ${unique()}`;
  await page.goto('/maintenance');
  await page.getByRole('button', { name: 'Report a fault' }).click();
  const dialog = modal(page);
  await field(dialog, 'Location').fill('Main lobby');
  await field(dialog, 'Category').selectOption('ELECTRICAL');
  await field(dialog, 'Priority').selectOption('HIGH');
  await field(dialog, 'Issue').fill(issue);
  await dialog.getByRole('button', { name: 'Report' }).click();
  await closed(page);

  const row = page.locator('tr', { hasText: issue });
  await expect(row.locator('.badge', { hasText: 'Open' })).toBeVisible();
  await row.getByRole('button', { name: 'Start' }).click();
  await expect(row.locator('.badge', { hasText: 'In progress' })).toBeVisible();
  await row.getByRole('button', { name: 'Hold' }).click();
  await expect(row.locator('.badge', { hasText: 'On hold' })).toBeVisible();
  await row.getByRole('button', { name: 'Resolve' }).click();
  await field(page, 'What was done').fill('Replaced the ballast');
  await page.locator('form').getByRole('button', { name: 'Resolve' }).click();
  await expect(page.locator('tr', { hasText: issue })).toHaveCount(0); // open tickets only by default
});

test('guest profile: VIP, notes and ID reveal', async ({ page }) => {
  await page.goto('/guests');
  await page.getByLabel('Search guests').fill('Okafor');
  await page.getByRole('button', { name: 'Search' }).click();
  await page.getByRole('link', { name: /Ngozi Okafor/ }).click();
  await expect(page.getByRole('heading', { name: 'Ngozi Okafor' })).toBeVisible();

  const vip = page.getByRole('button', { name: /Mark VIP|Remove VIP/ });
  const before = await vip.textContent();
  await vip.click();
  await expect(page.getByRole('button', { name: before === 'Mark VIP' ? 'Remove VIP' : 'Mark VIP' })).toBeVisible();

  const note = `Prefers a high floor ${unique()}`;
  await page.getByRole('button', { name: 'Edit notes' }).click();
  await field(page, 'Notes').fill(note);
  await page.getByRole('button', { name: 'Save' }).click();
  await expect(page.getByText(note)).toBeVisible();

  const reveal = page.getByRole('button', { name: 'Reveal' }).first();
  if (await reveal.count()) {
    await reveal.click();
    await expect(page.locator('code', { hasText: '•' })).toHaveCount(await page.locator('code').count() - 1);
  }

});

test('reports: figures and ledgers', async ({ page }) => {
  await page.goto('/reports');
  await expect(page.locator('.stat', { hasText: 'Occupancy' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Revenue by department' })).toBeVisible();


  await page.getByRole('link', { name: 'Ledgers' }).click();
  await expect(page.getByRole('heading', { name: /Guest ledger/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: /City ledger/ })).toBeVisible();
});

test.describe('file exports', () => {
  // Locally on Edge (PW_CHANNEL=msedge) a download opens an extra internal page that Playwright
  // reports as closed when the browser shuts; the app is fine. CI runs these in Chromium.
  test.skip(process.env.PW_CHANNEL === 'msedge', 'Edge download page quirk; covered in CI (Chromium)');

  test('reports export a CSV file', async ({ page }) => {
    await page.goto('/reports');
    const revenue = page.locator('.card', { has: page.getByRole('heading', { name: 'Revenue by department' }) });
    const [download] = await Promise.all([page.waitForEvent('download'), revenue.getByRole('button', { name: 'Export CSV' }).click()]);
    expect(download.suggestedFilename()).toMatch(/\.csv$/);
    expect(await download.path()).toBeTruthy();
  });

  test("a guest's data exports as a JSON file", async ({ page }) => {
    await page.goto('/guests');
    await page.getByLabel('Search guests').fill('Okafor');
    await page.getByRole('button', { name: 'Search' }).click();
    await page.getByRole('link', { name: /Ngozi Okafor/ }).click();
    const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Export data' }).click()]);
    expect(download.suggestedFilename()).toMatch(/^guest-\d+-data\.json$/);
    expect(await download.path()).toBeTruthy();
  });
});
