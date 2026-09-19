# Track A handover — verified commit set and remaining critical path

**Date:** 2026-09-19 (afternoon, BST)
**Rebased on:** `ef653dd` — "Finish Track B runner and checkout lane"
**Pushed feature head:** `0c0fe8b` (this handover is committed on top; see `git log`)

This handover reports only work that was verified in this checkout. Anything
half-finished was left out rather than committed; there are no uncommitted
local leftovers (working tree clean).

---

## 1. Committed and pushed

| SHA | Subject | What it makes true |
| --- | --- | --- |
| `3311fa8` | Track A: provider demo-operator route arms a fresh double-charge namespace | `POST /internal/demo/double-charge` on the trusted provider (demo-operator token) creates a fresh namespace, registers one operation, arms `DROP_AFTER_CAPTURE_ONCE` and mints a 2 h scoped token. |
| `d72190a` | Track A: armable live-store showcase with trusted incident notice on the status page | `POST /internal/demo/arm-double-charge` on the live store arms a real intent/operation and CAS-switches the router to `BUGGY`; the buggy retry reads the provider ledger and the checkout response carries the "charged twice" notice; the storefront preserves it into the status page banner. |
| `20ba185` | Track A: bind live-internal secret to provider_asgi for demo arming | The deployed provider function receives `LIVE_INTERNAL_TOKEN` so `require_demo_operator` can authenticate the live store's arming call. |
| `0c0fe8b` | Track A: operator script to arm the deployed double-charge showcase | `scripts/arm_double_charge_demo.py` runs as documented from the repo root (repo-root `sys.path` shim added; without it the script crashed on import). |

Files touched: `apps/trusted_provider/app.py`, `apps/live_store/app.py`,
`apps/live_store/domain/checkout.py`, `apps/live_store/domain/payment_retry.py`,
`apps/live_store/provider.py`, `apps/storefront/assets/storefront.js`,
`modal/services_a.py` (provider secret binding only — Track A service wiring,
no Track B runner/frames/dashboard paths), and the matching tests
(`tests/integration/test_provider_http.py`,
`tests/integration/test_live_store_checkout.py`,
`tests/integration/test_storefront_static.py`,
`tests/unit/test_payment_retry.py`,
`tests/fault_injection/test_g0_duplicate_capture.py`, `tests/helpers.py`),
plus `scripts/arm_double_charge_demo.py`. No secrets in any commit.

## 2. Not committed

**None.** After the four commits above the working tree is clean; there are no
stashed or local changes. Every unfinished piece below is a pre-existing,
deliberate stub/omission in the committed tree, not leftover work from this
session.

## 3. Verified vs unverified

**Ran in this checkout, on the rebased tree (`0c0fe8b`):**

- `uv run ruff check .` — **all checks passed** (repo-wide; Track B's
  `ef653dd` fixed the two probe-script lint errors that were red before it).
- `uv run mypy apps services` — **clean**, 48 source files.
- `uv run pytest -q` — **168 passed**.
- Composed app builds: `import modal_app`, `import services_a, services_b`,
  and instantiation of the provider, live-store and control-plane app
  factories (`create_app(...)`) all succeed.
- End-to-end local run with real HTTP servers (uvicorn, provider on `:19101`,
  store on `:19100`, test tokens): ran
  `scripts/arm_double_charge_demo.py --store-url http://127.0.0.1:19100`;
  it printed the fresh namespace, `Router mode: BUGGY` and the X/Y checkout
  URLs; `POST /api/checkout/{intent}` returned `PAID` with
  `"trusted payment provider recorded 2 captures … You were charged twice."`;
  the provider ledger showed **exactly two captures under two distinct
  idempotency keys**.

**Not verified (and therefore not claimed):**

- No deploy, no Modal image build, no run against the `nightwatch-demo`
  environment. The new arm route and notice do **not** exist remotely until
  Jazil redeploys `live_store_asgi` and `provider_asgi`.
- No browser/Jev/CUA/frames execution; no orchestration
  `POST /api/incidents/{id}/run` (it still escalates, see below); no candidate
  race.
- Storefront notice verified at the static-asset and HTTP-response level only,
  not in a real browser.
- The script was exercised against local services, not the deployed URL.

## 4. Critical path remaining, in order

1. **Real capsule source behind `POST /run`** — MISSING.
   `apps/control_plane/orchestration.py`: `UnavailableCapsuleSource` (~L48-52)
   is wired by `build_default_orchestrator` (~L372-386); `public_routes.py`
   `run_incident` (~L78-102) reaches it and escalates. Raw material exists:
   `services/capsule.py::build_capsule` (test-only), provider
   `GET /internal/ledger/{namespace}`, store `GET /internal/state/{intent_id}`.
2. **Detector-backed incident trigger** — MISSING.
   `services/detector.py::detect_duplicate_capture` exists but only
   `scripts/g0_gate.py` and tests call it; no route. `CONTROL_EVENT_TOKEN` is
   defined and unused (`apps/control_plane/config.py`). Needs a trigger route
   (`apps/control_plane/public_routes.py`) or store-side notification, plus a
   script.
3. **`GEMINI_MODEL` reaching the deployed app** — CONFIG, UNVERIFIED.
   `apps/control_plane/config.py:21` (`gemini_model: str = ""`);
   `services/gemini_agent.py` returns `GEMINI_UNAVAILABLE:NO_MODEL` when empty;
   secret `nightwatch-gemini` is bound to `control_asgi`
   (`modal/services_a.py`). **Modal cannot read secret values back** — the
   deployer must confirm `GEMINI_MODEL` is present in `nightwatch-gemini`
   (and set `GOOGLE_API_KEY`). Local `.env` has `GEMINI_MODEL` empty.
4. **Frame changes** — MISSING server-side.
   `apps/control_plane/app.py:37` still sets `app.state.frames =
   ReferenceSink(...)` → swap in `services/frames/store.py::FrameStore`;
   `apps/control_plane/routes.py:219-262` (`/internal/frames`) discards image
   bytes (`accept_frame(frame)` without `image=`) → forward the bytes; the
   latest-frame route is absent → add
   `GET /api/runs/{run_id}/frames/{candidate_id}/latest?after={seq}` in
   `apps/control_plane/public_routes.py` (dashboard expects it in
   `apps/dashboard/src/api/routes.ts:27-32`). Pillow is now a dependency and in
   `RUNNER_IMAGE` (Track B `ef653dd`). `services/frames/sampler.py` and
   `uploader.py` are still uncalled.
5. **`CandidateId` widened to 5-6 ids + classifier, schemas regenerated** —
   MISSING. `apps/contracts/base.py:42` is `Literal["A", "B", "C"]`;
   consumers include `apps/control_plane/routes.py`
   (`DEFAULT_EXPECTED_CANDIDATES`), scheduler/selector paths, generated
   schemas (`apps/contracts/schemas/*.json` via `scripts/gen_schemas.py`) and
   dashboard types (`npm run gen:types`). Requested in `CONTRACT_CHANGE.md`.
6. **Runner seam** — PARTIAL, advanced by Track B `ef653dd`:
   real Candidate B bundle + uvicorn boot (`services/worlds/payload.py`),
   `ScenarioSuite` + `Oracle` injected in
   `modal/services_b.py::run_candidate_impl`, `scenario_results` carried by
   `services/worlds/runner.py`. Remaining:
   (a) candidate A previous-release source/ref — `payload.py` raises
   `CandidatePayloadUnavailable` for `ROLLBACK`; (b) candidate C guarded patch
   bytes; (c) deterministic seed bytes (candidate DB is created fresh at
   boot); (d) base-URL injection so `ScenarioSuite` drives the app inside the
   sandbox — `execute_scenarios` in `modal/services_b.py` currently ignores the
   world and runs the in-process ASGI suite.
7. **Receipt generator / working evaluations route / dashboard served from
   `control_asgi`** — MISSING. No `RepairReceipt` producer (contract
   `apps/contracts/lease.py`; `ControlStore.save_receipt` in
   `services/control_store.py` unused, so the route 404s);
   `GET /api/runs/{run_id}/evaluations` reads `ControlStore.evaluations` while
   the orchestrator writes `candidate_evaluations`
   (`apps/control_plane/orchestration_store.py:97-137`); the dashboard `dist/`
   is not mounted (`apps/control_plane/app.py`, `modal/services_a.py`).
8. **Canary/staged smoke and lease guardian** — MISSING. No
   `services/canary.py`, no `services/lease_guardian.py`; `rollout_pct`
   already exists in `apps/live_store/router.py` (plan §14.2/14.3).
9. **Patch guard + C patch bytes; S09/S10 security scenarios** — MISSING. No
   `services/patch_guard.py`; `services/gemini_agent.py` returns
   `C_SKIPPED_PATCH_GUARD_NOT_WIRED`; `PatchProposal` contract exists
   (`apps/contracts/incident.py`); S09/S10 are not in
   `fixtures/scenarios.json`.

## 5. Known broken or risky — do not demo

- `POST /api/incidents/{id}/run` on the deployed control plane escalates with
  `CAPSULE_UNAVAILABLE` (no real capsule source). Do not show a live run
  before item 4.1 lands.
- The deployed live store/provider still run older code: the arm route and the
  visible notice do not exist remotely until `live_store_asgi` **and**
  `provider_asgi` are redeployed (the latter for the new secret binding).
- `GEMINI_MODEL` is empty locally and unverifiable remotely; Gemini will
  report `GEMINI_UNAVAILABLE:NO_MODEL` until the secret is confirmed.
- Candidate A currently errors (payload unavailable) and C is
  `SKIPPED_INVALID`; only B can pass, and its scenarios run in-process rather
  than against the sandbox app.
- Browser/Jev path: no TypeSafe SDK in any image and no frame-bytes route, so
  there is no live browser evidence or splitscreen. Track B's email-input
  mitigation (`type="text"` in `apps/storefront/checkout-*.html`) is committed
  but was not live-verified here.
- `_provider_base_url` in `apps/live_store/app.py` falls back to replacing the
  `nightwatch-live-store-asgi` hostname marker; any non-matching host must set
  `PROVIDER_BASE_URL` explicitly or arming fails closed with 503.
- Stale claims to avoid: `apps/dashboard/src/components/BrowserBlockerPanel.tsx`
  and plan §11.8 still describe browser "REDUCED" mode while
  `infra/BROWSER_STACK_NOTES.md` records the isolated route as green — that
  panel is Track B's lane and is not updated here.
