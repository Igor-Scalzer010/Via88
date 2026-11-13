import { type NextRequest } from "next/server";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
// Stream the Python response without buffering; the model key stays in FastAPI.
async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const base = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";
  const target = new URL(`/api/${path.map(encodeURIComponent).join("/")}`, base);
  target.search = request.nextUrl.search;
  try {
    const response = await fetch(target, {
      method: request.method,
      headers: {
        "Content-Type": request.headers.get("content-type") ?? "application/json",
        Accept: request.headers.get("accept") ?? "application/json",
      },
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.text(),
      cache: "no-store",
      signal: request.signal,
    });
    return new Response(response.body, {
      status: response.status,
      headers: {
        "Content-Type": response.headers.get("content-type") ?? "application/json",
        "Cache-Control": "no-store, no-transform",
        "X-Accel-Buffering": "no",
      },
    });
  } catch {
    return Response.json(
      { detail: "Não foi possível conectar ao backend. Verifique se o FastAPI está em execução." },
      { status: 502 },
    );
  }
}
export { proxy as GET, proxy as POST, proxy as PATCH };
