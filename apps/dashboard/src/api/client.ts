/**
 * Typed control-API client (plan §9.1).
 *
 * Response types are the generated modules (`src/generated/**`, codegen from
 * `apps/contracts/schemas`) — no hand-written wire shape exists here. Route
 * paths live in `routes.ts`. Reads send the operator token and never trust a
 * cache (`Cache-Control: no-store` on live views).
 */

import type { EvaluationResults as CommittedEvaluations, IncidentSnapshot, RepairReceipt } from "../generated";
import type { ControlApiConfig } from "./config";
import { type EvaluationResults, unavailableResults } from "./matrix";
import { routes } from "./routes";

export class ControlApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: string,
  ) {
    super(message);
    this.name = "ControlApiError";
  }
}

export class ControlApi {
  constructor(private readonly config: ControlApiConfig) {}

  /** `GET /api/incidents/{id}/receipt` — canonical receipt (plan §9.1). */
  async getReceipt(incidentId: string): Promise<RepairReceipt> {
    return this.getJson<RepairReceipt>(routes.incidentReceipt(incidentId));
  }

  /**
   * Committed S01–S08 and NC-01/NC-02 outcomes for the matrix.
   *
   * Resolve the committed run id from the incident snapshot, then read the
   * frozen run-scoped evaluation payload. Provisional runner output is never
   * exposed to components.
   */
  async getEvaluationResults(incidentId: string): Promise<EvaluationResults> {
    try {
      const incident = await this.getJson<IncidentSnapshot>(routes.incident(incidentId));
      const committed = await this.getJson<CommittedEvaluations>(
        routes.runEvaluations(incident.run_id),
      );
      return {
        available: true,
        scenarios: committed.scenarios ?? [],
        negativeControls: (committed.negative_controls ?? []).map((control) => ({
          control_id: control.control_id,
          status: control.status,
          failed_invariants: control.failed_invariants ?? [],
          evidence_ids: control.evidence_ids ?? [],
        })),
      };
    } catch (error) {
      if (error instanceof ControlApiError && error.status === 404) {
        return unavailableResults(`no committed evaluation results for incident ${incidentId} yet`);
      }
      throw error;
    }
  }

  private async getJson<T>(path: string): Promise<T> {
    const response = await fetch(`${this.config.baseUrl}${path}`, {
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${this.config.token}`,
      },
      cache: "no-store",
    });
    if (!response.ok) {
      throw new ControlApiError(
        `GET ${path} failed`,
        response.status,
        await response.text(),
      );
    }
    return (await response.json()) as T;
  }
}
