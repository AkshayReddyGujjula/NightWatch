/**
 * Typed control-API client (plan §9.1).
 *
 * Response types are the generated modules (`src/generated/**`, codegen from
 * `apps/contracts/schemas`) — no hand-written wire shape exists here. Route
 * paths live in `routes.ts`. Reads send the operator token and never trust a
 * cache (`Cache-Control: no-store` on live views).
 */

import type { RepairReceipt } from "../generated";
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
   * The frozen control API (plan §9.1) does not yet serve a per-scenario or
   * per-negative-control results payload — the receipt carries candidate-level
   * verdicts only — and this project never invents a wire shape. Until the
   * contract owner freezes the source, the result is explicitly unavailable
   * and the matrix renders labelled empties. When it lands, only this method
   * (plus `routes.ts`) changes; no component changes.
   */
  async getEvaluationResults(incidentId: string): Promise<EvaluationResults> {
    return unavailableResults(
      `no committed evaluation results source is served for incident ${incidentId} yet`,
    );
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
