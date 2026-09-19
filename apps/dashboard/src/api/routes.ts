/**
 * Control-API route builders — the single place route paths live.
 *
 * Every path below is from the frozen control API table (plan §9.1). This file
 * invents nothing: response types are the generated modules in
 * `src/generated/**` (codegen from `apps/contracts/schemas`). If the
 * implementation moves a path, this file and `client.ts` change — never a
 * component.
 */

const API_ROOT = "/api";

function incidentPath(incidentId: string): string {
  return `${API_ROOT}/incidents/${encodeURIComponent(incidentId)}`;
}

export const routes = {
  /** `GET /api/incidents/{id}` — committed incident/run snapshot. */
  incident: (incidentId: string) => incidentPath(incidentId),
  /** `GET /api/incidents/{id}/receipt` — canonical signed/hashed receipt JSON. */
  incidentReceipt: (incidentId: string) => `${incidentPath(incidentId)}/receipt`,
  /** `GET /api/incidents/{id}/events` — SSE replay from the committed event table. */
  incidentEvents: (incidentId: string) => `${incidentPath(incidentId)}/events`,
  /** `GET /api/runs/{run_id}/evaluations` — committed matrix source. */
  runEvaluations: (runId: string) => `${API_ROOT}/runs/${encodeURIComponent(runId)}/evaluations`,
  /**
   * `GET /api/runs/{run_id}/frames/{candidate_id}/latest?after={seq}` — latest
   * run-bound frame bytes for one candidate (plan §11.7). `afterSeq` is omitted
   * when no committed sequence is known yet: the wall never invents one.
   */
  runFrameLatest: (runId: string, candidateId: string, afterSeq: number | null) =>
    `${API_ROOT}/runs/${encodeURIComponent(runId)}/frames/${encodeURIComponent(candidateId)}/latest` +
    (afterSeq === null ? "" : `?after=${afterSeq}`),
} as const;
