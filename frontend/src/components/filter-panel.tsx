"use client";
import { useState } from "react";
import { ChevronDown, SlidersHorizontal } from "lucide-react";
import type { Catalog, Filters } from "@/lib/contracts.generated";
import { emptyFilters } from "@/lib/dashboard";
import { FilterChecklist } from "./filter-checklist";
import { Button } from "./ui/button";
import { CalendarRangeSelect } from "./ui/calendar-range-select";
import { Dialog, DialogContent, DialogTrigger } from "./ui/dialog";

const dimensions = [
  { key: "roads", alias: "road", label: "Rodovia" },
  { key: "ufs", alias: "uf", label: "Estado" },
  { key: "concessions", alias: "concession", label: "Concessionária" },
  { key: "accident_types", alias: "accident_type", label: "Tipo de acidente" },
  { key: "directions", alias: "direction", label: "Sentido" },
  { key: "track_types", alias: "track_type", label: "Tipo de pista" },
  { key: "vehicle_types", alias: "vehicle_type", label: "Tipo de veículo" },
] as const;

const severities = {
  all: "Todos os acidentes",
  with_severe: "Com vítimas graves",
  with_deaths: "Com óbitos",
  with_injuries: "Com feridos",
} satisfies Record<Filters["severity"], string>;

const description =
  "As alterações geram uma nova visão geral. Resultados fixados preservam seu recorte original.";

export function FilterPanel({
  filters,
  catalog,
  disabled,
  onApply,
}: {
  filters: Filters;
  catalog: Catalog | null;
  disabled: boolean;
  onApply: (filters: Filters) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(filters);
  const [error, setError] = useState("");

  function updateField<K extends keyof Filters>(key: K, value: Filters[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (draft.start_date && draft.end_date && draft.start_date >= draft.end_date) {
      setError("A data final deve ser posterior à inicial.");
      return;
    }
    if (draft.km_min != null && draft.km_max != null && draft.km_min >= draft.km_max) {
      setError("O km final deve ser maior que o km inicial.");
      return;
    }
    setOpen(false);
    onApply(draft);
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        setOpen(value);
        if (value) {
          setDraft(filters);
          setError("");
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" disabled={disabled}>
          <SlidersHorizontal size={15} />
          Filtros
        </Button>
      </DialogTrigger>
      <DialogContent title="Refinar o recorte" description={description}>
        <form className="grid gap-5" onSubmit={submit}>
          <p className="text-xs leading-relaxed text-(--muted)">{description}</p>
          <CalendarRangeSelect
            value={draft}
            onChange={(field, value) => {
              updateField(field, value);
              setError("");
            }}
          />
          <div className="grid grid-cols-1 gap-3 min-[480px]:grid-cols-2">
            {dimensions.map(({ key, alias, label }) => (
              <FilterChecklist
                key={key}
                label={label}
                options={catalog?.filters[key] ?? catalog?.filters[alias] ?? []}
                selected={draft[key]}
                onChange={(values) => updateField(key, values)}
              />
            ))}
            <label className="grid gap-1.5">
              <span className="filter-label">Gravidade</span>
              <span className="relative block min-w-0">
                <select
                  className="filter-control appearance-none"
                  value={draft.severity}
                  onChange={(event) =>
                    updateField("severity", event.target.value as Filters["severity"])
                  }
                >
                  {Object.entries(severities).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                <ChevronDown
                  aria-hidden="true"
                  size={15}
                  className="pointer-events-none absolute end-3 top-1/2 -translate-y-1/2 text-(--muted)"
                />
              </span>
            </label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {(
              [
                ["km_min", "Km inicial"],
                ["km_max", "Km final"],
              ] as const
            ).map(([field, label]) => (
              <label key={field} className="grid min-w-0 gap-1.5">
                <span className="filter-label">{label}</span>
                <input
                  className="filter-control tabular-nums"
                  type="number"
                  min="0"
                  step="0.001"
                  value={draft[field] ?? ""}
                  onChange={(event) => {
                    updateField(field, event.target.value ? event.target.valueAsNumber : null);
                    setError("");
                  }}
                />
              </label>
            ))}
          </div>
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
          <div className="flex items-center justify-between gap-2 border-t border-(--border) pt-4">
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                setDraft(emptyFilters());
                setError("");
              }}
            >
              Limpar filtros
            </Button>
            <Button type="submit">Aplicar recorte</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
