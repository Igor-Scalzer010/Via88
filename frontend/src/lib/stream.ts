import {
  ErrorSchema,
  ResponseSchema,
  StageSchema,
  type Response,
  type Stage,
} from "./contracts.generated";
export type StreamEvent =
  { event: "run_started" | "stage"; data: Stage } | { event: "completed"; data: Response };
export class StreamFailure extends Error {
  constructor(
    message: string,
    readonly code: string,
  ) {
    super(message);
  }
}

/** SSE frames can cross UTF-8 and network chunk boundaries. Only complete frames are applied. */
export class SSEParser {
  private buffer = "";
  push(chunk: string): { event: string; data: unknown }[] {
    this.buffer += chunk;
    const frames: { event: string; data: unknown }[] = [];
    let match: RegExpExecArray | null;
    while ((match = /\r?\n\r?\n/.exec(this.buffer))) {
      const frame = this.buffer.slice(0, match.index);
      this.buffer = this.buffer.slice(match.index + match[0].length);
      const lines = frame.split(/\r?\n/);
      const event =
        lines
          .find((line) => line.startsWith("event:"))
          ?.slice(6)
          .trim() ?? "message";
      const data = lines
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).replace(/^ /, ""))
        .join("\n");
      if (data) frames.push({ event, data: JSON.parse(data) as unknown });
    }
    return frames;
  }
}
export async function consumeStream(
  response: globalThis.Response,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new Error(
      body && typeof body === "object" && "detail" in body && typeof body.detail === "string"
        ? body.detail
        : "Não foi possível iniciar a análise.",
    );
  }
  if (!response.body) throw new Error("O servidor não iniciou o fluxo de análise.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SSEParser();
  let completed = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      for (const frame of parser.push(decoder.decode(value, { stream: !done }))) {
        if (frame.event === "error") {
          const error = ErrorSchema.parse(frame.data);
          throw new StreamFailure(error.message, error.code);
        }
        if (frame.event === "stage" || frame.event === "run_started")
          onEvent({ event: frame.event, data: StageSchema.parse(frame.data) });
        if (frame.event === "completed" && !completed) {
          onEvent({ event: "completed", data: ResponseSchema.parse(frame.data) });
          completed = true;
        }
      }
      if (done) break;
    }
    if (!completed)
      throw new Error(
        "A conexão foi interrompida antes da conclusão. O painel anterior foi preservado.",
      );
  } finally {
    reader.releaseLock();
  }
}
