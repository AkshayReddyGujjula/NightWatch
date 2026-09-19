# Contract change requests

Track B appends requests here instead of editing files it does not own (plan §17).
Track A is the contract owner and implements or declines each request.

## 2026-09-19 — typed triage in `GeminiDiagnosis` (plan v1.5 §10.4)

**Requested by:** Track B (Akshay) · **Decision:** team decision 19 September, recorded
in `Final-nightwatch-plan.md` v1.5 §10.4 and §31.4 decision 11. **Do not implement on Track B.**

Jev cannot emit free text (verified live against `jev-1.13.0` at T+0), so triage
belongs to Gemini. Per §10.4, add a nested advisory block to `GeminiDiagnosis`:

- `category: Literal['payment_correctness','deploy_regression','infrastructure','security','unknown']`
- `severity: Literal['low','medium','high','critical']`
- `rationale: str` — at most 200 characters, referencing cited evidence IDs
- `confidence: float` — bounded 0–1

Rules (from §10.4): advisory only — never qualifies an incident, gates a candidate,
influences selection or touches the lease; renders as `MODEL_PROPOSED` on the dashboard
and in the receipt; a missing or malformed triage block fails the diagnosis closed
without blocking A/B.

**Impact on Track B:** none — no Track B code consumes these fields.

## 2026-09-19 — Track A reply: freeze decisions accepted; unsigned barrier release recorded

**By:** Track A (Jazil) · **Status:** recorded · **Wire impact:** none

All five freeze decisions in `apps/contracts/README.md` are accepted by both tracks
(Akshay reviewed, 19 September). One deviation from plan §9.1 wording is recorded here:

§9.1 says the barrier "releases a signed generation". The frozen implementation
authenticates the release with the scoped runner bearer token plus generation
monotonicity: every barrier endpoint already requires the scoped `FRAME_INGEST_TOKEN`
credential, the runners are inside the trust zone, and the generation counter is
monotonic and read back on every response. No signature field is added now; the wire
shape is unchanged from the frozen contract. If an explicit signature is wanted later,
it becomes an additive field at the next contract change.

## 2026-09-19 — Track B: shared Modal App seam for `modal/services_a.py` / `modal/services_b.py`

**Requested by:** Track B (Akshay) · **Owner:** Track A (Jazil) + shared shim · **Status:** proposed

`modal/services_a.py` does not exist yet, and the deployable entrypoint (`modal_app.py`,
Track B-owned shim, §16/§17 “function names frozen; import wiring only”) must compose both
tracks' functions into **one** `modal.App`. Proposed seam, so neither track invents one:

- `modal/services_a.py` defines the single `app = modal.App("nightwatch")` and binds its
  functions (`control_asgi`, `live_store_asgi`, `provider_asgi`, `orchestrate_incident`)
  to it;
- `modal/services_b.py` does `from modal.services_a import app` and binds `run_candidate`
  to that same app;
- `modal_app.py` is wiring only: `from modal.services_a import app  # noqa: F401` and
  `import modal.services_b  # noqa: F401`.

Exactly one module may own the App object; a second `modal.App` in one deployment would
silently split the app. If Track A prefers a different owner (e.g. the App defined in
`modal_app.py` itself and both modules importing it), either shape is fine as long as it is
exactly one.

**Impact on Track B:** `modal/services_b.py` is held until this is confirmed; the race
scheduler and world lifecycle do not depend on it.

## 2026-09-19 — Track B: add `.gitattributes` with `* text=auto` and `*.sh text eol=lf`

**Requested by:** Track B (Akshay) · **Owner:** shared repo root · **File:** `.gitattributes` (new)

Windows checkouts run with `core.autocrlf=true`, so a fresh `git checkout` rewrites
shell scripts to CRLF. `infra/start_desktop_world.sh` then fails inside the Linux
image with `/usr/bin/env: 'bash\r': No such file or directory` (observed live on a
Modal image build). Track B normalizes the file inside the image as a workaround, but
the durable fix is repo-wide:

```gitattributes
* text=auto
*.sh text eol=lf
```

so every Linux script (Track A's future ones included) survives a Windows checkout.
Impact on frozen wire contracts: none - checkout hygiene only.

## 2026-09-19 — Track A reply: Modal App seam and `.gitattributes` accepted

**By:** Track A (Jazil) · **Status:** accepted

1. **Modal App seam** — Track A accepts Track B's proposed shape exactly:
   `modal/services_a.py` owns the single `app = modal.App("nightwatch")` and binds
   `control_asgi`, `live_store_asgi`, `provider_asgi` and `orchestrate_incident`;
   `modal/services_b.py` does `from modal.services_a import app` and binds
   `run_candidate`; `modal_app.py` is import wiring only. `modal/services_a.py`
   lands in Track A's next slice (trusted-service deployment); the seam shape is
   frozen now so `modal/services_b.py` can proceed without waiting.

2. **`.gitattributes`** - accepted and applied by Track A in this commit:
   `* text=auto` and `*.sh text eol=lf`.

**Wire impact:** none.

## 2026-09-19 — Track B: import-mechanics correction to the frozen App seam (no Track A action)

**By:** Track B (Akshay) · **Status:** recorded · **Wire impact:** none

The seam *shape* is unchanged — `services_a.py` owns the single
`app = modal.App("nightwatch")`, `services_b.py` binds `run_candidate` to it,
`modal_app.py` is wiring only — but the literal spelling
`from modal.services_a import app` cannot resolve in this repository. The
installed `modal` SDK is a regular package and always shadows the repository's
`modal/` directory (a namespace portion). Verified live on this laptop:

```text
from modal.services_x import x  ->  ModuleNotFoundError: No module named 'modal.services_x'
import modal                    ->  <repo>/.venv/Lib/site-packages/modal/__init__.py
```

Mechanical correction, contained to Track B-owned files:

- `modal_app.py` inserts `<repo>/modal` on `sys.path` and imports `services_a`
  and `services_b` by top-level module name;
- `modal/services_b.py` imports `from services_a import app`.

`modal/services_a.py` needs **no change**: it still defines `app` and binds its
four functions; it imports nothing from Track B. Paths, ownership and the
one-App rule are untouched; no second `modal.App` may exist.

## 2026-09-19 - Track B: dashboard needs a frozen committed-results source (request)

**By:** Track B (Akshay) · **Status:** request · **Wire impact:** none yet (nothing invented)

Track B's dashboard data plumbing is in place (`apps/dashboard/src/api/**`): a typed
client whose response types are the generated modules, a fetch-based SSE subscriber
with `Last-Event-ID` replay, and a scenario-matrix read model that renders PASS/FAIL
including negative controls. Route paths come from plan §9.1
(`GET /api/incidents/{id}/receipt`, `GET /api/incidents/{id}/events`).

Two things only the contract owner can freeze before committed data can render:

1. **Evaluation results for the matrix (S01-S08 + NC-01/NC-02).** No frozen shape
   carries per-scenario `ScenarioResult` rows or negative-control outcomes with
   evidence ids - the receipt's `candidate_matrix` is candidate-level only. Track B
   will not invent a route or payload. Choose the shape (a route such as
   `GET /api/runs/{run_id}/evaluations`, or receipt fields) and Track B adjusts
   `apps/dashboard/src/api/**` only - no component changes.
2. **SSE frame convention.** Track B's client assumes each SSE `id:` is the committed
   `event_id` and each `data:` frame is strict `IncidentEvent` JSON (plan §9.1 says
   `Last-Event-ID` replay). Confirm or correct.

Until both land, every matrix cell stays `no result` / `not run` and the live panels
stay labelled-empty - no guesses. When the `IncidentSnapshot` / `SafeStopRequest`
schemas land, integration re-runs `npm run gen:types` before any client method is added.

## 2026-09-19 - Track B: ephemeral runs of the shared app need Track A's secret names in `nightwatch-b`

**By:** Track B (Akshay) · **Status:** environment note · **Wire impact:** none

`uv run modal run -e nightwatch-b modal_app.py` fails while loading the App:
`NotFoundError: Secret 'nightwatch-provider' not found in environment 'nightwatch-b'`.
The single shared app resolves every function's secret references, and
`nightwatch-b` currently holds only `nightwatch-typesafe` + `nightwatch-evidence-ingest`.
Track A's three names (`nightwatch-provider`, `nightwatch-live-internal`,
`nightwatch-control`) exist in `nightwatch-a` and `nightwatch-demo`.

An ephemeral `modal run -e nightwatch-demo` was tried and stopped: loading the
shared app also warms Track A's ASGI containers, which then crash-loop against the
deployed app's open SQLite files (`Volume.reload` conflicts; the deployed app was
not damaged and the ephemeral app is stopped). Track B's map gate therefore runs a
temp dev App in `nightwatch-b` that binds the same `run_candidate_impl` with only
`nightwatch-evidence-ingest`. Decision needed from Jazil: mirror the three secret
names into `nightwatch-b`, or record that ephemeral shared-app runs target
`nightwatch-demo` (with the volume-warm caveat above).
