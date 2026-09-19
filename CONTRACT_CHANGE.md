# Contract change requests

Track B appends requests here instead of editing files it does not own (plan §17).
Track A is the contract owner and implements or declines each request.

## 2026-09-19 — public control API and committed evaluation source frozen

**By:** Track A (Jazil) · **Status:** accepted · **Wire impact:** additive

The requested dashboard source and SSE convention are now frozen:

- `GET /api/runs/{run_id}/evaluations` returns strict `EvaluationResults`,
  containing committed `ScenarioResult` rows and typed negative-control rows;
- SSE `id` is exactly the already-committed `IncidentEvent.event_id`, and SSE
  `data` is the strict `IncidentEvent` JSON;
- additive `IncidentSnapshot`, `SafeStopRequest`, and `WorldHealth` contracts
  freeze the remaining public routes from the control API inventory.

The server persists every event before it can be observed by an SSE subscriber.
`POST .../run` is incident-idempotent and performs a SAFE_HOLD write/readback
before any later orchestration may begin.

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

## 2026-09-19 — Track B: `CandidateId` must admit `C1..CN` for the 5–6 world race (request)

**By:** Track B (Akshay) · **Status:** request · **Wire impact:** frozen type widens; no route change

Plan §12.1 explicitly requires raising `max_containers` when extra worlds are
added, and the Track B checkpoint asks for a 5–6 world `map.aio` race. The frozen
contracts currently block it: `apps/contracts/base.py` defines
`CandidateId = Literal["A", "B", "C"]` and `CandidateSpec`'s validator
(`apps/contracts/incident.py`) indexes a fixed table by `candidate_id`, so any
`C1..CN` id raises before a world can be created. Track B request:

1. widen `CandidateId` to a bounded pattern such as `^[A-Z][A-Z0-9]{0,7}$`;
2. in the validator, map `A`/`B` exactly as today and treat any `C`-prefixed id
   (`C`, `C1`, …, `CN`) as `GEMINI_PATCH` at rank 2 — rank semantics are
   unchanged, the suffix only names a distinct patch;
3. expected-candidate sets therefore derive from the actual spec ids (the
   barrier `expect()` already takes a candidate list, so no route change).

Until this is accepted, Track B's six-world scale proof uses two waves of the
three frozen slots (`A`, `B`, `C`) with distinct provider namespaces and records
that limitation honestly; the runner, isolation and overlap evidence are real
either way. Track B makes no claim about racing six distinct candidate ids until
the contract admits them. No Track B code edits a contract file.

## 2026-09-19 — Track B: frame-store swap + frame-bytes read route (integration request)

**By:** Track B (Akshay) · **Status:** request · **Wire impact:** one additive public route needed

Two integration points only the control-plane owner can complete. Track B has
implemented its side; no Track A code is edited by Track B.

1. **Sink swap (no wire change).** `apps/control_plane/app.py` currently sets
   `app.state.frames = ReferenceSink(...)`. Track B's drop-in replacement is
   `services.frames.store.FrameStore`; it preserves the exact sink surface and
   error classes (`UnknownRunError`, `SequenceRegressionError`,
   `ReadySetMismatchError`, `SessionHashMismatchError` imported from
   `apps.control_plane.routes`), so the existing route status mapping is
   unchanged. It additionally keeps one latest frame (metadata + bytes) per
   `(run_id, candidate_id)` in memory and fans out metadata to bounded
   subscribers. Track B has an end-to-end test that assigns
   `app.state.frames = FrameStore(...)` and posts real multipart frames through
   the frozen `/internal/frames` route; the existing
   `tests/integration/test_internal_frames_contract.py` is unchanged and must
   stay green with the swap.
   Requested wiring: `create_app` constructs `FrameStore(timeout_seconds=barrier_timeout_seconds)`
   (Track A's call, Track B takes the edit if you prefer). **One-line route
   change required for the wall:** `FrameStore.accept_frame(frame, image=None)`
   accepts the validated bytes, but `ingest_frame` currently calls
   `sink.accept_frame(frame)` after validation, so HTTP-ingested frames would
   hold an empty image slot. Pass `image=bytes(payload)` at that call and the
   bytes flow to the frame-bytes route without any other change.

2. **Frame-bytes read route for the dashboard wall (additive).** The wall needs
   the plan §11.7 route `GET /api/runs/{run_id}/frames/{candidate_id}/latest?after={seq}`
   returning `image/jpeg` (or `image/webp`) bytes with `Cache-Control: no-store`
   and operator bearer auth like the other `/api` reads. Statuses: `200` bytes
   plus an `X-Frame-Seq: <frame_seq>` response header; `404` when no frame exists
   for that `(run, candidate)`; `409` (or `204`) when `after` is not older than
   the latest seq — please prefer `409`/`204` over `404` there so the wall never
   confuses "no frame" with "nothing newer". Requested header name is
   `X-Frame-Seq`; if the contract prefers another name, say so and Track B
   changes only `routes.ts` + `src/api/frames.ts`. The bytes come from the same
   `app.state.frames` store (`latest(run_id, candidate_id, after_seq)`), never
   from the runner and never from SQLite. Until both (1) and (2) land — the swap
   *and* the byte-forward — the committed bytes slot is empty and the wall stays
   in its labelled `no committed frame source yet` state; the submission makes no
   claim about live frames in the committed control plane before then.

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
