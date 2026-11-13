import { test, expect } from "@playwright/test";
import { catalog, dataset, session } from "../fixtures";

for (const viewport of [
  { width: 1920, height: 960 },
  { width: 1200, height: 800 },
  { width: 900, height: 720 },
  { width: 390, height: 844 },
]) {
  test(`keeps the assistant visible and leaves space below the last chart at ${viewport.width}px`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    // A saved investigation with several rows reproduces scrolling to the last chart.
    const saved = {
      ...session,
      dashboard: {
        ...session.dashboard,
        widgets: Array.from({ length: 6 }, (_, index) => ({
          id: `chart_${index}`,
          type: "bar_chart",
          title: `Ranking ${index + 1}`,
          description: "Acidentes por rodovia",
          dataset_id: dataset.id,
          x_field: "label",
          y_field: "value",
          sort: "descending",
        })),
      },
      datasets: [dataset],
    };
    await page.route("**/api/**", async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/api/health")
        return route.fulfill({
          json: { status: "ok", data_available: true, llm_configured: true, model: "test" },
        });
      if (path === "/api/catalog") return route.fulfill({ json: catalog });
      if (path === "/api/sessions")
        return route.fulfill({ json: [{ id: saved.id, title: saved.title }] });
      return route.fulfill({ json: saved });
    });
    await page.goto("/");
    const charts = page.getByTestId("widget-bar_chart");
    await expect(charts).toHaveCount(6);
    await page.evaluate(() => window.scrollTo(0, 0));
    const assistant = page.getByRole("complementary", { name: "Investigação com assistente" });
    const composer = page.getByLabel("Pergunte sobre os dados");

    if (viewport.width > 760) {
      const initialBounds = await assistant.boundingBox();
      expect(initialBounds).not.toBeNull();
      for (const position of [0.5, 1, 0]) {
        await page.evaluate((fraction) => {
          window.scrollTo(0, (document.documentElement.scrollHeight - innerHeight) * fraction);
        }, position);
        await expect
          .poll(async () => {
            const bounds = await assistant.boundingBox();
            return bounds && Math.abs(bounds.y - (initialBounds?.y ?? 0)) < 1;
          })
          .toBe(true);
        const bounds = await assistant.boundingBox();
        expect(bounds).not.toBeNull();
        expect(Math.abs((bounds?.y ?? 0) + (bounds?.height ?? 0) - viewport.height)).toBeLessThan(
          1,
        );
        await expect(composer).toBeInViewport({ ratio: 1 });
      }
    }

    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    const lastChart = await charts.last().boundingBox();
    if (!lastChart) throw new Error("Last chart unavailable");
    const bottomBarHeight = viewport.width <= 760 ? 57 : 0;
    expect(
      viewport.height - bottomBarHeight - (lastChart.y + lastChart.height),
    ).toBeGreaterThanOrEqual(24);
    await page.screenshot({ path: `../tmp/via-scroll-${viewport.width}.png` });
  });
}
