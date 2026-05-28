import { expect, test } from '@playwright/test';

// The theme toggle lives in the root layout, so it is exercised on a
// data-free page to stay independent of the ledger service.
test.use({ colorScheme: 'light' });

test('toggle switches theme, persists it, and survives reload', async ({ page }) => {
	await page.goto('/demo/playwright');

	const html = page.locator('html');
	const toggle = page.getByRole('button', { name: 'Switch to dark mode' });

	// No stored preference + light OS scheme => starts light.
	await expect(html).not.toHaveClass(/dark/);

	await toggle.click();
	await expect(html).toHaveClass(/dark/);
	expect(await page.evaluate(() => localStorage.getItem('theme'))).toBe('dark');

	// Persisted choice should be applied before paint on reload (no flash).
	await page.reload();
	await expect(html).toHaveClass(/dark/);

	await page.getByRole('button', { name: 'Switch to light mode' }).click();
	await expect(html).not.toHaveClass(/dark/);
	expect(await page.evaluate(() => localStorage.getItem('theme'))).toBe('light');
});
