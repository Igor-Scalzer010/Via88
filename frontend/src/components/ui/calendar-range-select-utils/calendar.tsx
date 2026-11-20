"use client";

import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from "lucide-react";
import { DayPicker } from "react-day-picker";
import { cn } from "@/lib/utils";

const chevrons = { down: ChevronDown, left: ChevronLeft, right: ChevronRight, up: ChevronUp };
const navButton =
  "grid size-8 place-items-center rounded-md border border-(--border) hover:bg-(--accent-light) aria-disabled:cursor-not-allowed aria-disabled:opacity-40";

export function Calendar({
  className,
  classNames,
  showOutsideDays = true,
  ...props
}: React.ComponentProps<typeof DayPicker>) {
  return (
    <DayPicker
      showOutsideDays={showOutsideDays}
      className={cn("p-3", className)}
      classNames={{
        month: "relative",
        month_caption: "flex h-8 items-center pe-[4.5rem]",
        dropdowns: "flex min-w-0 items-center gap-1.5",
        dropdown_root:
          "relative inline-flex h-8 items-center rounded-md border border-(--border) focus-within:outline-2 focus-within:outline-(--accent)",
        dropdown:
          "absolute inset-0 z-10 w-full cursor-pointer opacity-0 [&_option]:bg-(--card) [&_option]:text-(--foreground)",
        caption_label: "inline-flex items-center gap-1 px-2 text-xs font-semibold capitalize",
        nav: "absolute end-0 top-0 z-10 flex items-center gap-1",
        button_previous: navButton,
        button_next: navButton,
        month_grid: "mt-2 w-full table-fixed border-separate border-spacing-0",
        weekday: "h-8 text-center text-[11px] font-medium capitalize text-(--muted)",
        day: "p-0 text-center",
        day_button:
          "relative mx-auto flex h-9 w-full items-center justify-center rounded-full text-xs tabular-nums hover:bg-(--accent-light) focus-visible:z-10",
        today: "[&_button]:font-bold [&_button]:underline [&_button]:underline-offset-4",
        outside: "text-(--muted)",
        hidden: "invisible",
        ...classNames,
      }}
      components={{
        Chevron: ({ orientation = "down", size = 14, className }) => {
          const Icon = chevrons[orientation];
          return <Icon aria-hidden="true" size={size} className={className} />;
        },
      }}
      {...props}
    />
  );
}
