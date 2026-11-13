"use client";
import { useEffect, useMemo, useState } from "react";
import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download } from "lucide-react";
import { DatasetSchema, type Dataset } from "@/lib/contracts.generated";
import { api } from "@/lib/api";
import { number } from "@/lib/utils";
import { Button } from "./ui/button";
export function DataTable({ dataset, fields }: { dataset: Dataset; fields?: string[] }) {
  "use no memo"; // TanStack Table owns mutable getters; exclude it from React Compiler.
  const [page, setPage] = useState(0);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [remote, setRemote] = useState<Dataset | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const pageSize = 10;
  const serverMode = dataset.row_count > dataset.rows.length || dataset.rows.length > pageSize;
  useEffect(() => {
    if (!serverMode) return;
    const controller = new AbortController();
    const params = new URLSearchParams({
      offset: String(page * pageSize),
      limit: String(pageSize),
    });
    if (sorting[0]) {
      params.set("sort_by", sorting[0].id);
      params.set("sort_direction", sorting[0].desc ? "descending" : "ascending");
    }
    // A dataset is immutable; pagination reads its saved query, never reruns the LLM.
    queueMicrotask(() => {
      setLoading(true);
      setError("");
    });
    void api(`/datasets/${dataset.id}?${params}`, DatasetSchema, { signal: controller.signal })
      .then(setRemote)
      .catch((cause: unknown) => {
        if (!controller.signal.aborted)
          setError(cause instanceof Error ? cause.message : "Falha ao abrir página.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [dataset.id, serverMode, page, sorting]);
  const columns = useMemo<ColumnDef<Dataset["rows"][number]>[]>(
    () =>
      dataset.columns
        .filter((column) => !fields?.length || fields.includes(column.key))
        .map((column) => ({
          accessorKey: column.key,
          header: column.label,
          cell: ({ getValue }) => {
            const value: unknown = getValue();
            return typeof value === "number"
              ? `${number.format(value)}${column.format === "percent" ? "%" : ""}`
              : String(value ?? "—");
          },
        })),
    [dataset.columns, fields],
  );
  // eslint-disable-next-line react-hooks/incompatible-library -- Mutable getters stay inside this component, which opts out of React Compiler.
  const table = useReactTable({
    data: (serverMode ? (remote ?? dataset) : dataset).rows.slice(
      0,
      serverMode ? pageSize : undefined,
    ),
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    manualPagination: true,
    manualSorting: serverMode,
    state: { sorting },
    onSortingChange: (updater) => {
      setSorting(updater);
      setPage(0);
    },
    rowCount: dataset.row_count,
  });
  function downloadPage() {
    const visible = serverMode ? (remote ?? dataset) : dataset;
    const keys = visible.columns.filter((column) => !fields?.length || fields.includes(column.key));
    const csvCell = (value: unknown) => {
      const text = String(value ?? "");
      const safe = typeof value === "string" && /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
      return `"${safe.replaceAll('"', '""')}"`;
    };
    const text = [
      keys.map((column) => csvCell(column.label)).join(";"),
      ...visible.rows.map((row) => keys.map((column) => csvCell(row[column.key])).join(";")),
    ].join("\r\n");
    const url = URL.createObjectURL(
      new Blob(["\uFEFF", text], { type: "text/csv;charset=utf-8;" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `via-${dataset.id}-pagina-${page + 1}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="data-table">
      <div className="table-scroll" aria-busy={loading}>
        <table>
          <thead>
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => (
                  <th
                    key={header.id}
                    aria-sort={
                      header.column.getIsSorted() === "asc"
                        ? "ascending"
                        : header.column.getIsSorted() === "desc"
                          ? "descending"
                          : "none"
                    }
                  >
                    <button
                      disabled={dataset.row_count < 2}
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getIsSorted() &&
                        (header.column.getIsSorted() === "desc" ? (
                          <ArrowDown size={12} />
                        ) : (
                          <ArrowUp size={12} />
                        ))}
                    </button>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <div className="table-footer">
        <span>{number.format(dataset.row_count)} registros</span>
        <div>
          <Button
            variant="ghost"
            size="icon"
            onClick={downloadPage}
            disabled={loading}
            aria-label="Baixar CSV da página visível"
          >
            <Download size={15} />
          </Button>
          {serverMode && (
            <>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setPage((value) => value - 1)}
                disabled={page === 0 || loading}
                aria-label="Página anterior"
              >
                <ChevronLeft size={16} />
              </Button>
              <span>
                {page + 1} / {Math.max(1, Math.ceil(dataset.row_count / pageSize))}
              </span>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => setPage((value) => value + 1)}
                disabled={(page + 1) * pageSize >= dataset.row_count || loading}
                aria-label="Próxima página"
              >
                <ChevronRight size={16} />
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
