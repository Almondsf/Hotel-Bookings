/** The public website and booking engine, as a guest who isn't signed in sees them. */
import { addDays, expect, field, test } from './fixtures';

const today = () => new Date().toISOString().slice(0, 10);

test('home page shows the hotel, its rooms and how to book', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.home-hero h1')).toBeVisible();
  const rooms = page.locator('#rooms .home-room');
  await expect(rooms.first()).toBeVisible();
  expect(await rooms.count()).toBeGreaterThanOrEqual(4);

  await rooms.first().getByRole('link', { name: 'View details' }).click();
  await expect(page).toHaveURL(/\/rooms\/[a-z0-9-]+$/);
  await expect(page.locator('.room-title')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'In your room' })).toBeVisible();
});

test('check availability lists the best fit for the party first', async ({ page }) => {
  const checkIn = addDays(today(), 20);
  await page.goto(`/book?check_in=${checkIn}&check_out=${addDays(checkIn, 2)}&adults=1&children=0`);
  const results = page.locator('.guest-room');
  await expect(results.first()).toBeVisible();
  // A lone traveller is offered the single room first, marked as the best match
  await expect(results.first().getByRole('heading')).toContainText('Classic Single');
  await expect(results.first().locator('.home-badge', { hasText: 'Best match' })).toBeVisible();

  await page.goto(`/book?check_in=${checkIn}&check_out=${addDays(checkIn, 2)}&adults=2&children=2`);
  await expect(page.locator('.guest-room').first()).toBeVisible();
  const names = await page.locator('.guest-room h2').allTextContents();
  expect(names.length).toBeGreaterThan(0);
  for (const name of names) expect(name).not.toMatch(/Classic Single|Standard Room|Twin Room|Executive Suite/);
});

test('checkout explains how to book when online payment is not set up', async ({ page }) => {
  const checkIn = addDays(today(), 20);
  await page.goto(`/book?check_in=${checkIn}&check_out=${addDays(checkIn, 1)}&adults=2&children=0`);
  await page.locator('.guest-room').first().getByRole('button', { name: 'Select' }).first().click();
  await expect(page).toHaveURL(/\/book\/checkout\?/);
  await expect(page.getByRole('alert')).toContainText("Online payment isn't available");
  await expect(field(page, 'Email')).toBeVisible();
});

test('a large party gets group plans, with the regular rooms still listed underneath', async ({ page }) => {
  const checkIn = addDays(today(), 45);
  await page.goto(`/book?check_in=${checkIn}&check_out=${addDays(checkIn, 2)}&adults=10&children=4`);
  const plans = page.locator('.guest-plan');
  await expect(plans.first()).toBeVisible();
  expect(await plans.count()).toBeGreaterThanOrEqual(2);
  await expect(plans.first().locator('.home-badge')).toHaveText('Best value');
  await expect(page.getByRole('heading', { name: 'Or browse our rooms' })).toBeVisible();
  await expect(page.locator('section[aria-label="All rooms"] .guest-room').first()).toBeVisible();

  const rooms = await plans.first().locator('li').count();
  await plans.first().getByRole('button', { name: 'Book this plan' }).click();
  await expect(page).toHaveURL(/\/book\/checkout\?.*plan=/);
  await expect(page.locator('.guest-summary .guest-plan-rooms li')).toHaveCount(rooms);
  await expect(page.getByText(`All ${rooms} rooms are held`)).toBeVisible();
});
