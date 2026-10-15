/** Runs after every other test: closing the day moves the hotel's business date. */
import { closed, expect, field, modal, test } from './fixtures';

test('close the day: check out stragglers in place, mark no-shows, run the audit', async ({ page }) => {
  await page.goto('/night-audit');
  const subtitle = await page.locator('.page-header p').textContent();

  // Guests due out are checked out from the audit page itself
  const departures = page.locator('.audit-list li', { has: page.getByRole('button', { name: 'Check out' }) });
  while (await departures.count()) {
    await departures.first().getByRole('button', { name: 'Check out' }).click();
    const dialog = modal(page);
    await expect(dialog.getByText('Balance to settle')).toBeVisible();
    await expect(dialog.getByText('…')).toHaveCount(0);
    if (await dialog.getByLabel('Guest pays now').count()) {
      await dialog.getByLabel('Guest pays now').check();
      await field(dialog, 'Reference').fill('POS-55667788');
    }
    await dialog.locator('button.primary').click();
    await closed(page);
  }

  const noShows = page.getByLabel(/Mark them as no-shows/);
  if (await noShows.count()) await noShows.check();
  await page.getByRole('button', { name: /^Close .* and post room charges$/ }).click();
  await expect(page.locator('.alert.success')).toContainText('Business date is now');
  await expect(page.locator('.page-header p')).not.toHaveText(subtitle!);
});
