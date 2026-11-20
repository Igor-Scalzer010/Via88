"use client";

import { useId, useState } from "react";
import { Check, ChevronDown, Search } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "./ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "./ui/popover";

function searchKey(value: string) {
  return value.toLocaleLowerCase("pt-BR").normalize("NFD").replace(/\p{M}/gu, "");
}

export function FilterChecklist({
  label,
  options,
  selected,
  onChange,
}: {
  label: string;
  options: readonly string[];
  selected: readonly string[];
  onChange: (values: string[]) => void;
}) {
  const [search, setSearch] = useState("");
  const labelId = useId();
  const valueId = useId();
  const values = [...new Set([...options, ...selected])];
  const query = searchKey(search.trim());
  const visible = query ? values.filter((value) => searchKey(value).includes(query)) : values;

  return (
    <div className="grid min-w-0 gap-1.5">
      <span id={labelId} className="filter-label">
        {label}
      </span>
      <Popover onOpenChange={() => setSearch("")}>
        <PopoverTrigger
          className="filter-control"
          aria-labelledby={`${labelId} ${valueId}`}
          disabled={!values.length}
        >
          <span
            id={valueId}
            className={cn("min-w-0 flex-1 truncate", !selected.length && "text-(--muted)")}
          >
            {selected.length === 1 && selected[0]}
            {selected.length > 1 && `${selected.length} selecionados`}
            {!selected.length && (values.length ? "Todos" : "Sem opções")}
          </span>
          <ChevronDown aria-hidden="true" size={15} className="shrink-0 text-(--muted)" />
        </PopoverTrigger>
        <PopoverContent
          className="flex w-[max(14rem,var(--radix-popover-trigger-width))] max-h-[min(23rem,var(--radix-popover-content-available-height))] flex-col overflow-hidden"
          aria-labelledby={labelId}
        >
          {values.length > 7 && (
            <div className="relative shrink-0 border-b border-(--border) p-2">
              <Search
                aria-hidden="true"
                size={15}
                className="pointer-events-none absolute start-5 top-1/2 -translate-y-1/2 text-(--muted)"
              />
              <input
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Buscar opção"
                aria-label={`Buscar opção em ${label.toLocaleLowerCase("pt-BR")}`}
                className="w-full rounded-lg bg-(--background) py-2 pe-3 ps-9 text-xs"
              />
            </div>
          )}
          <div className="min-h-0 overflow-y-auto overscroll-contain p-1.5">
            {visible.map((value) => {
              const checked = selected.includes(value);
              return (
                <label
                  key={value}
                  className="flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-2 text-xs leading-5 hover:bg-(--accent-light) has-checked:bg-(--accent-light)"
                >
                  <span className="relative grid size-4 shrink-0 place-items-center">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(event) =>
                        onChange(
                          event.target.checked
                            ? [...selected, value]
                            : selected.filter((item) => item !== value),
                        )
                      }
                      className="peer size-4 cursor-pointer appearance-none rounded border border-(--muted) checked:border-(--accent) checked:bg-(--accent)"
                    />
                    <Check
                      aria-hidden="true"
                      size={12}
                      strokeWidth={3}
                      className="pointer-events-none absolute hidden text-(--background) peer-checked:block"
                    />
                  </span>
                  <span className="min-w-0 wrap-anywhere">{value}</span>
                </label>
              );
            })}
            {!visible.length && (
              <p role="status" className="px-3 py-3 text-xs text-(--muted)">
                Nenhuma opção encontrada.
              </p>
            )}
          </div>
          <div className="flex shrink-0 items-center justify-between gap-2 border-t border-(--border) px-2 py-1">
            <span className="ps-2 text-xs text-(--muted)">
              {selected.length ? `${selected.length} de ${values.length}` : "Todas as opções"}
            </span>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={!selected.length}
              onClick={() => onChange([])}
            >
              Limpar seleção
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
