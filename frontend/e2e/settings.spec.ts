import { closed, expect, field, modal, test, unique } from './fixtures';

test('settings: change a room rate, take a room out of service and back', async ({ page }) => {
  await page.goto('/settings?tab=rooms');
  const types = page.locator('.card', { has: page.getByRole('heading', { name: 'Room types' }) });
  await types.locator('tr', { hasText: 'Standard Room' }).getByRole('button', { name: 'Edit' }).click();
  await field(modal(page), 'Base nightly rate').fill('90000');
  await modal(page).getByRole('button', { name: 'Save' }).click();
  await closed(page);
  await expect(types.locator('tr', { hasText: 'Standard Room' })).toContainText('₦90,000.00');

  const rooms = page.locator('.card', { has: page.getByRole('heading', { name: 'Rooms', exact: true }) });
  const row = rooms.locator('tr', { hasText: '106' });
  await row.getByRole('button', { name: 'Edit' }).click();
  await field(modal(page), 'Availability').selectOption('OUT_OF_SERVICE');
  await field(modal(page), 'Notes').fill('Repainting');
  await modal(page).getByRole('button', { name: 'Save' }).click();
  await closed(page);
  await expect(row.locator('.badge', { hasText: 'Out of service' })).toBeVisible();
  await row.getByRole('button', { name: 'Edit' }).click();
  await field(modal(page), 'Availability').selectOption('AVAILABLE');
  await modal(page).getByRole('button', { name: 'Save' }).click();
  await closed(page);
  await expect(row.locator('.badge', { hasText: 'Available' })).toBeVisible();
});

test('settings: add a rate plan and a selling restriction', async ({ page }) => {
  const plan = `Weekend Escape ${unique()}`;
  await page.goto('/settings?tab=rates');
  await page.getByRole('button', { name: 'Add rate plan' }).click();
  await field(modal(page), 'Name').fill(plan);
  await field(modal(page), 'Code').fill(`WKND${unique()}`.toUpperCase());
  await field(modal(page), 'Adjustment %').fill('-12');
  await modal(page).getByRole('button', { name: 'Save' }).click();
  await closed(page);
  await expect(page.locator('td', { hasText: plan })).toBeVisible();

  const note = `Hotel bought out ${unique()}`;
  await page.goto('/settings?tab=restrictions');
  await page.getByRole('button', { name: 'Add restriction' }).click();
  await modal(page).getByLabel('Stop sell').check();
  await field(modal(page), 'Note').fill(note);
  await modal(page).getByRole('button', { name: 'Add' }).click();
  await closed(page);
  const row = page.locator('tr', { hasText: note });
  await expect(row).toContainText('Stop sell');
  await row.getByRole('button', { name: 'Remove' }).click();
  await expect(row).toHaveCount(0);
});

test('settings: add a menu item and set an exchange rate', async ({ page }) => {
  const item = `Nkwobi ${unique()}`;
  await page.goto('/settings?tab=menus');
  await page.getByRole('button', { name: 'Add item' }).click();
  await field(modal(page), 'Name').fill(item);
  await field(modal(page), 'Menu section').fill('Starters');
  await field(modal(page), 'Price').fill('7500');
  await modal(page).getByRole('button', { name: 'Save' }).click();
  await closed(page);
  await expect(page.locator('td', { hasText: item })).toBeVisible();

  await page.goto('/settings?tab=taxes');
  await page.getByLabel('Rate in naira').fill('1560'); // a whole number must be accepted
  await page.getByRole('button', { name: 'Set rate' }).click();
  await expect(page.locator('tr', { hasText: '1 USD' })).toContainText('₦1,560.00');
});

test('staff: edit a team member', async ({ page }) => {
  await page.goto('/staff');
  await page.locator('tr', { hasText: 'bar@demo.hotel' }).getByRole('button', { name: 'Edit' }).click();
  await field(modal(page), 'Phone').fill('08031112222');
  await modal(page).getByRole('button', { name: 'Save' }).click();
  await closed(page);
});
