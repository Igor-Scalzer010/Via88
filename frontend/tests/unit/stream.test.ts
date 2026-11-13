import { describe, expect, it } from "vitest";
import { consumeStream, SSEParser } from "../../src/lib/stream";
import { result } from "../fixtures";
describe("SSE transport", () => {
  it("buffers CRLF frames and split JSON without applying fragments", () => {
    const parser = new SSEParser();
    expect(parser.push('event: stage\r\ndata: {"run_id":"r","label":"Consult')).toEqual([]);
    expect(parser.push('ando","stage":"query"}\r')).toEqual([]);
    expect(parser.push("\n\r\n")).toEqual([
      { event: "stage", data: { run_id: "r", label: "Consultando", stage: "query" } },
    ]);
  });
  it("ignores comments and dispatches multiple frames", () => {
    const parser = new SSEParser();
    expect(
      parser.push(
        ': ping\n\nevent: stage\ndata: {"stage":"query"}\n\nevent: stage\ndata: {"stage":"analyze"}\n\n',
      ),
    ).toHaveLength(2);
  });
  it("validates final response and delivers a repeated completion once", async () => {
    const text = `event: completed\ndata: ${JSON.stringify(result)}\n\n`;
    const events: unknown[] = [];
    await consumeStream(new Response(text + text), (event) => events.push(event));
    expect(events).toHaveLength(1);
  });
  it("decodes accented UTF-8 characters split across byte chunks", async () => {
    const text = `event: completed\ndata: ${JSON.stringify({ ...result, answer: "Análise de vítimas" })}\n\n`;
    const bytes = new TextEncoder().encode(text);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (let index = 0; index < bytes.length; index += 7)
          controller.enqueue(bytes.slice(index, index + 7));
        controller.close();
      },
    });
    let answer = "";
    await consumeStream(new Response(body), (event) => {
      if (event.event === "completed") answer = event.data.answer;
    });
    expect(answer).toBe("Análise de vítimas");
  });
  it("rejects an interrupted or malformed response", async () => {
    await expect(
      consumeStream(
        new Response(
          'event: stage\ndata: {"run_id":"r","stage":"query","label":"Consultando"}\n\n',
        ),
        () => {},
      ),
    ).rejects.toThrow("interrompida");
    await expect(
      consumeStream(new Response("event: completed\ndata: {}\n\n"), () => {}),
    ).rejects.toThrow();
  });
  it("surfaces a safe server error", async () => {
    await expect(
      consumeStream(
        new Response(
          'event: error\ndata: {"run_id":"r","code":"no_data","message":"Sem dados suficientes"}\n\n',
        ),
        () => {},
      ),
    ).rejects.toThrow("Sem dados suficientes");
  });
});
