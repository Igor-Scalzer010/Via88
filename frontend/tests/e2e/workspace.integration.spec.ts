import { test, expect } from "@playwright/test";
import { SessionSchema } from "../../src/lib/contracts.generated";
test("real FastAPI, DuckDB and LangGraph retain the exact follow-up cohort and pinned results", async ({
  page,
}) => {
  await page.goto("/");
  // The first real proxy request includes a cold Next.js route compilation.
  await expect(page.getByTestId("widget-metric").first()).toBeVisible({ timeout: 45000 });
  await page.screenshot({ path: "../tmp/via-overview-desktop.png", fullPage: true });
  await page
    .getByLabel("Pergunte sobre os dados")
    .fill("Quais foram as cinco rodovias com mais acidentes nos últimos três anos?");
  await page.getByRole("button", { name: "Enviar pergunta", exact: true }).click();
  await expect(page.getByTestId("widget-bar_chart")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Enviar pergunta", exact: true })).toBeVisible();
  const id = await page.evaluate(() => localStorage.getItem("via-session"));
  const before = SessionSchema.parse(await (await page.request.get(`/api/sessions/${id}`)).json());
  const ranking = before.latest_analysis?.datasets[0];
  expect(ranking?.query.group_by).toBe("road_uf");
  const keys = new Set(ranking?.rows.map((row) => String(row.key)));
  const pinnedWidget = before.dashboard.widgets.find((widget) => widget.type === "bar_chart");
  expect(pinnedWidget).toBeDefined();
  await page
    .getByTestId("widget-bar_chart")
    .getByRole("button", { name: /^Fixar resultado / })
    .click();
  await expect(
    page.getByTestId("widget-bar_chart").getByRole("button", { name: /^Desafixar / }),
  ).toBeVisible();
  const card = page.getByTestId("widget-bar_chart");
  await card.hover();
  const handle = await card.locator(".drag-handle").boundingBox();
  if (!handle) throw new Error("Drag handle unavailable");
  await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
  await page.mouse.down();
  await page.mouse.move(handle.x + handle.width / 2 + 90, handle.y + handle.height / 2 + 70, {
    steps: 12,
  });
  await page.mouse.up();
  const readLayout = async () =>
    SessionSchema.parse(
      await (await page.request.get(`/api/sessions/${id}`)).json(),
    ).dashboard.layouts.lg?.find((item) => item.i === pinnedWidget?.id);
  await expect.poll(readLayout).toBeDefined();
  const moved = await readLayout();
  expect((moved?.x ?? 0) > 0 || (moved?.y ?? 0) > 0).toBe(true);
  const item = page.locator(".react-grid-item").filter({ has: card });
  const resize = await item.locator(".react-resizable-handle-se").boundingBox();
  if (!resize) throw new Error("Resize handle unavailable");
  await page.mouse.move(resize.x + resize.width / 2, resize.y + resize.height / 2);
  await page.mouse.down();
  await page.mouse.move(resize.x + resize.width / 2 + 85, resize.y + resize.height / 2 + 65, {
    steps: 12,
  });
  await page.mouse.up();
  await expect
    .poll(async () => {
      const value = await readLayout();
      return value?.w !== moved?.w || value?.h !== moved?.h;
    })
    .toBe(true);
  const resized = await readLayout();
  await page
    .getByLabel("Pergunte sobre os dados")
    .fill("Desses trechos, quais tiveram mais acidentes com vítimas graves?");
  await page.getByRole("button", { name: "Enviar pergunta", exact: true }).click();
  await expect(page.getByTestId("widget-bar_chart")).toHaveCount(2);
  const after = SessionSchema.parse(await (await page.request.get(`/api/sessions/${id}`)).json());
  const followup = after.latest_analysis?.datasets[0];
  expect(followup?.query.metric).toBe("accidents_with_severe");
  expect(followup?.query.cohort?.keys.slice().sort()).toEqual([...keys].sort());
  expect(followup?.rows.every((row) => keys.has(String(row.key)))).toBe(true);
  expect(after.dashboard.pinned_widget_ids).toContain(pinnedWidget?.id);
  expect(after.datasets.find((dataset) => dataset.id === pinnedWidget?.dataset_id)).toEqual(
    before.datasets.find((dataset) => dataset.id === pinnedWidget?.dataset_id),
  );
  await page.reload();
  await expect(page.getByTestId("widget-bar_chart")).toHaveCount(2);
  await expect(page.getByRole("button", { name: /^Desafixar / })).toHaveCount(1);
  expect(await readLayout()).toEqual(resized);
  await page.screenshot({ path: "../tmp/via-dashboard-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Painel", exact: true }).click();
  await expect(page.getByTestId("widget-bar_chart").first()).toBeVisible();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1),
  ).toBe(true);
  await page.screenshot({ path: "../tmp/via-dashboard-mobile.png", fullPage: true });
});
