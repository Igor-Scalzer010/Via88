import { render, screen, fireEvent } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { WidgetCard } from "../../src/components/widget";
import { dataset, result } from "../fixtures";
it("makes partial coverage visible in metrics and table footers", () => {
  const action = result.dashboard_actions[0];
  if (action.action === "remove") throw new Error("fixture");
  const partial = { ...dataset, evidence: { ...dataset.evidence, coverage: "partial" as const } };
  const props = {
    dataset: partial,
    pinned: false,
    locked: true,
    onPin: vi.fn(),
    onRemove: vi.fn(),
    onFilter: vi.fn(),
  };
  const { rerender } = render(<WidgetCard {...props} widget={action.widget} />);
  expect(screen.getByText("Cobertura parcial")).toBeInTheDocument();
  expect(screen.queryByText("Dados ANTT")).not.toBeInTheDocument();
  rerender(
    <WidgetCard
      {...props}
      widget={{
        type: "table",
        id: "table_partial",
        title: "Tabela parcial",
        dataset_id: dataset.id,
        description: "",
        columns: [],
      }}
    />,
  );
  expect(screen.getByText("Cobertura parcial")).toBeInTheDocument();
  expect(screen.getByText("* fim exclusivo")).toBeInTheDocument();
});
it("renders metrics from query results and exposes source evidence", () => {
  const action = result.dashboard_actions[0];
  if (action.action === "remove") throw new Error("fixture");
  const pin = vi.fn();
  render(
    <WidgetCard
      widget={action.widget}
      dataset={dataset}
      pinned={false}
      locked={true}
      onPin={pin}
      onRemove={vi.fn()}
      onFilter={vi.fn()}
    />,
  );
  expect(screen.getByText("20")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Fixar resultado Total de acidentes" }));
  expect(pin).toHaveBeenCalledOnce();
  fireEvent.click(screen.getByRole("button", { name: "Ver fontes: Total de acidentes" }));
  expect(screen.getByText("snapshot_test")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /ANTT/ })).toHaveAttribute(
    "href",
    "https://dados.antt.gov.br/dataset/acidentes-rodovias",
  );
});
it("distinguishes unknown metric values from an observed zero", () => {
  const action = result.dashboard_actions[0];
  if (action.action === "remove") throw new Error("fixture");
  const { rerender } = render(
    <WidgetCard
      widget={action.widget}
      dataset={{ ...dataset, rows: [{ key: "total", label: "Total", value: null }] }}
      pinned={false}
      locked={true}
      onPin={vi.fn()}
      onRemove={vi.fn()}
      onFilter={vi.fn()}
    />,
  );
  expect(screen.getByText("Sem informação")).toBeInTheDocument();
  rerender(
    <WidgetCard
      widget={action.widget}
      dataset={{ ...dataset, rows: [{ key: "total", label: "Total", value: 0 }] }}
      pinned={false}
      locked={true}
      onPin={vi.fn()}
      onRemove={vi.fn()}
      onFilter={vi.fn()}
    />,
  );
  expect(screen.getByText("0")).toBeInTheDocument();
});
