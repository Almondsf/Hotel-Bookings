import { addDays, closed, expect, field, modal, test, unique } from './fixtures';

test('walk-in from the room board, then extend the stay', async ({ page }) => {
  const last = `Walkin${unique()}`;
  await page.goto('/room-board');
  const tile = page.locator('.room-tile', { has: page.getByRole('button', { name: 'Walk-in' }) }).first();
  const room = (await tile.locator('.number').textContent())!.trim();
  await tile.getByRole('button', { name: 'Walk-in' }).click();

  const dialog = modal(page);
  await field(dialog, 'First name').fill('Ada');
  await field(dialog, 'Last name').fill(last);
  await field(dialog, 'Email').fill(`${last.toLowerCase()}@example.com`);
  await field(dialog, 'Document number').fill('A12345678');
  await dialog.getByRole('button', { name: 'Check in' }).click();

  await expect(page).toHaveURL(/\/reservations\/\d+$/);
  await expect(page.locator('.badge', { hasText: 'Checked in' })).toBeVisible();
  await expect(page.locator('dd', { hasText: `${room} ·` })).toBeVisible();

  // Extend by one night: the stay is re-priced
  await page.getByRole('button', { name: 'Change' }).click();
  const departure = field(modal(page), 'Departure');
  const next = addDays(await departure.inputValue(), 1);
  await departure.fill(next);
  await modal(page).getByRole('button', { name: 'Save changes' }).click();
  await closed(page);
  await expect(page.locator('dt:text("Departure") + dd')).toContainText('2 nights');
});

test('reserve a room from the board, then check the guest in from the dashboard', async ({ page }) => {
  const last = `Board${unique()}`;
  await page.goto('/room-board');
  await page.locator('.room-tile', { has: page.getByRole('button', { name: 'Reserve' }) }).first()
    .getByRole('button', { name: 'Reserve' }).click();
  await expect(page).toHaveURL(/\/reservations\/new\?/);
  await page.waitForLoadState('networkidle'); // room types and rooms loaded, so the pre-selection sticks
  await expect(page.locator('select:has(option:text("Any available"))')).not.toHaveValue('');  // the room was pre-selected

  await field(page, 'First name').fill('Bola');
  await field(page, 'Last name').fill(last);
  await field(page, 'Email').fill(`${last.toLowerCase()}@example.com`);
  await page.getByRole('button', { name: 'Create reservation' }).click();
  await expect(page).toHaveURL(/\/reservations\/\d+$/);
  await expect(page.locator('.badge', { hasText: 'Confirmed' })).toBeVisible();

  await page.goto('/dashboard');
  const row = page.locator('tr', { hasText: last });
  await row.getByRole('button', { name: 'Check in' }).click();
  await field(modal(page), 'Document number').fill('12345678901');
  await modal(page).getByRole('button', { name: 'Check in' }).click();
  await closed(page);
  await expect(row.locator('.badge', { hasText: 'Checked in' })).toBeVisible();
});

test('check a departing guest out from the dashboard, taking card payment', async ({ page }) => {
  await page.goto('/dashboard');
  const departures = page.locator('.card', { has: page.getByRole('heading', { name: 'Departing today' }) });
  const row = departures.locator('tr', { has: page.getByRole('button', { name: 'Check out' }) }).first();
  test.skip(!(await row.count()), 'no departures left today in the demo data');
  const guest = (await row.locator('a').first().textContent())!.trim();

  await row.getByRole('button', { name: 'Check out' }).click();
  const dialog = modal(page);
  await expect(dialog.getByText('Balance to settle')).toBeVisible();
  await expect(dialog.getByText('…')).toHaveCount(0);
  const payNow = dialog.getByLabel('Guest pays now');
  if (await payNow.count()) {
    await payNow.check();
    await field(dialog, 'Reference').fill('POS-12345678');
  }
  await dialog.locator('button.primary').click();
  await closed(page);
  await expect(departures.locator('tr', { hasText: guest })).toHaveCount(0);
});

test('point of sale: tapping an item starts an order, then pay in cash', async ({ page }) => {
  await page.goto('/pos');
  await page.getByLabel('Outlet').selectOption({ label: 'Restaurant' });
  await page.locator('.pos-product:not([disabled])').first().click();
  const ticket = page.locator('.pos-ticket');
  await expect(ticket.locator('tr')).toHaveCount(1);
  await ticket.getByRole('button', { name: 'Pay' }).click();
  await modal(page).getByRole('button', { name: 'Complete sale' }).click();
  await expect(page.locator('.alert.success')).toContainText('settled');
});

test('a two-room group: staff see it together, and the guest cancels the whole group online', async ({ page }) => {
  const last = `Group${unique()}`;
  const email = `${last.toLowerCase()}@example.com`;
  const arrival = addDays(new Date().toISOString().slice(0, 10), 75);
  await page.goto('/reservations/new');
  await page.waitForLoadState('networkidle');
  await field(page, 'First name').fill('Funke');
  await field(page, 'Last name').fill(last);
  await field(page, 'Email').fill(email);
  await field(page, 'Arrival').fill(arrival);
  await field(page, 'Departure').fill(addDays(arrival, 2));
  await page.getByRole('button', { name: 'Add another room' }).click();
  for (const select of await page.locator('label.field', { hasText: /^\s*Room type/ }).locator('select').all()) {
    await select.selectOption({ index: 1 });
  }
  await page.getByRole('button', { name: 'Create reservation' }).click();
  await expect(page).toHaveURL(/\/reservations\/\d+$/);

  // The reservation links to its group, which lists both rooms
  await page.getByRole('link', { name: /^GR-/ }).click();
  await expect(page).toHaveURL(/\/groups\/GR-[A-Z0-9]+$/);
  const reference = page.url().split('/').pop()!;
  await expect(page.locator('tbody tr')).toHaveCount(2);
  await expect(page.getByRole('button', { name: 'Cancel group' })).toBeVisible();

  // The booker manages the whole group with its reference
  await page.goto('/booking/manage');
  await field(page, 'Confirmation number').fill(reference);
  await field(page, 'Email used to book').fill(email);
  await page.getByRole('button', { name: 'Find booking' }).click();
  await expect(page.getByRole('heading', { name: `Group ${reference}` })).toBeVisible();
  await expect(page.locator('.guest-group-rooms li')).toHaveCount(2);
  await page.getByRole('button', { name: 'Cancel group' }).click();
  await expect(page.locator('.guest-group-rooms .badge', { hasText: 'cancelled' })).toHaveCount(2);

  await page.goto(`/groups/${reference}`);
  await expect(page.locator('tbody .badge', { hasText: 'Cancelled' })).toHaveCount(2);
  await expect(page.getByRole('button', { name: 'Cancel group' })).toHaveCount(0);
});
