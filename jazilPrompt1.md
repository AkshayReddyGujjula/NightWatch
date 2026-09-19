# Track A — ENGINE build prompt (Jazil's laptop, one agent)

You are the Track A "engine" agent for NightWatch on Jazil's laptop. Read this entire file before
acting. Work in the order below (dependency order, not optionality). Commit + push at every
checkpoint and report raw evidence. A second agent (Track B) is working in parallel on the
browser hero from Akshay's laptop — never edit Track B paths.

## 0. What NightWatch is (30-second version)

NightMart, a synthetic storefront, fails silently: checkout returns HTTP 200 while a lost payment
response makes the buggy retry path capture the same payment twice. NightWatch detects it from a
trusted, append-only provider ledger outside the candidate app, contains it (SAFE_HOLD), freezes
an incident capsule, asks Gemini for a typed diagnosis and several bounded patch proposals, races
every candidate repair in an isolated Modal Sandbox world, grades each with a deterministic
oracle from trusted evidence only, activates the best passing repair under a time-limited repair
lease, and emits an engineer receipt. A cybersecurity incident (SQL injection and/or
malformed-payload crash/downtime) is part of this build and follows the same pipeline. Models
propose; deterministic code decides.

## 1. Ground rules (non-negotiable)

- Evidence only. Never fake a pass. If a gate cannot run, label the degraded mode.
- Deterministic authority: Gemini proposes diagnosis/patches; Jev proposes bounded browser
  actions; the oracle and selection are code.
- Generated code never silently merges: activation is time-limited, reversible, evidence-gated,
  and labelled as generated code when applicable.
- Secrets never appear in code, commits, logs, screenshots or receipts (public repo).
- No Playwright anywhere.
- The original incident namespace is immutable; resets create new namespaces.
- Frozen contracts live in `apps/contracts/**` + `fixtures/**`. If you change a model:
  regenerate schemas (`uv run python scripts/gen_schemas.py`), update contract tests, and record
  the change in `CONTRACT_CHANGE.md`.
- You are the ONLY deployer. Deploy the composed app:
  `MODAL_ENVIRONMENT=nightwatch-demo uv run modal deploy modal_app.py`
  After every deploy prove: `modal app list --env nightwatch-demo` Tasks >= 3 and two consecutive
  fast reads (<1s) on all three `/health` endpoints. Report every deploy with its reason.
- Git: `git pull --rebase` immediately before every push; no force push; keep commits scoped to
  Track A paths; if a rebase conflicts in a Track B-owned file, stop and report.
- Track A paths: `apps/contracts/**`, `apps/live_store/**`, `apps/trusted_provider/**`,
  `apps/control_plane/**`, `modal/services_a.py`, `services/detector.py`, `services/capsule.py`,
  `services/oracle.py`, `services/selector.py`, `services/canary.py`,
  `services/lease_guardian.py`, `services/gemini_agent.py`, `services/patch_guard.py`,
  `scripts/preflight.py`, `scripts/run_demo.py`, `scripts/reset_demo.py`,
  `scripts/verify_receipt.py`, `scripts/secret_scan.py`, `fixtures/**`, `tests/conftest.py`.
- Never edit Track B paths: `services/worlds/**`, `services/scheduler.py` (coordinate),
  `services/jev/**`, `services/frames/**`, `apps/dashboard/**`, `apps/storefront/**` (serve
  only), `infra/**`, `modal/services_b.py`, `modal_app.py`, `tests/isolation/**`.

## 2. What already exists (checkpoint 1 — do not rebuild)

- Incident spine passes Gate G0 locally: `uv run python scripts/g0_gate.py` (real duplicate
  capture, INV-01 detector, immutable original digest).
- Deployed at commit `928831a` on `nightwatch-demo`: three healthy ASGI services, local SQLite +
  closed Volume snapshots + SHA-256 sidecars, durable across redeploys. URLs:
  `https://jxzxl07-nightwatch-demo--nightwatch-control-asgi.modal.run`,
  `...--nightwatch-live-store-asgi.modal.run`, `...--nightwatch-provider-asgi.modal.run`.
- NightMart storefront live: `/checkout-x.html` ("Pay now"), `/checkout-y.html`
  ("Confirm order" + voucher), API reachable from the pages.
- Control foundation: `POST /api/incidents/{id}/run` currently creates the run, writes and reads
  back SAFE_HOLD, and does NOT orchestrate yet; plus `/safe-stop`, `GET incident`,
  `GET /events` (SSE with Last-Event-ID replay), `GET /receipt`,
  `GET /api/runs/{id}/evaluations`, `GET /api/worlds/{id}/health`. Hash-chained SQLite control
  store in `services/control_store.py`.
- Contracts: 60 generated schemas including `control.EvaluationResults`, `control.IncidentSnapshot`,
  `control.WorldHealth`, `control.SafeStopRequest`; the dashboard consumes generated types.
- 118 tests pass; ruff + mypy clean.
- Track B has proven the real `run_candidate.map` race: 3 distinct sandboxes, peak concurrency 3,
  3.96 s measured all-alive window (`scripts/smoke_map_race.py`).

## 3. Tasks (dependency order)

### Task 1 — Oracle + scenario execution (start now; biggest unblock)

- `services/oracle.py`: INV-01..06 from trusted evidence only (provider ledger + evaluator-only
  app-state reads); typed `InvariantResult` with non-empty evidence ids; evidence-set validation
  per `(candidate, scenario, invariant)`; `all([])` must NEVER pass.
- Scenario executor per plan §12.2: per-scenario DB generation file, own provider namespace, own
  short-lived scoped token, seed/code/fault hashes asserted before the run.
- S03–S08 API scenarios real; S01/S02 UI scenarios labelled `ERROR_BROWSER_STACK` until Track B's
  browser unblock is green; NC-01/NC-02 must fail the intended invariant.
- Gate: one full candidate world returns real `ScenarioResult`s with exact evidence sets, and both
  negative controls produce the expected failures.

### Task 2 — Orchestration (wire `POST /run` to the engine)

- Implement `orchestrate_incident` (plan §4.2): freeze capsule -> Gemini typed diagnosis -> build
  candidate specs (A rollback, B safe handler, C candidates when Gemini lands) ->
  `run_candidate.map` race with `order_outputs=True, return_exceptions=True` -> persist events as
  they happen -> grade with the oracle -> deterministic selection.
- Keep the existing SAFE_HOLD write + readback before any experiment.
- A crashed or unusable world must stay that candidate's own labelled ERROR evaluation.
- Gate: end-to-end from `POST /api/incidents/{id}/run` to graded candidates with real evidence.

### Task 3 — Selection -> staged smoke -> lease -> receipt

- Deterministic selection: a candidate must pass every required gate; tie-break by smallest diff /
  lowest risk, code-owned; never model confidence.
- Staged smoke: `rollout_pct` + `bucket_seed`, 20 probes per stage (5/25/100), every probe
  oracle-checked; any stage failure -> no activation.
- Lease + router readback + guardian; expiry or guardian failure -> SAFE_HOLD, never BUGGY.
  Demonstrate Safe Stop.
- Receipt: `demo_mode`, `degraded_reasons` (naming the true browser state), the already-harmed
  intent, containment, every candidate outcome with evidence ids, winner + why, unresolved work.
- Gate: local end-to-end trigger -> receipt, with the reduced browser state labelled honestly.

### Task 4 — Gemini multi-patch

- `services/gemini_agent.py`: typed `GeminiDiagnosis` (with the advisory triage block: category,
  severity, rationale <=200 chars, confidence 0-1) + N = 2–3 bounded one-file `PatchProposal`s;
  structured output only; malformed output fails closed.
- `services/patch_guard.py`: allowed paths, diff/size bounds, no new dependencies, tests named;
  reject anything else.
- Each valid patch becomes its own world C1..CN, racing alongside A and B; record patch hashes.
- Generated patches activate only through the lease path and are labelled; if Gemini fails or is
  slow, C is `SKIPPED_INVALID` (labelled) and A/B still race.

### Task 5 — Security incident (mandatory for the pivot)

- Add S09 (SQL injection: cross-namespace read or unauthorized mutation) and S10
  (malformed-payload crash/downtime) to `fixtures/scenarios.json`, with new oracle invariants
  (e.g. no cross-namespace reads, no unauthenticated mutation, no 5xx storm under the attack
  payload), deterministic attacker payloads, fault injection, and negative controls.
- Update contracts/schemas/tests + `CONTRACT_CHANGE.md` as needed.
- The attacker path must be replayable inside every candidate world; the patched world must block
  the attack while legitimate flows still pass.
- Gate: oracle detects and grades the security incident with real evidence; no fake attack results.

### Task 6 — Integration with Track B (at each integration point)

- Pull Track B's commits; deploy the composed `modal_app.py` (it carries their `run_candidate`
  changes); prove Tasks + health.
- When Track B's `services/frames/**` store lands, replace the control plane's `ReferenceSink`
  with their implementation (you own the wiring) without changing the frozen wire contract.
- Smoke the DEPLOYED runner via
  `modal.Function.from_name("nightwatch", "run_candidate").map(...)` — never `modal run` for the
  deployed artifact (an ephemeral app can warm production ASGI containers).

## 4. Time plan (submission 19:00, live demo 20:00; it is ~15:05 now)

- 15:05–16:30 Task 1 (oracle + scenarios).
- 16:30–17:30 Task 2 (orchestration) + first payment-incident E2E.
- 17:30–18:30 Task 3 + Task 4 (selection/lease/receipt, Gemini multi-patch) + start Task 5.
- 18:30–19:00 integration, rehearsals, freeze, submit. Task 5 must be in by the rehearsal if at
  all possible; if not, label it. Nothing fake.

## 5. Report format at every checkpoint

1. Commit SHAs pushed + what changed.
2. Deploy evidence: deploy output, Tasks, the six health timings, live route inventory.
3. Gate evidence: raw output for the gate you claim (oracle results, E2E event log, receipt).
4. What is not green, with its honest label.
5. Blockers / decisions needed.
6. Next slice.

Stop and report at each checkpoint. Never continue past a failed gate by hiding it.
