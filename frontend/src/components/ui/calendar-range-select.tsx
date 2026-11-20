"use client";

import { useId, useState } from "react";
import { format, parseISO } from "date-fns";
import { CalendarDays } from "lucide-react";
import type { DateRange } from "react-day-picker";
import { ptBR } from "react-day-picker/locale";
import { formatDate } from "@/lib/utils";
import { Button } from "./button";
import { Calendar } from "./calendar-range-select-utils/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "./popover";

type DateField = "start_date" | "end_date";
type DateBounds = Record<DateField, string | null>;

function CalendarDateField({
  field,
  label,
  value,
  onChange,
}: {
  field: DateField;
  label: string;
  value: DateBounds;
  onChange: (field: DateField, value: string | null) => void;
}) {
  const [open, setOpen] = useState(false);
  const labelId = useId();
  const valueId = useId();
  const from = value.start_date ? parseISO(value.start_date) : undefined;
  const to = value.end_date ? parseISO(value.end_date) : undefined;
  const selected = field === "start_date" ? from : to;
  const range: DateRange =
    from && to && from < to ? { from, to } : { from: selected ?? from ?? to };
  const year = new Date().getFullYear();
  // Include saved dates in the navigation even when they are outside its usual span.
  const firstYear = Math.min(year - 100, from?.getFullYear() ?? year, to?.getFullYear() ?? year);
  const lastYear = Math.max(year + 10, from?.getFullYear() ?? year, to?.getFullYear() ?? year);

  function select(date: string | null) {
    onChange(field, date);
    setOpen(false);
  }

  return (
    <div className="grid min-w-0 gap-1.5">
      <span id={labelId} className="filter-label">
        {label}
      </span>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger className="filter-control" aria-labelledby={`${labelId} ${valueId}`}>
          <CalendarDays aria-hidden="true" size={16} className="shrink-0 text-(--accent)" />
          <span id={valueId} className={value[field] ? "tabular-nums" : "text-(--muted)"}>
            {value[field] ? formatDate(value[field]) : "Selecionar"}
          </span>
        </PopoverTrigger>
        <PopoverContent
          className="w-72"
          align={field === "end_date" ? "end" : "start"}
          aria-label={label}
        >
          <Calendar
            mode="range"
            locale={ptBR}
            lang="pt-BR"
            captionLayout="dropdown"
            navLayout="after"
            defaultMonth={selected ?? from ?? to}
            startMonth={new Date(firstYear, 0)}
            endMonth={new Date(lastYear, 11)}
            selected={range}
            // The calendar highlights both dates; the clicked day edits this field's endpoint.
            onSelect={(_, day) => select(format(day, "yyyy-MM-dd"))}
            formatters={{
              formatMonthDropdown: (month) => format(month, "MMM", { locale: ptBR }),
            }}
            fixedWeeks
            showOutsideDays={false}
            classNames={{
              range_start: "rounded-s-full bg-(--accent-light)",
              range_end: "rounded-e-full bg-(--accent-light)",
              range_middle: "range-middle bg-(--accent-light)",
              selected:
                "[&:not(.range-middle)>button]:bg-(--accent) [&:not(.range-middle)>button]:font-semibold [&:not(.range-middle)>button]:text-(--background)",
            }}
          />
          <div className="flex items-center justify-between gap-2 border-t border-(--border) px-3 py-2">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={!value[field]}
              onClick={() => select(null)}
            >
              Limpar data
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => select(format(new Date(), "yyyy-MM-dd"))}
            >
              Hoje
            </Button>
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}

export function CalendarRangeSelect({
  value,
  onChange,
}: {
  value: DateBounds;
  onChange: (field: DateField, value: string | null) => void;
}) {
  return (
    <div className="grid grid-cols-2 items-end gap-3">
      <CalendarDateField
        field="start_date"
        label="Data inicial"
        value={value}
        onChange={onChange}
      />
      <CalendarDateField
        field="end_date"
        label="Data final (exclusiva)"
        value={value}
        onChange={onChange}
      />
    </div>
  );
}
