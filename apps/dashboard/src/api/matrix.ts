/**
 * Component-facing read model for the scenario matrix (S01–S08 + NC-01/NC-02).
 *
 * This is not a wire schema. Wire shapes are the generated modules
 * (`src/generated/**`, codegen from `apps/contracts/schemas`); this file
 * projects them (plus the frozen registry fixture) into the exact cells the
 * table renders. When the contract owner freezes the committed-results source,
 * only `client.ts` changes — no component rework.
 */

import type { NegativeControl, ScenarioResult } from "../generated";
import type { InvariantId } from "../generated/evaluation_InvariantResult";
import type { CandidateId, ScenarioId } from "../generated/evaluation_ScenarioResult";

export type ResultStatus = "PASS" | "FAIL" | "ERROR";

export type CellTone = "none" | "pass" | "fail" | "warn" | "expected" | "unexpected";

export interface NegativeControlOutcome {
  control_id: NegativeControl["control_id"];
  status: ResultStatus;
  /** Invariants the oracle observed failing; compared with `must_fail`. */
  failed_invariants: InvariantId[];
  evidence_ids: string[];
}

export interface EvaluationResults {
  /**
   * `false` until the control API serves committed evaluation results; every
   * cell then stays labelled `no result` / `not run` — never a guess.
   */
  available: boolean;
  unavailableReason?: string;
  scenarios: ScenarioResult[];
  negativeControls: NegativeControlOutcome[];
}

export function unavailableResults(reason: string): EvaluationResults {
  return { available: false, unavailableReason: reason, scenarios: [], negativeControls: [] };
}

export const UNAVAILABLE_RESULTS: EvaluationResults = unavailableResults(
  "the control API does not serve committed evaluation results yet",
);

export interface ResultCellView {
  label: string;
  tone: CellTone;
  /** Hover trace: every status is traceable to evidence ids or a reason. */
  trace: string;
}

export function scenarioCell(
  candidateId: CandidateId,
  scenarioId: ScenarioId,
  results: EvaluationResults,
): ResultCellView {
  const row = results.scenarios.find(
    (result) => result.candidate_id === candidateId && result.scenario_id === scenarioId,
  );
  if (row === undefined) {
    return {
      label: "no result",
      tone: "none",
      trace: `no committed result for candidate ${candidateId} / ${scenarioId} (labelled empty — never a guess)`,
    };
  }
  const evidence = (row.invariants ?? []).flatMap((invariant) => invariant.evidence_ids ?? []);
  for (const id of row.ledger_evidence_ids ?? []) evidence.push(id);
  const parts = [`candidate ${candidateId} · ${scenarioId} · status ${row.status}`];
  if (row.failure_reason) parts.push(`reason: ${row.failure_reason}`);
  parts.push(evidence.length > 0 ? `evidence: ${evidence.join(", ")}` : "no evidence ids");
  return {
    label: row.status,
    tone: row.status === "PASS" ? "pass" : row.status === "FAIL" ? "fail" : "warn",
    trace: parts.join(" — "),
  };
}

export function negativeControlCell(
  control: NegativeControl,
  results: EvaluationResults,
): ResultCellView {
  const outcome = results.negativeControls.find(
    (candidate) => candidate.control_id === control.control_id,
  );
  if (outcome === undefined) {
    return {
      label: "not run",
      tone: "none",
      trace: `no committed oracle result for ${control.control_id} (labelled empty — never a guess)`,
    };
  }
  const evidence =
    outcome.evidence_ids.length > 0 ? `evidence: ${outcome.evidence_ids.join(", ")}` : "no evidence ids";
  if (outcome.status === "FAIL") {
    const covered = control.must_fail.every((invariant) =>
      outcome.failed_invariants.includes(invariant),
    );
    if (covered) {
      return {
        label: `FAIL ${control.must_fail.join(" ")} — expected`,
        tone: "expected",
        trace: `${control.control_id} failed as intended — ${evidence}`,
      };
    }
    return {
      label: `FAIL ${outcome.failed_invariants.join(" ")} — expected ${control.must_fail.join(" ")}`,
      tone: "warn",
      trace: `${control.control_id} failed for the wrong invariants — ${evidence}`,
    };
  }
  if (outcome.status === "PASS") {
    return {
      label: "PASS — control did not fail",
      tone: "unexpected",
      trace: `the oracle let this lie through; do not trust PASS verdicts above — ${evidence}`,
    };
  }
  return { label: "ERROR", tone: "warn", trace: `${control.control_id} oracle error — ${evidence}` };
}
