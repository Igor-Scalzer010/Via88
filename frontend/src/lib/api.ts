import { z } from "zod";
export async function api<S extends z.ZodTypeAny>(
  path: string,
  schema: S,
  init?: RequestInit,
): Promise<z.output<S>> {
  const response = await fetch(`/api${path}`, {
    ...init,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new Error(
      body && typeof body === "object" && "detail" in body && typeof body.detail === "string"
        ? body.detail
        : `A solicitação falhou (${response.status}).`,
    );
  }
  return schema.parse(await response.json());
}
