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
