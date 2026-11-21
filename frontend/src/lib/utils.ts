import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
export const number = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const calendarDate = new Intl.DateTimeFormat("pt-BR");

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(`${value.slice(0, 10)}T12:00:00`);
  return Number.isNaN(parsed.valueOf()) ? value : calendarDate.format(parsed);
}

export function formatMonth(value: unknown): string {
  return String(value ?? "—").replace(/^(\d{4})-(0[1-9]|1[0-2])$/, "$2/$1");
}
