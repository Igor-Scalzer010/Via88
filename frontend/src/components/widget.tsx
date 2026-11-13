"use client";
import dynamic from "next/dynamic";
import { useCallback, useState } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import {
  AlertTriangle,
  Check,
  ExternalLink,
  GripVertical,
  Info,
  Pin,
  Table2,
  Trash2,
} from "lucide-react";
import type { Dataset, Widget } from "@/lib/contracts.generated";
import { formatDate, number } from "@/lib/utils";
import { DataTable } from "./data-table";
import { Button } from "./ui/button";
import { Dialog, DialogContent, DialogTrigger } from "./ui/dialog";
const GeoMap = dynamic(() => import("./geo-map"), {
  ssr: false,
  loading: () => <div className="chart-skeleton" />,
});
const colors = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--chart-6)",
];
export function Sources({ dataset }: { dataset: Dataset }) {
  const evidence = dataset.evidence;
  return (
    <div className="sources">
      <span className="eyebrow">EVIDÊNCIA DA ANÁLISE</span>
      <h3>{dataset.title}</h3>
      <dl>
        <div>
          <dt>Fonte</dt>
          <dd>
            <a href={evidence.source_url} target="_blank" rel="noreferrer">
              {evidence.source} <ExternalLink size={12} />
            </a>
          </dd>
        </div>
        <div>
          <dt>Período consultado</dt>
          <dd>
            {formatDate(evidence.start_date)} a {formatDate(evidence.end_date)} (fim exclusivo)
          </dd>
        </div>
        <div>
          <dt>Definição</dt>
          <dd>{evidence.definition}</dd>
        </div>
        <div>
          <dt>Registros encontrados</dt>
          <dd>{number.format(evidence.matched_rows)}</dd>
        </div>
        <div>
          <dt>Recursos com registros</dt>
          <dd>
            {evidence.resources_with_records} de {evidence.resources_total}
          </dd>
        </div>
        <div>
          <dt>Versão da base</dt>
          <dd className="mono">{evidence.snapshot_id}</dd>
        </div>
      </dl>
      <h4>Recorte aplicado</h4>
      <pre>{JSON.stringify(dataset.query, null, 2)}</pre>
      {evidence.warnings.map((warning) => (
        <p className="notice" key={warning}>
          {warning}
        </p>
      ))}
      <p className="muted">
        O conjunto abrange rodovias federais concedidas acompanhadas pela ANTT. Contagens não
        representam taxas de risco sem dados de exposição ao tráfego.
      </p>
    </div>
  );
}
export function WidgetCard({
  widget,
  dataset,
  pinned,
  locked,
  onPin,
  onRemove,
  onFilter,
}: {
  widget: Widget;
  dataset: Dataset;
  pinned: boolean;
  locked: boolean;
  onPin: () => void;
  onRemove: () => void;
  onFilter: (dimension: string, key: string) => void;
}) {
  const [table, setTable] = useState(false);
  const selectUF = useCallback((uf: string) => onFilter("uf", uf), [onFilter]);
  const metric = widget.type === "metric";
  const partialCoverage = dataset.evidence.coverage === "partial";
  const sourceLabel = /sint[eé]tic/i.test(dataset.evidence.source) ? "Demonstração" : "Dados ANTT";
  const seriesField = "y_field" in widget ? widget.y_field : "value";
  const seriesLabel =
    dataset.columns.find((column) => column.key === seriesField)?.label ?? dataset.title;
  const values = metric
    ? dataset.rows
        .map((row) => row[widget.field])
        .filter((value): value is number => typeof value === "number")
    : [];
  const value = metric
    ? widget.aggregation === "count"
      ? dataset.row_count
      : values.length
        ? values.reduce((total, current) => total + current, 0) /
          (widget.aggregation === "avg" ? values.length : 1)
        : null
    : null;
  const data = [...dataset.rows];
  if ("sort" in widget && widget.sort)
    data.sort(
      (a, b) =>
        (Number(a[widget.y_field]) - Number(b[widget.y_field])) *
        (widget.sort === "descending" ? -1 : 1),
    );
  const tooltip = {
    contentStyle: {
      borderRadius: 12,
      background: "var(--card)",
      border: "1px solid var(--border)",
      fontSize: 12,
    },
    formatter: (value: unknown) => number.format(Number(value)),
  };
  return (
    <article
      className={`widget-card ${metric ? "metric-card" : ""} ${pinned ? "is-pinned" : ""}`}
      data-testid={`widget-${widget.type}`}
    >
      <header className="widget-header">
        <div className="widget-title">
          {!locked && <GripVertical size={15} className="drag-handle" aria-hidden="true" />}
          <h2>{widget.title}</h2>
        </div>
        <div className="widget-actions">
          <Dialog>
            <DialogTrigger asChild>
              <Button variant="ghost" size="icon" aria-label={`Ver fontes: ${widget.title}`}>
                <Info size={14} />
              </Button>
            </DialogTrigger>
            <DialogContent title="Fontes e metodologia">
              <Sources dataset={dataset} />
            </DialogContent>
          </Dialog>
          {!metric && (
            <Button
              variant="ghost"
              size="icon"
              aria-label={table ? "Exibir gráfico" : "Exibir tabela"}
              onClick={() => setTable(!table)}
              aria-pressed={table}
            >
              <Table2 size={14} />
            </Button>
          )}
          <Button
            variant="ghost"
            size="icon"
            aria-label={pinned ? `Desafixar ${widget.title}` : `Fixar resultado ${widget.title}`}
            onClick={onPin}
            aria-pressed={pinned}
          >
            <Pin size={14} className={pinned ? "pinned-icon" : ""} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={onRemove}
            aria-label={`Remover ${widget.title}`}
          >
            <Trash2 size={14} />
          </Button>
        </div>
      </header>
      {metric ? (
        <div className="metric-body">
          <strong>{value === null ? "Sem informação" : number.format(value)}</strong>
          <p>{widget.description || dataset.evidence.definition}</p>
          <span className={`metric-footer ${partialCoverage ? "coverage-partial" : ""}`}>
            {partialCoverage ? <AlertTriangle size={12} /> : <Check size={12} />}
            {partialCoverage ? "Cobertura parcial" : sourceLabel}
            {pinned ? " · Fixado" : ""}
          </span>
        </div>
      ) : (
        <>
          <p className="widget-description">{widget.description || dataset.evidence.definition}</p>
          <div className="widget-visual">
            {table || widget.type === "table" ? (
              <DataTable
                key={dataset.id}
                dataset={dataset}
                fields={widget.type === "table" ? widget.columns : undefined}
              />
            ) : widget.type === "map_choropleth" ? (
              <GeoMap
                dataset={dataset}
                xField={widget.x_field}
                yField={widget.y_field}
                onSelect={selectUF}
              />
            ) : widget.type === "donut_chart" ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={data}
                    dataKey={widget.y_field}
                    nameKey={widget.x_field}
                    innerRadius="57%"
                    outerRadius="82%"
                    paddingAngle={3}
                    stroke="none"
                  >
                    {data.map((_, i) => (
                      <Cell key={i} fill={colors[i % colors.length]} />
                    ))}
                  </Pie>
                  <Tooltip {...tooltip} />
                </PieChart>
              </ResponsiveContainer>
            ) : widget.type === "bar_chart" ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={data}
                  layout="vertical"
                  margin={{ left: 0, right: 30, bottom: 0, top: 4 }}
                >
                  <CartesianGrid stroke="var(--border)" strokeDasharray="3 5" horizontal={false} />
                  <XAxis
                    type="number"
                    tickFormatter={(value: number) => number.format(value)}
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: "var(--muted)", fontSize: 11 }}
                  />
                  <YAxis
                    type="category"
                    dataKey={widget.x_field}
                    width={105}
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: "var(--muted)", fontSize: 11 }}
                  />
                  <Tooltip {...tooltip} cursor={{ fill: "var(--chart-hover)" }} />
                  <Bar
                    dataKey={widget.y_field}
                    name={seriesLabel}
                    fill="var(--chart-1)"
                    radius={[0, 5, 5, 0]}
                    maxBarSize={27}
                    onClick={(_, index) => {
                      const row = data[index];
                      if (row)
                        onFilter(dataset.query.group_by, String(row.key ?? row[widget.x_field]));
                    }}
                  />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                {widget.type === "area_chart" ? (
                  <AreaChart data={data} margin={{ left: 0, right: 18, top: 12, bottom: 0 }}>
                    <defs>
                      <linearGradient id={`fill-${widget.id}`} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.24} />
                        <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0.01} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="var(--border)" strokeDasharray="3 5" vertical={false} />
                    <XAxis
                      dataKey={widget.x_field}
                      minTickGap={30}
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: "var(--muted)", fontSize: 11 }}
                    />
                    <YAxis
                      width={48}
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: "var(--muted)", fontSize: 11 }}
                    />
                    <Tooltip {...tooltip} />
                    <Area
                      type="monotone"
                      dataKey={widget.y_field}
                      name={seriesLabel}
                      stroke="var(--chart-1)"
                      strokeWidth={2.5}
                      fill={`url(#fill-${widget.id})`}
                    />
                  </AreaChart>
                ) : (
                  <LineChart data={data} margin={{ left: 0, right: 18, top: 12, bottom: 0 }}>
                    <CartesianGrid stroke="var(--border)" strokeDasharray="3 5" vertical={false} />
                    <XAxis
                      dataKey={widget.x_field}
                      minTickGap={30}
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: "var(--muted)", fontSize: 11 }}
                    />
                    <YAxis
                      width={48}
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: "var(--muted)", fontSize: 11 }}
                    />
                    <Tooltip {...tooltip} />
                    <Line
                      type="monotone"
                      dataKey={widget.y_field}
                      name={seriesLabel}
                      stroke="var(--chart-1)"
                      strokeWidth={2.5}
                      dot={false}
                      activeDot={{ r: 5 }}
                    />
                  </LineChart>
                )}
              </ResponsiveContainer>
            )}
          </div>
          <footer className="widget-footer">
            <span>
              {formatDate(dataset.evidence.start_date)} — {formatDate(dataset.evidence.end_date)}*
            </span>
            <span className="footer-badges">
              {partialCoverage && (
                <span className="coverage-partial">
                  <AlertTriangle size={10} />
                  Cobertura parcial
                </span>
              )}
              <span>{pinned ? "Fixado · " : ""}* fim exclusivo</span>
            </span>
          </footer>
        </>
      )}
    </article>
  );
}
