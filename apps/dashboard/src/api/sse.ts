/**
 * SSE subscriber for the control event stream (plan §9.1, §15.2).
 *
 * Fetch-based, not `EventSource`: every operator endpoint requires
 * `Authorization: Bearer`, which the browser `EventSource` API cannot set.
 * Reconnects carry `Last-Event-ID` so a reconnecting dashboard replays
 * committed events instead of inventing state.
 */

import type { IncidentEvent } from "../generated";
import type { ControlApiConfig } from "./config";
import { routes } from "./routes";
import { SseParser } from "./sseParser";

export type StreamState = "connecting" | "open" | "reconnecting" | "stopped";

export interface IncidentEventSubscription extends ControlApiConfig {
  incidentId: string;
  /** Replay from this committed event id on the first connect (plan §15.2). */
  lastEventId?: string;
  onEvent: (event: IncidentEvent) => void;
  onState?: (state: StreamState) => void;
  /** Transport-level problem; the UI must surface it, never hide it. */
  onDegraded?: (reason: string) => void;
}

export interface IncidentEventStream {
  stop: () => void;
}

const RECONNECT_DELAYS_MS = [1_000, 2_000, 4_000, 8_000, 10_000];

export function subscribeIncidentEvents(
  subscription: IncidentEventSubscription,
): IncidentEventStream {
  const controller = new AbortController();
  const url = `${subscription.baseUrl}${routes.incidentEvents(subscription.incidentId)}`;
  const reportState = subscription.onState ?? (() => undefined);
  const reportDegraded = subscription.onDegraded ?? (() => undefined);
  let lastEventId = subscription.lastEventId;
  let attempt = 0;

  const run = async () => {
    while (!controller.signal.aborted) {
      reportState(attempt === 0 ? "connecting" : "reconnecting");
      try {
        const response = await fetch(url, {
          headers: {
            Accept: "text/event-stream",
            Authorization: `Bearer ${subscription.token}`,
            ...(lastEventId !== undefined && lastEventId !== ""
              ? { "Last-Event-ID": lastEventId }
              : {}),
          },
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok || response.body === null) {
          throw new Error(`event stream refused: HTTP ${response.status}`);
        }
        reportState("open");
        attempt = 0;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        const parser = new SseParser();
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          for (const frame of parser.push(decoder.decode(value, { stream: true }))) {
            if (frame.id !== undefined && frame.id !== "") lastEventId = frame.id;
            if (frame.event !== undefined && frame.event !== "message") continue;
            if (frame.data === "") continue;
            const parsed = parseIncidentEvent(frame.data);
            if (parsed === undefined) {
              reportDegraded("dropped a malformed event frame (control-plane logs hold the source)");
              continue;
            }
            subscription.onEvent(parsed);
          }
        }
      } catch (error) {
        if (controller.signal.aborted) return;
        reportDegraded(error instanceof Error ? error.message : String(error));
      }
      if (controller.signal.aborted) return;
      const delay = RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)];
      attempt += 1;
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  };

  void run();
  return {
    stop: () => {
      reportState("stopped");
      controller.abort();
    },
  };
}

/**
 * Transport guard only — this is not a schema. The wire shape is the generated
 * `IncidentEvent` (frozen contract); events with unrecognised kinds still
 * arrive typed and the UI must render them explicitly, never silently.
 */
function parseIncidentEvent(data: string): IncidentEvent | undefined {
  try {
    const value: unknown = JSON.parse(data);
    if (typeof value !== "object" || value === null) return undefined;
    const record = value as Record<string, unknown>;
    if (
      typeof record.event_id !== "string" ||
      typeof record.kind !== "string" ||
      typeof record.occurred_at_utc !== "string"
    ) {
      return undefined;
    }
    return value as IncidentEvent;
  } catch {
    return undefined;
  }
}
