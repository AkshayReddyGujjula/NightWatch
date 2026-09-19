# Track B — BROWSER HERO build prompt (Akshay's laptop, one agent)

You are the Track B "hero" agent for NightWatch on Akshay's laptop: the browser-race showcase
(Jev + CUA driving real browsers in parallel Modal Sandboxes), the frame store and the
split-screen dashboard wall. Read this entire file before acting. A second agent (Track A) is
working in parallel on the engine from Jazil's laptop — never edit Track A paths.

## 0. What NightWatch is (30-second version)

NightMart, a synthetic storefront, fails silently: checkout returns HTTP 200 while a lost payment
response makes the buggy retry path capture the same payment twice. NightWatch detects it from a
trusted, append-only provider ledger outside the candidate app, contains it (SAFE_HOLD), freezes
an incident capsule, asks Gemini for a typed diagnosis and several bounded patch proposals, races
every candidate repair in an isolated Modal Sandbox world, grades each with a deterministic
oracle from trusted evidence only, activates the best passing repair under a time-limited repair
lease, and emits an engineer receipt. A cybersecurity incident (SQL injection and/or
malformed-payload crash/downtime) follows the same pipeline. Models propose; deterministic code
decides.

Your lane is the main showcase: Jev running MANY sessions concurrently — 5–6 isolated Modal
Sandboxes, each driving a real browser — shown on a split-screen wall with live frames, real
sandbox IDs, measured overlap and per-candidate PASS/FAIL.

## 1. Ground rules (non-negotiable)

- Evidence only. Never fake a frame, a screenshot, a sandbox or a browser journey. If the driver
  cannot be unblocked inside the timebox, label `ERROR_BROWSER_STACK` and move on.
- You do NOT deploy. Jazil is the only deployer. For probes use ephemeral runs in
  `nightwatch-b` with a Track B-only dev app binding `run_candidate_impl` — do NOT import
  `services_a` (its secret names do not exist in `nightwatch-b`). Never run ephemeral apps in
  `nightwatch-demo`: they warm the production ASGI containers and contend on the volumes.
- The TypeSafe/Jev key lives in the runner container; it must NEVER enter a candidate sandbox.
  Record model version, confidence and raw probabilities on every decision.
- No Playwright anywhere.
- Track B paths: `services/worlds/**`, `services/scheduler.py`, `services/jev/**`,
  `services/frames/**`, `apps/dashboard/**`, `apps/storefront/**`, `infra/**`,
  `modal/services_b.py`, `modal_app.py`, `scripts/smoke_map_race.py`,
  `scripts/verify_browser_stack.py`, `tests/isolation/**`.
- Never edit Track A paths: `apps/contracts/**` (request changes in `CONTRACT_CHANGE.md`),
  `apps/live_store/**`, `apps/trusted_provider/**`, `apps/control_plane/**` (the ReferenceSink
  swap is Track A's wiring), `modal/services_a.py`, `services/detector.py`, `services/capsule.py`,
  `services/oracle.py`, `services/selector.py`, `services/canary.py`,
  `services/lease_guardian.py`, `services/gemini_agent.py`, `services/patch_guard.py`,
  `fixtures/**`, `scripts/gen_schemas.py`.
- Git: `git pull --rebase` immediately before every push; no force push; scoped commits. If a
  rebase conflicts in a Track A-owned file, stop and report.

## 2. Start here

- `cd` to the repo; `git pull --rebase`; confirm HEAD >= `928831a`; `git status --short` is clean
  (the two prompt files may show as untracked — leave them).
- Read first: `infra/BROWSER_STACK_NOTES.md`, plan §11.8 and §31.4 decision 13,
  `services/worlds/**`, `services/scheduler.py`, `infra/start_desktop_world.sh`,
  `infra/cua_capabilities.json`, `scripts/verify_browser_stack.py`, `scripts/smoke_map_race.py`,
  `apps/dashboard/README.md`.
- What exists: the desktop image builds and boots (Xvfb, Openbox, D-Bus, AT-SPI, Chrome 153,
  CUA Driver 0.28.2 bounded); session + isolated launch + exact binding were proven in round 3;
  the real 3-sandbox `map.aio` race is proven (peak 3, 3.96 s all-alive window); the dashboard
  shell, typed client and SSE subscriber are built; the storefront assets exist and are served
  by the live store.
- What is blocked (and the root cause): the driver's isolated browser hardcodes `about:blank`
  and the origin-scoped manifest refuses typed navigation/observation from an opaque origin; the
  existing-profile setup path failed on our Chrome 153 world. There is NO driver-version fix —
  0.28.3 nightlies are docs-only. Do not chase versions. The fix is in Task 1.

## 3. Tasks

### Task 1 — Browser unblock probe (start now; HARD STOP 16:15)

Goal: a real typed browser journey inside one Modal sandbox, on the allowed origin
(`http://127.0.0.1:8080/`).

ROUTE A (preferred): in `infra/start_desktop_world.sh`, add `--remote-debugging-port=0` to the
Chrome launch (keep the absolute `--user-data-dir=/run/nightwatch/chrome-profile` and the start
URL). Then, inside the sandbox:

- read `/run/nightwatch/browser.json` for `pid` and `window_id`;
- call `browser_prepare`:
  `cua-driver call browser_prepare '{"session":"probe","strategy":{"kind":"existing_profile"},"pid":<pid>,"window_id":<wid>}'`
- expect: `prepared: true`; `endpoint_ownership` present; `side_effects` all false
  (`opened_setup_page`, `closed_setup_page`, `focused_setup_address_field`,
  `enabled_remote_debugging`, `used_bounded_pixel_fallback`, `foregrounded_window`,
  `injected_global_input`);
- then `get_browser_state` with `snapshot_format: "semantic_v2"`; expect `binding_quality:
  "exact"`, `mutation_allowed: true`, URL on the allowed origin, non-empty semantic elements.

Why it should work: the Linux driver reads `/proc/<pid>/cmdline` -> `--user-data-dir` ->
`<dir>/DevToolsActivePort` -> proves the loopback listener belongs to the pid tree -> attaches
with zero side effects ("existing endpoints are detected without side effects"). Upstream issue
#3239 documents exactly this flow succeeding on Linux X11.

ROUTE B (fallback, if A fails after ~30 min): let the driver launch its isolated browser
(`about:blank`); read the profile dir from `/proc/<pid>/cmdline`; read `DevToolsActivePort`; open
a CDP WebSocket to the page target and send ONE `Page.navigate` to the allowed origin; then use
the typed tools. Record this one-hop deviation honestly.

Evidence required: raw `browser_prepare` JSON, raw `get_browser_state` JSON, >= 1 screenshot
(hash + byte size), sandbox id, timings, clean teardown.

If not green by 16:15: set the reduced label, report, and move to Task 3 — do not keep grinding.

### Task 2 — Jev atom (after Task 1 green; target 16:45)

- One real TypeSafe call from the runner container over bounded action IDs derived from the
  semantic snapshot (include `reobserve` and `abstain`); record choice, confidence,
  probabilities, `model_name`.
- Execute the chosen action through typed driver tools; then take a FRESH snapshot and verify the
  postcondition (URL or element state change). Low margin -> reobserve once -> abstain.
- Capture >= 3 screenshots with timestamps and distinct hashes; save the full decision / action /
  verification JSON. This is the "Jev drives a browser in a Modal sandbox" proof.

### Task 3 — Frames + split-screen wall (start even if Task 1 is still failing)

- Implement `services/frames/**`: latest frame per `(run, candidate)`, strictly monotonic
  `frame_seq`, SSE fan-out; frame uploader posts multipart to `POST /internal/frames` with the
  scoped `FRAME_INGEST_TOKEN` (frozen contract in `apps/contracts/README.md`).
- Sampler: `get_browser_state(include_screenshot=true)` at >= 1 fps per active world (target 2);
  freshness from `captured_monotonic_ns`; stale frames never satisfy cadence.
- Dashboard wall: N tiles streaming REAL frames, each labelled with candidate id, sandbox id,
  Jev decision/confidence, executed action, verification result, PASS/FAIL; wire
  `GET /api/runs/{run_id}/evaluations` and the receipt once Track A's routes return data. Every
  cell stays labelled no-result until real data exists.
- Integration: `apps/control_plane` currently uses a `ReferenceSink` stand-in; file the swap
  request in `CONTRACT_CHANGE.md` (Track A wires it) — do not edit control paths.

### Task 4 — Scale to 5–6 worlds

- `modal/services_b.py`: raise `run_candidate` `max_containers` to 6–8; `map.aio` over all
  candidates (A, B, C1..CN) with `order_outputs=True, return_exceptions=True`.
- Per-world isolation: own scenario DB file, own provider namespace + short-lived token, own
  Chrome profile, own CUA session; the Jev key stays in the runner.
- Extend the browser barrier expected-candidate set; record real sandbox IDs, UTC lifecycle
  timestamps, measured overlap (never the requested number), image digests, all terminations.
- Coordinate with Track A: when `services_b` changes are ready, tell them to pull + deploy the
  composed app; then smoke the deployed runner via
  `modal.Function.from_name("nightwatch", "run_candidate").map(...)`.

## 4. Time plan (submission 19:00, live demo 20:00; it is ~15:05 now)

- 15:05–16:15 Task 1 (hard stop).
- 16:15–16:45 Task 2 (Jev atom) if Task 1 is green.
- 16:30–18:00 Task 3 (frames + wall), starting regardless.
- 17:30–18:30 Task 4 (scale to 5–6).
- 18:30–19:00 integration + rehearsal-ready; submit 19:00; live demo 20:00.

## 5. Report format at every checkpoint

1. Commit SHAs pushed + what changed.
2. Browser probe: raw `browser_prepare` JSON, `get_browser_state` JSON, screenshot hashes, sandbox
   id, timings; or the honest reduced label with the exact refusal text.
3. Jev atom: decision JSON (choice, confidence, probabilities, model), action, fresh-snapshot
   verification, screenshot hashes.
4. Frames/wall: measured frame cadence from real timestamps, screenshot hashes, dashboard state.
5. Scale: sandbox IDs, measured overlap, termination proof.
6. What failed and its label, blockers, next slice.

Stop and report at each checkpoint. Never fake a frame or a journey.
