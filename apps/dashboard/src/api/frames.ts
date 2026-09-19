/**
 * Component-facing read model for the frame wall (plan §11.7).
 *
 * Frame bytes are committed evidence, not decoration: the wall reads the
 * latest run-bound image for a `(run_id, candidate_id)` from
 * `GET /api/runs/{run_id}/frames/{candidate_id}/latest?after={seq}`. When that
 * source is absent the wall renders `available: false` with a reason — never a
 * placeholder image, never a looping animation. The `after` sequence is only
 * ever a server-announced `frame_seq`; an unknown sequence stays `null` and is
 * omitted from the request rather than guessed.
 */

import { ControlApiError } from "./client";
import type { ControlApiConfig } from "./config";
import { routes } from "./routes";

export interface FrameWallFrame {
  /** The exact committed bytes returned by the control API. */
  blob: Blob;
  /**
   * Server-announced `frame_seq` for these bytes, or `null` when the response
   * announced none. Never synthesised from the request or a prior frame.
   */
  seq: number | null;
  /**
   * Epoch milliseconds at which the dashboard received these bytes. This is a
   * measured receive time — the capture time only exists in committed frame
   * metadata, which is not part of this read model yet.
   */
  receivedAtMs: number;
}

export interface FrameWallState {
  /**
   * `false` until the control API serves committed frame bytes; every tile then
   * shows the labelled reason — never a placeholder image.
   */
  available: boolean;
  unavailableReason?: string;
  /** Latest committed frame per candidate id; absence = no committed frame yet. */
  frames: Record<string, FrameWallFrame>;
}

export function unavailableFrames(reason: string): FrameWallState {
  return { available: false, unavailableReason: reason, frames: {} };
}

export type FrameFetchResult =
  | { available: true; blob: Blob; seq: number | null }
  | {
      available: false;
      reason: string;
      /**
       * `true` when a frame exists but is not newer than `afterSeq` (HTTP 204
       * no-content, 304 not-modified or 409 stale `after`). The wall keeps its
       * previous bytes.
       */
      unchanged?: boolean;
    };

/**
 * Response header the wall reads as the announced sequence. Plan §9.1 calls
 * the frame-bytes route "typed metadata headers" but does not freeze header
 * names yet; `X-Frame-Seq` is the only name accepted, and an absent or
 * malformed header yields `seq: null` rather than a guessed number.
 */
const FRAME_SEQ_HEADER = "X-Frame-Seq";

/**
 * `GET /api/runs/{run_id}/frames/{candidate_id}/latest?after={seq}` with the
 * operator bearer token and `cache: "no-store"`.
 *
 * Returns `{ available: false, reason }` when no committed frame source exists
 * (404/501) or when the source reports the frame unchanged (204/304/409) and
 * `{ available: true, blob, seq }` on 200. Every other status is rethrown as a
 * `ControlApiError` so the UI can surface it instead of hiding it.
 */
export async function fetchLatestFrame(
  config: ControlApiConfig,
  runId: string,
  candidateId: string,
  afterSeq: number | null,
): Promise<FrameFetchResult> {
  const response = await fetch(
    `${config.baseUrl}${routes.runFrameLatest(runId, candidateId, afterSeq)}`,
    {
      headers: {
        Accept: "image/jpeg, image/webp",
        Authorization: `Bearer ${config.token}`,
      },
      cache: "no-store",
    },
  );

  if (response.status === 404 || response.status === 501) {
    return {
      available: false,
      reason: `the control API does not serve committed frame bytes for run ${runId} / candidate ${candidateId} yet (HTTP ${response.status})`,
    };
  }
  // 204/304 (plan §9.1 "no-content when unchanged") and 409 (the frozen
  // integration request, CONTRACT_CHANGE.md, asks for 409 when `after` is not
  // older than the latest seq) all mean "no newer committed frame": keep the
  // bytes already displayed.
  if (response.status === 204 || response.status === 304 || response.status === 409) {
    return {
      available: false,
      unchanged: true,
      reason: `no frame newer than seq ${afterSeq === null ? "unknown" : afterSeq} yet`,
    };
  }
  if (!response.ok) {
    throw new ControlApiError(
      `GET frames/${candidateId}/latest failed`,
      response.status,
      await response.text(),
    );
  }

  return {
    available: true,
    blob: await response.blob(),
    seq: parseSeqHeader(response.headers.get(FRAME_SEQ_HEADER)),
  };
}

function parseSeqHeader(value: string | null): number | null {
  if (value === null) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : null;
}
