import { expect, test, type Page } from "@playwright/test";

const FORBIDDEN = /\b(BUY|SELL|LONG|SHORT|ENTRY|EXIT|TARGET|STOP[ -]LOSS|SIGNAL SCORE|AI SIGNAL|PREDICTION|PROBABILITY)\b/;

async function noForbidden(page: Page) {
  const text = await page.locator("#main").innerText();
  expect(text).not.toMatch(FORBIDDEN);
  // no data element may claim to be live (Stage 1 has no live tick store); the
  // acceptance gate's own criterion names ("Live readiness") are not data labels
  await expect(page.locator(".badge", { hasText: /^\s*live\s*$/i })).toHaveCount(0);
  await expect(page.locator(".badge", { hasText: /latest stored/i }).first()).toBeVisible();
}

test("the research journey on real data (spec §39)", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));

  // 1. overview
  await page.goto("/overview");
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
  await expect(page.locator("header.topbar").getByText("Latest stored", { exact: true })).toBeVisible();
  await noForbidden(page);

  // 2. search RELIANCE (Ctrl+K)   3. open the stock
  await page.keyboard.press("Control+k");
  await page.getByRole("combobox", { name: "Search instruments and sectors" }).fill("RELIANCE");
  await expect(page.getByRole("option", { name: /RELIANCE INDUSTRIES/ })).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/stocks\/NSE_EQ%7CINE002A01018/);
  await expect(page.getByText("Latest stored · 1D close")).toBeVisible();

  // 4. chart   5. change timeframe (5m disabled)
  await page.getByRole("tab", { name: "Chart" }).click();
  const chart = page.getByTestId("candle-chart");
  await expect(chart).toBeVisible();
  await expect(chart.locator("canvas").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /5m unavailable/ })).toBeDisabled();
  await page.getByRole("button", { name: "15m timeframe" }).click();
  await expect(page).toHaveURL(/tf=15m/);
  await expect(page.getByTestId("candle-chart").or(page.getByText(/No 15m bars stored/))).toBeVisible();

  // 6. fundamentals   7. corporate actions   (8. stock news)
  await page.getByRole("tab", { name: "Fundamentals" }).click();
  await expect(page.getByRole("table", { name: "Key ratios, company vs sector" })).toBeVisible();
  await page.getByRole("tab", { name: "Corporate actions" }).click();
  await expect(page.getByRole("heading", { name: "What the statuses mean" })).toBeVisible();
  await noForbidden(page);

  // 8. news
  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "News" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "News" })).toBeVisible();
  await expect(page.getByText(/Received /).first()).toBeVisible();

  // 9. data quality (CHAVDA: the real CA_ADJUSTMENT case)
  await page.getByRole("link", { name: "Data Quality" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Data quality" })).toBeVisible();
  await expect(page.getByText("CA ADJUSTMENT").first()).toBeVisible();

  // 10. operations   11. acceptance   12. Stage 3 locked
  await page.getByRole("link", { name: "Operations" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Operations" })).toBeVisible();
  await page.getByRole("link", { name: /Acceptance status/ }).click();
  await expect(page.getByTestId("stage3-lock")).toContainText("Stage 3 Locked");
  await noForbidden(page);

  expect(errors).toEqual([]);
});

test("global: revised labels are withheld, labels are vendor labels", async ({ page }) => {
  await page.goto("/global");
  await expect(page.getByRole("heading", { level: 1, name: "Global markets" })).toBeVisible();
  await page.getByRole("row", { name: /\^N225/ }).first().click();
  await expect(page.getByRole("table", { name: "Label finality" })).toBeVisible();
  const revised = page.getByRole("row").filter({ hasText: "REVISED" }).first();
  if (await revised.count()) await expect(revised).toContainText("WITHHELD");
});

for (const width of [1440, 1280, 1024, 768, 390]) {
  test(`responsive smoke at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    for (const path of ["/overview", "/stocks", "/stocks/NSE_EQ%7CINE002A01018?tab=chart", "/global", "/operations"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      // the page body never scrolls horizontally (tables scroll inside their own containers)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow, `${path} @ ${width}px`).toBeLessThanOrEqual(1);
    }
  });
}
