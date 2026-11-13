// Local QA only. Start the normal FastAPI :8000 and Next.js :3000 first.
import { chromium, expect as baseExpect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const output = new URL("../../tmp/", import.meta.url);
const expect = baseExpect.configure({ timeout: 60000 });
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  channel: process.platform === "win32" ? "msedge" : undefined,
});
const errors = [];
const failedRequests = [];
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(60000);
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("requestfailed", (request) => {
    if (request.failure()?.errorText !== "net::ERR_ABORTED")
      failedRequests.push(`${request.url()} ${request.failure()?.errorText}`);
  });
  await page.goto("http://127.0.0.1:3000");
  await expect(page.getByTestId("widget-metric")).toHaveCount(4);
  await expect(page.getByRole("status")).toContainText("Cobertura parcial no período");
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  const map = page.getByTestId("widget-map_choropleth");
  await map.scrollIntoViewIfNeeded();
  await expect(map.locator(".maplibregl-canvas")).toBeVisible();
  await page.waitForLoadState("networkidle");
  await expect(
    page.getByTestId("widget-donut_chart").locator(".recharts-sector").first(),
  ).toBeVisible();
  // Recharts' initial animation takes 1500 ms; capture the settled visual state.
  await page.waitForTimeout(2200);
  await expect(map.locator(".map-fallback")).toHaveCount(0);
  await map.screenshot({
    path: fileURLToPath(new URL("via-real-map.png", output)),
    animations: "disabled",
  });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({
    path: fileURLToPath(new URL("via-real-dashboard.png", output)),
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Alterar tema", exact: true }).click();
  await page.getByRole("menuitem", { name: "Escuro", exact: true }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.screenshot({
    path: fileURLToPath(new URL("via-real-dashboard-dark.png", output)),
    fullPage: true,
    animations: "disabled",
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Painel", exact: true }).click();
  const fits = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth + 1,
  );
  expect(fits).toBe(true);
  await page.screenshot({
    path: fileURLToPath(new URL("via-real-dashboard-mobile.png", output)),
    fullPage: true,
    animations: "disabled",
  });
  const health = await (await page.request.get("http://127.0.0.1:3000/api/health")).json();
  const geography = await (await page.request.get("http://127.0.0.1:3000/api/geography")).json();
  expect(geography.features).toHaveLength(27);
  expect(errors).toEqual([]);
  expect(failedRequests).toEqual([]);
  const report = {
    health,
    geography_features: geography.features.length,
    metric_widgets: 4,
    mobile_fits: fits,
    errors,
    failed_requests: failedRequests,
  };
  await writeFile(new URL("via-real-ui-qa.json", output), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
} finally {
  await browser.close();
}
