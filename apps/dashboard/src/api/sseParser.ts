/**
 * Minimal SSE frame parser (WHATWG event-stream format; plan §15.2 reconnect
 * semantics). Pure text-in / frames-out, so it is exercised without a network:
 * `sse.ts` feeds it decoded chunks and owns reconnect and `Last-Event-ID`
 * behaviour.
 */

export interface SseFrame {
  /** `id:` field — the committed event id used for `Last-Event-ID` replay. */
  id?: string;
  /** `event:` field — absent for plain messages. */
  event?: string;
  /** `data:` field(s), joined with newlines. */
  data: string;
}

export class SseParser {
  private buffer = "";

  push(chunk: string): SseFrame[] {
    this.buffer += chunk;
    // Normalise complete CRLF pairs only. A lone trailing CR stays buffered
    // until the next chunk completes it; frames are separated by a blank line.
    this.buffer = this.buffer.replace(/\r\n/g, "\n");
    const frames: SseFrame[] = [];
    let boundary = this.buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const raw = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      const frame = parseFrame(raw);
      if (frame !== undefined) frames.push(frame);
      boundary = this.buffer.indexOf("\n\n");
    }
    return frames;
  }
}

function parseFrame(raw: string): SseFrame | undefined {
  let id: string | undefined;
  let event: string | undefined;
  const data: string[] = [];
  for (const line of raw.split("\n")) {
    if (line === "" || line.startsWith(":")) continue; // comment / keep-alive
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "id") id = value;
    else if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (data.length === 0 && id === undefined && event === undefined) return undefined;
  return { id, event, data: data.join("\n") };
}
