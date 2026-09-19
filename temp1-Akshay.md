# Track B — finish the reduced demo (browser chapter closed)

Paste this into the Track B agent session. Read `Final-nightwatch-plan.md` §3.2, §11.8, §12,
§14.4, §15, §16.1, §31.4 before acting.

## Accepted as final

- Browser spend is closed. Recording Card 3 as "mechanism untested, not disproven" is
  exactly the right standard of evidence — keep it. Add one line noting Card 4 (CDP
  first-navigation over the driver-owned loopback endpoint) as **untested and not
  attempted**, so the record is complete and nobody later assumes it was tried.
- Card 4 is **out of scope** unless Akshay explicitly reopens it after the core demo is
  rehearsing. Do not start it.
- Nothing in the demo, dashboard, README or receipt may reference a browser journey. The
  pane area shows the labelled blocker panel — the two driver findings with their evidence
  and a pointer to `infra/BROWSER_STACK_NOTES.md`. Never a static image posing as a live
  session.
- The receipt must carry `demo_mode` and `degraded_reasons` naming the browser-stack
  failure explicitly.

## Foreground order — do not interleave

1. Dashboard scaffold + frozen codegen
2. `modal/services_b.py` — the moment Track A answers the App seam
3. Scenario execution wiring — the moment `services/oracle.py` lands

### 1. Dashboard — start now, zero Track A dependency

- Vite + React + TS under `apps/dashboard/**`; `npm run gen:types` reads
  `apps/contracts/schemas/**` — one codegen path, no hand-written client schema anywhere.
- Layout priority: state strip (incident id, state, live elapsed, SAFE_HOLD / Safe Stop) ·
  **money-truth ledger panel** (two captures for one intent, then one after activation) ·
  worlds/lifecycle panel (real sandbox ids, created/ready/finished/terminated, overlap
  graph) · **scenario matrix** (S01–S08 × candidates, invariant results, evidence ids) ·
  decision + selection basis · receipt view.
- The negative controls must appear in the matrix as **FAILING for the intended
  invariant**. That, plus the ledger, is the most persuasive thing on the screen.
- Rules: no fake data ever; empty states explicitly labelled; every number traceable to an
  event or an evidence id; `Cache-Control: no-store` on live views; SSE reconnect via
  `Last-Event-ID` once Track A's event route lands.

### 2. `modal/services_b.py` (after the seam)

One Sandbox per spec via `ModalWorld`; scoped provider token only; cleanup guaranteed in
`finally`; race failures become control events, never swallowed; `order_outputs=True` as
recorded in the plan (§12.1). Raise `max_containers` to match the number of worlds — never
reuse one world for two candidates.

### 3. Scenario execution

If `services/oracle.py` is not there yet, **report the blocker**. Never fake a pass.

## Report back

1. Commits + areas shipped
2. Dashboard: what renders now, and which panels are labelled empty
3. Codegen: exact command + how many types generated
4. Tests: ruff / mypy / pytest counts (+ frontend lint/build)
5. Real sandbox ids and lifecycle evidence (if `services_b` landed)
6. Blockers — each with the decision needed (Track A seam, oracle, control routes)
7. Next slice with its gate
