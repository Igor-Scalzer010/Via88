import { describe, expect, it } from "vitest";
import { applyAnalysis, emptyDashboard } from "../../src/lib/dashboard";
import { result } from "../fixtures";
describe("evidence-backed atomic dashboard", () => {
  it("applies valid predefined widgets sharing an immutable dataset", () => {
    const applied = applyAnalysis(emptyDashboard(), [], result);
    expect(applied.dashboard.widgets).toHaveLength(2);
    expect(applied.datasets).toHaveLength(1);
  });
  it("rejects a whole batch if one widget references a missing dataset", () => {
    const original = emptyDashboard();
    const invalid = {
      ...result,
      dashboard_actions: [
        ...result.dashboard_actions,
        {
          action: "add",
          widget: {
            id: "bad",
            type: "metric",
            title: "Inválido",
            dataset_id: "missing",
            field: "value",
            aggregation: "sum",
          },
        },
      ],
    };
    expect(() => applyAnalysis(original, [], invalid)).toThrow("verificável");
    expect(original.widgets).toEqual([]);
  });
  it("rejects arbitrary React and invalid columns", () => {
    expect(() =>
      applyAnalysis(emptyDashboard(), [], {
        ...result,
        dashboard_actions: [
          { action: "add", widget: { id: "unsafe", type: "react", code: "alert(1)" } },
        ],
      }),
    ).toThrow();
    const widget = { ...result.dashboard_actions[0] };
    if (widget.action !== "remove" && widget.widget.type === "metric")
      widget.widget = { ...widget.widget, field: "unavailable" };
    expect(() =>
      applyAnalysis(emptyDashboard(), [], { ...result, dashboard_actions: [widget] }),
    ).toThrow("campo");
  });
  it("rejects attempted changes to pinned snapshots atomically", () => {
    const first = applyAnalysis(emptyDashboard(), [], result);
    first.dashboard.pinned_widget_ids = ["metric_test"];
    expect(() =>
      applyAnalysis(first.dashboard, first.datasets, {
        ...result,
        analysis_id: "next",
        datasets: [],
        dashboard_actions: [{ action: "remove", widget_id: "metric_test" }],
      }),
    ).toThrow("fixado");
    expect(first.dashboard.widgets.some((widget) => widget.id === "metric_test")).toBe(true);
  });
  it("rejects mutation of an existing dataset id", () => {
    const first = applyAnalysis(emptyDashboard(), [], result);
    expect(() =>
      applyAnalysis(first.dashboard, first.datasets, {
        ...result,
        datasets: [{ ...result.datasets[0], rows: [] }],
      }),
    ).toThrow("imutável");
  });
  it("rejects numeric strings even when a column claims to be numeric", () => {
    expect(() =>
      applyAnalysis(emptyDashboard(), [], {
        ...result,
        datasets: [
          { ...result.datasets[0], rows: [{ key: "BR-101", label: "BR-101", value: "12" }] },
        ],
      }),
    ).toThrow("numérico");
  });
  it("rejects dashboard mutations in an insufficient-data response", () => {
    expect(() =>
      applyAnalysis(emptyDashboard(), [], { ...result, status: "insufficient_data" }),
    ).toThrow("não concluída");
  });
});
