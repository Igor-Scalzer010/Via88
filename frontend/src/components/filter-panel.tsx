"use client";
import { useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import type { Catalog, Filters } from "@/lib/contracts.generated";
import { emptyFilters } from "@/lib/dashboard";
import { Button } from "./ui/button";
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
      <DialogContent title="Refinar o recorte">
        <form className="filters-form" onSubmit={submit}>
          <p className="muted">
            As alterações geram uma nova visão geral. Resultados fixados preservam seu recorte
            original.
          </p>
          <div className="form-row">
            <label>
              Data inicial
              <input
                type="date"
                value={draft.start_date ?? ""}
                onChange={(event) => setDraft({ ...draft, start_date: event.target.value || null })}
              />
            </label>
            <label>
              Data final (exclusiva)
              <input
                type="date"
                value={draft.end_date ?? ""}
                onChange={(event) => setDraft({ ...draft, end_date: event.target.value || null })}
              />
            </label>
          </div>
          {dimensions.map(({ key, alias, label }) => (
            <label key={key}>
              {label}
              <select
                multiple
                value={draft[key]}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    [key]: Array.from(event.target.selectedOptions, (option) => option.value),
                  })
                }
              >
                {(catalog?.filters[key] ?? catalog?.filters[alias] ?? []).map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          ))}
          <label>
            Gravidade
            <select
              value={draft.severity}
              onChange={(event) =>
                setDraft({ ...draft, severity: event.target.value as Filters["severity"] })
              }
            >
              <option value="all">Todos os acidentes</option>
              <option value="with_severe">Com vítimas graves</option>
              <option value="with_deaths">Com óbitos</option>
              <option value="with_injuries">Com feridos</option>
            </select>
          </label>
          <div className="form-row">
            <label>
              Km inicial
              <input
                type="number"
                min="0"
                step="0.001"
                value={draft.km_min ?? ""}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    km_min: event.target.value ? Number(event.target.value) : null,
                  })
                }
              />
            </label>
            <label>
              Km final
              <input
                type="number"
                min="0"
                step="0.001"
                value={draft.km_max ?? ""}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    km_max: event.target.value ? Number(event.target.value) : null,
                  })
                }
              />
            </label>
          </div>
          <p className="muted small">
            Para selecionar mais de um item, use Ctrl ou ⌘. Dados ausentes não são tratados como
            zero.
          </p>
          {error && (
            <p className="error-text" role="alert">
              {error}
            </p>
          )}
          <div className="form-actions">
            <Button type="button" variant="ghost" onClick={() => setDraft(emptyFilters())}>
              Limpar filtros
            </Button>
            <Button type="submit">Aplicar recorte</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
