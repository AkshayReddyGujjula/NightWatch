# Track A — finish the incident path to a working lease and receipt

Paste this into the Track A agent session. Read `Final-nightwatch-plan.md` §4.1, §9, §10.4,
§12.2, §13, §14, §18 (G1–G4), §20, §27 before acting.

G0 passed: the incident is undeniable. Everything below is what the reduced demo still needs
from Track A, in dependency order. Only item 4 is droppable.

## 0. Unblock Track B first — before anything else

1. **Answer the Modal App seam request in `CONTRACT_CHANGE.md`.** It is a ~10-line decision
   and it is holding Track B's `services_b.py` — their `run_candidate` cannot be built
   without it.
2. **Confirm the scoped-token minting shape**: short-lived tokens bound to
   `{incident_id, candidate_id, scenario_id, namespace, allowed_operation_ids, expiry}`
   (§4.1 rule 3), minted by the provider, and never entering a candidate sandbox as
   anything other than that token.

## 1. The oracle + scenario execution (§13) — this is what grades the race

- `services/oracle.py`: INV-01..06 evaluated from **trusted evidence only** (provider
  ledger + evaluator-only app-state read), returning typed `InvariantResult` with non-empty
  evidence ids.
- Execute the S01–S08 registry from `fixtures/scenarios.json` exactly as §12.2/§13
  describe: per-scenario DB generation file, own provider namespace, own short-lived token,
  seed/code/fault hashes asserted before the run.
- S01/S02 are `ERROR_BROWSER_STACK` today (see §11.8): they must fail closed and be
  labelled — never silently skipped, never counted as passes.
- Evidence-set validation: a PASS requires every expected
  `(candidate, scenario, invariant)` tuple exactly once. `all([])` must never pass.
- Both negative controls must fail for the intended reason.

## 2. Control plane: state machine, routes, events

- CAS transitions with the stop flag, the event table, SSE with `Last-Event-ID`.
- The routes Track B's dashboard needs: `GET /api/incidents/{id}`, `/events`, `/receipt`,
  `GET /api/worlds/{id}/health`, `POST /api/incidents/{id}/run`, `POST /.../safe-stop`.
- `SAFE_HOLD` precedes every experiment and never returns to `BUGGY`.

## 3. Selection, staged smoke, lease, receipt

- Selector: lowest-ranked live-eligible candidate that passed every gate (B, or `LEGACY`
  when `POLICY_LIVE_A=1` and it passed). Deterministic, evidence-driven, no model input.
- Staged smoke with `rollout_pct` + `bucket_seed`, 20 probes per stage, every probe
  oracle-checked.
- Lease issuance + router readback + guardian; expiry or guardian failure → `SAFE_HOLD`,
  never `BUGGY`.
- Receipt carrying `demo_mode` and `degraded_reasons`, naming the browser-stack failure
  explicitly.

## 4. Gemini diagnosis + patch guard (candidate C) — droppable under time pressure

- Typed `GeminiDiagnosis` including the advisory triage block (§10.4) and one bounded
  `PatchProposal` behind the patch guard.
- If time compresses, C becomes `SKIPPED_INVALID`, labelled. Never faked.

## Rules

Stay inside Track A paths; `git pull --rebase` before every push; never commit secrets;
never fake a pass; the original namespace is immutable.
Run the review loop at every milestone — 2–4 parallel reviewers (plan-conformance,
adversarial correctness, trust boundary, evidence integrity) — fix confirmed findings and
re-run until a pass returns nothing material.

## Report back

1. Commits + areas shipped
2. Seam reply + token-minting confirmation (yes/no, with the decision)
3. Oracle: invariant coverage, evidence ids, negative-control results
4. Routes live (list) · selection/lease state
5. Receipt example (or why not yet)
6. Tests: ruff / mypy / pytest counts
7. Blockers + decisions needed · next slice with its gate
