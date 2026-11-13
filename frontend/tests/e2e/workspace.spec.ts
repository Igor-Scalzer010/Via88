import { test, expect } from "@playwright/test";
import { catalog, result, session } from "../fixtures";
test("opens a new empty session with null active filters before any import", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/health")
      return route.fulfill({
        json: { status: "ok", data_available: false, llm_configured: false, model: null },
      });
    if (path === "/api/catalog")
      return route.fulfill({
        json: {
          ...catalog,
          available: false,
          snapshot_id: null,
          min_date: null,
          max_date: null,
          total_accidents: 0,
          resources: 0,
          filters: {},
        },
      });
    if (path === "/api/sessions")
      return route.fulfill({
        json: route.request().method() === "POST" ? { ...session, active_filters: null } : [],
      });
    return route.fulfill({ status: 404, json: { detail: "not found" } });
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Vamos trazer os dados para a estrada." }),
  ).toBeVisible();
  await expect(page.getByLabel("Pergunte sobre os dados")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Filtros", exact: true })).toBeDisabled();
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  expect(errors).toEqual([]);
});
test("investigates with context, preserves a pinned snapshot and renders evidence", async ({
  page,
}) => {
  let saved = { ...session };
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    if (path === "/api/health")
      return route.fulfill({
        json: { status: "ok", data_available: true, llm_configured: true, model: "test-model" },
      });
    if (path === "/api/catalog") return route.fulfill({ json: catalog });
    if (path === "/api/sessions")
      return route.fulfill({
        json: route.request().method() === "POST" ? saved : [{ id: saved.id, title: saved.title }],
      });
    if (path.endsWith("/overview")) return route.fulfill({ json: result });
    if (path.endsWith("/dashboard")) {
      saved = { ...saved, dashboard: route.request().postDataJSON() };
      return route.fulfill({ json: saved.dashboard });
    }
    if (path === "/api/chat") {
      const body = route.request().postDataJSON() as {
        message: string;
        session_id: string;
        request_id: string;
      };
      const next = {
        ...result,
        request_id: body.request_id,
        analysis_id: "analysis_followup",
        answer: "Dessas rodovias, BR-101 teve mais acidentes com vítimas graves.",
        datasets: [],
        dashboard_actions: [
          {
            action: "update",
            widget: {
              id: "chart_test",
              type: "bar_chart",
              title: "Acidentes graves nessas rodovias",
              description: "Mesma coorte",
              dataset_id: result.datasets[0].id,
              x_field: "label",
              y_field: "value",
              sort: "descending",
            },
          },
        ],
      };
      return route.fulfill({
        contentType: "text/event-stream",
        body: `event: stage\ndata: {"run_id":"run_test","stage":"query","label":"Consultando dados"}\n\nevent: completed\ndata: ${JSON.stringify(next)}\n\n`,
      });
    }
    if (path.startsWith("/api/sessions/")) return route.fulfill({ json: saved });
    return route.fulfill({ status: 404, json: { detail: "missing" } });
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Total de acidentes", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Fixar resultado Total de acidentes", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Desafixar Total de acidentes", exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Pergunte sobre os dados")
    .fill("Dessas rodovias, quais tiveram mais acidentes com vítimas graves?");
  await page.getByRole("button", { name: "Enviar pergunta", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Acidentes graves nessas rodovias" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Desafixar Total de acidentes", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Ver fontes: Acidentes graves nessas rodovias" }).click();
  await expect(page.getByText("snapshot_test", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Fechar", exact: true }).click();
  await page.getByRole("button", { name: "Exibir tabela", exact: true }).click();
  await expect(page.getByRole("cell", { name: "BR-101", exact: true }).first()).toBeVisible();
});
test("keeps deterministic exploration available without an LLM key", async ({ page }) => {
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/health")
      return route.fulfill({
        json: { status: "ok", data_available: true, llm_configured: false, model: null },
      });
    if (path === "/api/catalog") return route.fulfill({ json: catalog });
    if (path === "/api/sessions")
      return route.fulfill({ json: [{ id: session.id, title: session.title }] });
    if (path.endsWith("/overview")) return route.fulfill({ json: result });
    return route.fulfill({ json: session });
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Total de acidentes", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("Pergunte sobre os dados")).toBeDisabled();
  await expect(page.getByRole("button", { name: "Filtros", exact: true })).toBeEnabled();
});
