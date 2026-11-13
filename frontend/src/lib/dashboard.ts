import {
  DashboardSchema,
  ResponseSchema,
  type Dashboard,
  type Dataset,
  type Response,
  type Widget,
  type Filters,
} from "./contracts.generated";
export const emptyFilters = (): Filters => ({
  start_date: null,
  end_date: null,
  roads: [],
  ufs: [],
  concessions: [],
  accident_types: [],
  directions: [],
  track_types: [],
  vehicle_types: [],
  severity: "all",
  km_min: null,
  km_max: null,
});
export const emptyDashboard = (): Dashboard => ({
  widgets: [],
  layouts: {},
  pinned_widget_ids: [],
});
export function validateWidget(widget: Widget, dataset: Dataset): void {
  const columns = new Set(dataset.columns.map((column) => column.key));
  const fields =
    widget.type === "metric"
      ? [widget.field]
      : widget.type === "table"
        ? widget.columns
        : [widget.x_field, widget.y_field];
  if (fields.some((field) => !columns.has(field)))
    throw new Error(`O widget ${widget.title} referencia um campo indisponível.`);
  const numericField =
    widget.type === "metric" ? widget.field : widget.type === "table" ? null : widget.y_field;
  if (
    numericField &&
    (dataset.columns.find((column) => column.key === numericField)?.data_type !== "number" ||
      dataset.rows.some(
        (row) => row[numericField] !== null && typeof row[numericField] !== "number",
      ))
  )
    throw new Error("A visualização exige um campo numérico válido.");
  if (widget.type === "map_choropleth" && dataset.query.group_by !== "uf")
    throw new Error("O mapa exige uma consulta agrupada por UF.");
}
export function validateDashboard(dashboard: Dashboard, datasets: Dataset[]): void {
  const ids = new Set(dashboard.widgets.map((widget) => widget.id));
  if (
    ids.size !== dashboard.widgets.length ||
    new Set(datasets.map((dataset) => dataset.id)).size !== datasets.length
  )
    throw new Error("Identificadores duplicados no painel.");
  if (
    dashboard.pinned_widget_ids.some((id) => !ids.has(id)) ||
    new Set(dashboard.pinned_widget_ids).size !== dashboard.pinned_widget_ids.length
  )
    throw new Error("Resultado fixado inexistente ou duplicado.");
  for (const items of Object.values(dashboard.layouts)) {
    if (
      new Set(items.map((item) => item.i)).size !== items.length ||
      items.some((item) => !ids.has(item.i) || item.x + item.w > 12)
    )
      throw new Error("O layout contém uma posição inválida.");
  }
  for (const widget of dashboard.widgets) {
    const dataset = datasets.find((item) => item.id === widget.dataset_id);
    if (!dataset) throw new Error("Resultado do painel indisponível.");
    validateWidget(widget, dataset);
  }
}
/** Validate the entire batch before committing it; never leave a half-applied analysis. */
export function applyAnalysis(
  dashboard: Dashboard,
  datasets: Dataset[],
  input: unknown,
): { dashboard: Dashboard; datasets: Dataset[]; response: Response } {
  const response = ResponseSchema.parse(input);
  if (response.status !== "complete" && response.dashboard_actions.length)
    throw new Error("Uma análise não concluída não pode alterar o painel.");
  if (new Set(response.datasets.map((dataset) => dataset.id)).size !== response.datasets.length)
    throw new Error("Identificadores de resultados duplicados.");
  const byId = new Map(datasets.map((dataset) => [dataset.id, dataset]));
  for (const dataset of response.datasets) {
    const existing = byId.get(dataset.id);
    if (existing && JSON.stringify(existing) !== JSON.stringify(dataset))
      throw new Error("Um resultado imutável foi alterado pelo servidor.");
    byId.set(dataset.id, dataset);
  }
  const widgets = new Map(dashboard.widgets.map((widget) => [widget.id, widget]));
  const pinned = new Set(dashboard.pinned_widget_ids);
  const changed = new Set<string>();
  for (const action of response.dashboard_actions) {
    const id = action.action === "remove" ? action.widget_id : action.widget.id;
    if (changed.has(id))
      throw new Error("Uma análise contém ações conflitantes para a mesma visualização.");
    changed.add(id);
    if (pinned.has(id)) throw new Error("Uma análise não pode alterar um resultado fixado.");
    if (action.action === "remove") widgets.delete(id);
    else {
      const dataset = byId.get(action.widget.dataset_id);
      if (!dataset) throw new Error("A visualização não contém um resultado verificável.");
      validateWidget(action.widget, dataset);
      widgets.set(id, action.widget);
    }
  }
  const ids = new Set(widgets.keys());
  const layouts = Object.fromEntries(
    Object.entries(dashboard.layouts).map(([key, items]) => [
      key,
      items.filter((item) => ids.has(item.i)),
    ]),
  );
  const next = DashboardSchema.parse({ ...dashboard, widgets: [...widgets.values()], layouts });
  validateDashboard(next, [...byId.values()]);
  return { response, datasets: [...byId.values()], dashboard: next };
}
