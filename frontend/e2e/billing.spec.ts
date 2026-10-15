import type { Page } from '@playwright/test';

import { closed, expect, field, modal, test, unique } from './fixtures';

async function newBill(page: Page, name: string) {
  await page.goto('/folios');
  await page.getByRole('button', { name: 'New bill' }).click();
  await modal(page).locator('input[name=name]').fill(name);
  await modal(page).getByRole('button', { name: 'Open bill' }).click();
  await expect(page).toHaveURL(/\/folios\/\d+$/);
}

async function postCharge(page: Page, description: string, price: string) {
  await page.getByRole('button', { name: 'Post charge' }).click();
  await field(modal(page), 'Unit price').fill(price);
  await field(modal(page), 'Description').fill(description);
  await modal(page).getByRole('button', { name: 'Post' }).click();
  await closed(page);
}

const balance = (page: Page) => page.locator('.stat', { hasText: /Balance due|Credit/ }).locator('.value');

test('bill a non-resident: charge, payment, void, discount, move a charge', async ({ page }) => {
  const event = `Okafor dinner ${unique()}`;
  await newBill(page, event);
  await postCharge(page, 'Private dining for 5', '50000');
  await postCharge(page, 'Corkage', '5000');
  await expect(balance(page)).toHaveText('₦59,125.00'); // 55,000 + 7.5% VAT

  await page.getByRole('button', { name: 'Take payment' }).click();
  await field(modal(page), 'Amount (₦)').fill('20000');
  await modal(page).getByRole('button', { name: 'Record payment' }).click();
  await closed(page);
  await expect(balance(page)).toHaveText('₦39,125.00');

  const payments = page.locator('.card', { has: page.getByRole('heading', { name: 'Payments' }) });
  await payments.getByRole('button', { name: 'Void' }).click();
  await field(modal(page), 'Reason').fill('Keyed wrong amount');
  await modal(page).getByRole('button', { name: 'Void payment' }).click();
  await closed(page);
  await expect(payments.locator('tr.void')).toHaveCount(1);
  await expect(balance(page)).toHaveText('₦59,125.00');

  await page.getByRole('button', { name: 'Discount' }).click();
  await field(modal(page), 'Amount off').fill('5000');
  await field(modal(page), 'Reason').fill('Regular guest');
  await modal(page).getByRole('button', { name: 'Apply discount' }).click();
  await closed(page);
  await expect(page.locator('td', { hasText: 'Discount: Regular guest' })).toBeVisible();
  await expect(balance(page)).toHaveText('₦53,750.00');

  // Corkage goes to another open bill
  const charges = page.locator('.card', { has: page.getByRole('heading', { name: 'Charges' }) });
  await charges.locator('tr', { hasText: 'Corkage' }).getByRole('button', { name: 'Move' }).click();
  await modal(page).locator('select').selectOption({ index: 1 });
  await field(modal(page), 'Reason').fill('Host pays drinks');
  await modal(page).getByRole('button', { name: 'Move charge' }).click();
  await closed(page);
  await expect(balance(page)).toHaveText('₦48,375.00');
});

test('bill a company, see it on the statement and record its payment', async ({ page }) => {
  const event = `Shell meeting ${unique()}`;
  await newBill(page, event);
  await postCharge(page, 'Meeting room hire', '100000');
  await page.getByRole('button', { name: 'Bill to company' }).click();
  await modal(page).locator('select').selectOption({ label: 'Shell Nigeria' });
  await modal(page).getByRole('button', { name: 'Bill to company' }).click();
  await closed(page);
  await expect(page.locator('.badge', { hasText: 'Transferred' })).toBeVisible();
  await expect(page.getByText('Invoices')).toBeVisible();

  await page.goto('/companies');
  await page.getByRole('link', { name: 'Shell Nigeria' }).click();
  await expect(page.locator('tr', { hasText: event })).toBeVisible();
  await page.getByRole('button', { name: 'Record payment' }).click();
  await field(modal(page), 'Amount (₦)').fill('107500');
  await field(modal(page), 'Reference').fill('TRF-998877');
  await modal(page).getByRole('button', { name: 'Record payment' }).click();
  await closed(page);
  await expect(page.locator('tr', { hasText: 'TRF-998877' })).toBeVisible();
});

test('open an invoice PDF in a new tab', async ({ page }) => {
  await page.goto('/folios?status=SETTLED');
  await page.locator('tbody a[href^="/folios/"]').first().click();
  // A tab opens during the click (so pop-up blockers allow it) and the PDF is fetched with the
  // staff session. Browsers with a PDF viewer show it there; headless test browsers download it.
  const [tab, pdf] = await Promise.all([
    page.waitForEvent('popup'),
    page.waitForResponse((r) => /\/invoices\/\d+\/pdf\/$/.test(new URL(r.url()).pathname)),
    page.getByRole('button', { name: 'Open PDF' }).first().click(),
  ]);
  expect(tab).toBeTruthy();
  expect(pdf.status()).toBe(200);
  expect(pdf.headers()['content-type']).toContain('application/pdf');
});

test('add a company account', async ({ page }) => {
  const name = `Zenith Bank ${unique()}`;
  await page.goto('/companies');
  await page.getByRole('button', { name: 'Add company' }).click();
  await field(modal(page), 'Company name').fill(name);
  await field(modal(page), 'Code').fill(`zenith-${unique()}`);
  await modal(page).getByRole('button', { name: 'Save' }).click();
  await closed(page);
  await expect(page.getByRole('link', { name })).toBeVisible({ timeout: 20_000 }); // the list refetches after saving
});
