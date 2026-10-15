/**
 * Shared test setup. Every test fails if the app hits an unexpected API error
 * or a JavaScript error, so a button that quietly fails is caught even when
 * the screen looks fine. Tests that expect an error call `allowApiError`.
 */
import { expect, test as base, type Locator, type Page } from '@playwright/test';

/** Created by `manage.py seed_demo`. */
export const ADMIN = { email: 'admin@demo.hotel', password: 'DemoPass#2026' };

type Fixtures = { allowApiError: (pattern: RegExp) => void; signedIn: boolean; session: void };

export const test = base.extend<Fixtures>({
  // Projects for staff screens set `signedIn: true`. Each test signs in for itself: the refresh
  // token rotates on every use (the old one is revoked), so a saved session only works once.
  signedIn: [false, { option: true }],
  session: [async ({ page, signedIn }, use) => {
    if (signedIn) {
      await page.goto('/login');
      await page.fill('input[type=email]', ADMIN.email);
      await page.fill('input[type=password]', ADMIN.password);
      await page.click('button:has-text("Sign in")');
      await page.waitForURL(/\/dashboard$/);
    }
    await use();
  }, { auto: true }],
  allowApiError: [async ({ page }, use) => {
    const allowed: RegExp[] = [/\/api\/auth\/refresh\//];
    const problems: string[] = [];
    page.on('response', async (response) => {
      const url = response.url();
      if (!url.includes('/api/') || response.status() < 400 || allowed.some((p) => p.test(url))) return;
      const body = await response.text().catch(() => '');
      problems.push(`${response.request().method()} ${new URL(url).pathname} -> ${response.status()} ${body.slice(0, 200)}`);
    });
    page.on('pageerror', (error) => problems.push(`page error: ${error.message}`));
    await use((pattern) => allowed.push(pattern));
    // Let requests still in flight finish (and be checked) before the browser closes under them
    await page.waitForLoadState('networkidle').catch(() => undefined);
    expect(problems, 'unexpected API or page errors').toEqual([]);
  }, { auto: true }],
});

export { expect };
export type Options = { signedIn: boolean };

/** The open dialog. */
export const modal = (page: Page) => page.locator('.modal');

/** Wait for the open dialog to close (its action succeeded). */
export async function closed(page: Page) {
  await expect(modal(page)).toHaveCount(0);
}

/** A form field by its label. Labels also contain hint text, so match how the label starts ("Code" ≠ "Promo code"). */
export function field(scope: Page | Locator, label: string) {
  const startsWith = new RegExp(`^\\s*${label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`);
  return scope.locator('label.field', { hasText: startsWith }).locator('input, select, textarea').first();
}

/** YYYY-MM-DD `days` after an ISO date, without time-zone surprises. */
export function addDays(iso: string, days: number) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/** A short unique suffix so repeated runs don't collide. */
export const unique = () => Date.now().toString(36).slice(-5);
