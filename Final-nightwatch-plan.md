# NightWatch: final six-hour build and architecture plan

**Version:** 1.6, 19 September 2026 — folds in the browser-stack outcome and verified CUA facts (§11.6, §11.8), the `order_outputs=True` correction (§12.1), and decision 13 in §31.4  
**Status:** implementation-ready; Section 2 is the frozen default unless Akshay and Jazil explicitly change it before the T+0:20 contract freeze  
**Team:** two builders — **Jazil owns Track A** (domain, trusted authority, Gemini, proof) and **Akshay owns Track B** (Modal, Jev/CUA, dashboard). One laptop/branch owns each whole track; no path is edited by both.  
**Build window:** T+0 to T+6h from whenever coding actually starts; T+6h to T+7h is submission, recording, secret-scrub and rehearsal time. Fixed anchors, whatever T+0 turns out to be: **19:00 submission** and **20:00 live demo**.  
**Authoritative scope:** this document supersedes conflicting implementation details in `PLAN.md` and `flow.md`

---

## 0. The decision in one page

### Product

NightWatch is an agentic incident first responder for a failure that ordinary uptime monitoring misses. The demo store returns HTTP 200 and looks healthy, but a lost payment response makes the buggy retry handler create a fresh idempotency key and capture the same logical checkout twice.

NightWatch:

1. detects the money invariant violation from a trusted, append-only mock payment ledger;
2. immediately puts **new synthetic checkouts** into `SAFE_HOLD` so the original evidence is preserved and no more captures occur;
3. freezes a reproducible incident capsule;
4. asks Gemini for a typed diagnosis and a bounded one-file patch proposal;
5. launches exactly three isolated candidate worlds concurrently on Modal;
6. lets Jev make narrow, typed browser-action choices while CUA Driver observes and executes them in an isolated Chromium profile against two deliberately different checkout UIs;
7. grades every candidate with deterministic Pydantic-validated invariants using trusted evidence outside the candidate;
8. chooses the lowest-risk eligible repair by code, not by an AI confidence score;
9. activates a preinstalled safe retry handler in the live demo using a time-limited repair lease; and
10. produces a tamper-evident engineer receipt that distinguishes prior harm, future containment, tested evidence and unresolved work.

The audience should understand the differentiator in one sentence:

> **The website said success; the ledger said the customer paid twice. NightWatch contained the blast radius, raced three repairs in isolated worlds, and only activated the repair that independent evidence proved safe.**

### The three candidates

| Candidate | What runs in its Modal Sandbox | Purpose | May be activated live? |
| --- | --- | --- | --- |
| **A: known-good release** | Previous app artifact | Establishes that the incident is a release regression and provides comparative evidence | **Yes, route-only, when tested.** The previous release's handler is installed as the hash-verified `LEGACY` route and becomes live-eligible under the identical gate if it is built and tested by Gate G3. Container redeploy and data/schema migration remain out of scope. |
| **B: prepared safe handler** | Current artifact with `payment_retry_handler=safe` | Lowest-risk containment: retain current app and state but inquire after an uncertain capture instead of charging again | **Yes.** The same handler is preinstalled and hash-verified in the live app. |
| **C: Gemini patch** | Current artifact plus a validated one-file diff | Shows real diagnosis and code generation; supplies a proposed permanent repair | **No.** It is tested and handed to an engineer, never automatically merged or deployed. |

If B does not pass every required gate, NightWatch remains in `SAFE_HOLD` and escalates. It never silently falls back to the known-bad handler.

### Why this can win

- **Main-track story:** financially meaningful silent failure, real multi-agent investigation, real code and real evidence, with a safety boundary judges can interrogate.
- **Best use of Modal:** Modal hosts the trusted services, runs three actual sandbox worlds concurrently, gives each world authenticated connectivity, and exposes measured lifecycle/concurrency evidence.
- **Best use of Pydantic:** every external or model boundary is a strict schema; Gemini produces typed hypotheses and a patch proposal; Jev returns typed candidate actions; malformed outputs are visibly rejected; the state machine, invariants, lease and receipt are typed.
- **Google DeepMind:** Gemini analyses a frozen incident capsule and proposes a bounded patch. It is useful without being allowed to grade or deploy its own work.
- **TypeSafe/Jev + CUA:** Jev is the bounded semantic action selector; CUA Driver is the observation/execution transport. They already have an official `jev-use` composition. The app retains URL, freshness, value and postcondition authority.

### What is explicitly not being built

No SQL injection or IDOR scenario on the critical path (it may exist only as a gated post-freeze playbook started after the core demo is frozen and rehearsed, with its own oracle, and it may never delay or weaken the payment story), no real payments, real customer data, arbitrary shell agent, automatic generated-code deployment, database migration engine, automatic refunds, mobile app, generic SRE platform, or live Conduct integration without verified access. Those ideas belong in the roadmap or the gated playbook, not in the six-hour critical path.

---

## 1. Event and delivery constraints

These are confirmed from the supplied event page and screenshots:

- competition opt-in/submission deadline: **19:00**;
- live demos: **20:00**; awards: **20:45**;
- team limit: five people; this plan assumes two;
- minimum two listed partner technologies;
- project must be created at the hackathon; boilerplates are allowed;
- submission needs a public source repository, comprehensive setup/install README, APIs/frameworks/tools documentation and enough technical documentation for the jury;
- presentation needs a **two-minute recorded demo**, detailed explanation and live feature walkthrough;
- listed technology partners are Google DeepMind, Modal and Pydantic;
- side challenges shown are Best Use of Modal and Best Use of Pydantic, each advertised at €1,500.

The team-supplied judging rubric is **50% technical depth, 20% creativity, 30% uniqueness and solving a real problem**, with advertised side prizes **Best Use of Modal** and **Best Use of Pydantic**. Optimise explicitly for those weights: correctness and technical depth first, then a novel and clearly stated framing, then partner technologies that are load-bearing rather than decorative. Where the rubric is silent, do not invent extra claims.

---

## 2. Frozen scope decisions

These are explicit plan decisions, not hidden assumptions. Ownership is assigned (Jazil = Track A, Akshay = Track B). Change another row only by recording the reason before the T+0:20 contract freeze; do not redesign after it.

| Choice | Recommended default | Alternatives and consequence |
| --- | --- | --- |
| Final incident | **Duplicate-payment incident in this document** | Choosing the older SQL-injection story invalidates most of this plan and is not recommended. |
| Ownership | **Jazil = Track A; Akshay = Track B** | Fixed for the day. If you must swap, swap laptops and keys — never file ownership mid-build. |
| Optional services | **Modal, Gemini, Jev and CUA Driver are required; hosted Logfire optional; Conduct stretch-only** | Jev + CUA is the only browser stack. If its preflight fails, browser scenarios remain failed/omitted while the team fixes that stack; no substitute browser controller is introduced. |

Known access: Akshay holds the Google AI Studio Gemini key and the TypeSafe Jev key. The hackathon Modal credits live on **Jazil's workspace**, and **Jazil is the sole designated deployer**. The Gemini key is shared to Jazil's laptop because Track A needs it; the Jev key stays on Akshay's because Track B needs it. Logfire and Conduct access must be proven at the T+0:20 preflight; the document does not assume unverified credentials.

---

## 3. Success definition and demo modes

### 3.1 Full-demo acceptance contract

The build may be called the **full NightWatch demo** only if one clean recorded run proves all of the following:

- the buggy live store returns HTTP 200 and creates two captures for one logical intent under `DROP_AFTER_CAPTURE_ONCE`;
- the original provider namespace and harmed order remain visible and unchanged after reproduction;
- `SAFE_HOLD` prevents new captures before experiments begin;
- three distinct Modal Sandbox IDs exist for A, B and C;
- at least two candidate workers overlap in measured running time, with target peak concurrency three;
- each candidate uses a distinct app database, provider namespace, scoped provider token, Chromium process/profile and CUA Driver session **inside that candidate's own Modal Sandbox**;
- all three browser tiles display frames captured from those three real CUA sessions at a measured minimum of 1 fresh frame/second per active tile, targeting 2 frames/second, with stall detection rather than replayed animation;
- Gemini returns a schema-valid diagnosis and Candidate C diff that passes the patch guard, allowing C to start as the third real world; an invalid/skipped C can never be called full mode, and its dashboard tile must be a labelled placeholder with no screenshot;
- real Jev responses choose actions in both UI variants; selected actions and returned model version are recorded;
- CUA Driver uses world-local isolated Chromium profiles, snapshot-bound semantic references and independently verified postconditions for the recorded hero journeys;
- S01–S08 execute for each eligible candidate, and every claimed pass has trusted ledger plus app-state evidence;
- both negative controls fail for the intended invariant;
- deterministic policy selects the lowest-ranked live-eligible candidate that passes every required gate (B, or `LEGACY` if B fails);
- staged smoke, lease issuance, router readback and guardian checks succeed;
- Safe Stop is demonstrated and can never re-enable the buggy path;
- the receipt names the already harmed intent, the newly protected scope, candidate outcomes and unresolved work;
- the end-to-end run is repeated twice after the last material change.

A frame-stream or stall failure in one world degrades that world's **display and browser evidence** claim only. It never changes a candidate's invariant verdict, which is decided from the trusted ledger and app state alone (see §13.2). Say that out loud instead of letting a stalled tile imply a payment failure.

### 3.2 Core-demo contract

If time or an external API prevents the full contract, ship a truthful **core demo**:

- one real duplicate capture;
- immediate `SAFE_HOLD`;
- Modal candidates A and B concurrently;
- S01, S02 and S08 plus both negative controls;
- deterministic selection and activation of B;
- at least one real Jev-driven UI journey if Jev is available;
- a receipt whose `demo_mode` and `degraded_reasons` list everything omitted.

Do not claim a browser-agent result when Jev + CUA did not run, a Modal Sandbox win when local processes ran it, three candidates when C did not finish, or full S01–S08 evidence when only the core suite ran.

### 3.3 Non-functional targets

| Property | Target | Interpretation |
| --- | --- | --- |
| Detection-to-containment | `<180 s` engineering target, applies only to `DETECTED -> SAFE_HOLD` | The 180-second figure is budgeted for containment, not the whole pipeline. Measured with monotonic timestamps; never converted into a fake pass. |
| Full incident-to-lease run | measured against the §14.4 sub-5-minute target; never promised | Report the real number in the receipt and the video; a miss is reported, not hidden. |
| Duplicate containment | Before candidate launch | `SAFE_HOLD` write and readback precede any experiment. |
| World concurrency | peak `>=2`, target `3` | Derived from Modal lifecycle timestamps, not dashboard animation. |
| Browser evidence cadence | minimum `1 fps`, target `2 fps` per active world | Derived from `BrowserFrame.captured_monotonic_ns`; stale/replayed frames never satisfy it. |
| Reproducibility | two clean post-freeze runs | Same frozen capsule/hash, new run IDs and provider namespaces. |
| Secrets | zero in repo, UI, receipts and candidate sandboxes | Automated secret scan plus manual screenshot check. |
| State integrity | original ledger immutable | Resets create new namespaces; they never delete the original. |

---

## 4. System context and trust boundaries

```text
                                 TRUSTED CONTROL ZONE
 Operator/browser
       |
       v
 +------------------+       spawn       +--------------------------+
 | Modal control    |------------------->| Modal orchestrator       |
 | ASGI + dashboard |<--signed events----| function                 |
 | sole control DB  |                    +------------+-------------+
 +---+-----------+--+                                 |
     |           |                      map.aio(A, B, C) concurrently
     | lease     |                                   |
     v           |                      +------------+-------------+
 +---------------+---+                  | 3 trusted candidate      |
 | Modal live store  |                  | runner functions         |
 | ASGI + live DB    |                  | Jev key stays here       |
 | buggy/safe router |                  +--+-----------+----------+
 +---------+---------+                     |           |
           | scoped capture                | creates 1 | each
           v                               v           v
 +--------------------+              +-----------------------------+
 | Modal mock payment |<-------------| 3 DESKTOP MODAL SANDBOXES |
 | provider ASGI      | scoped tokens| A | B | C                  |
 | append-only ledger |              | candidate app + DB         |
 +----------+---------+              | Xvfb + Chromium + CUA     |
            ^                        | Driver; no model secrets   |
            |                        +-----------------------------+
            |                                      ^
            | evaluator-only read                  | Sandbox.exec calls
            +---------------- trusted oracle ------+ from trusted runners

 Each runner: CUA semantic snapshot -> bounded actions -> Jev Choice
              -> freshness check -> CUA action -> trusted oracle
              -> exact screenshot frame -> dashboard frame stream
```

### 4.1 Trust rules

1. Candidate app code is untrusted even when Gemini did not write it.
2. The provider ledger, evaluator/oracle, scenario definitions, fixture, hashes, policy and lease code are never inside the candidate image or writable mount. The candidate app and desktop controller share a Modal Sandbox but run as different OS users; their observations are not authoritative evidence.
3. Gemini and Jev have no live control-plane credential, evaluator credential, Modal token or deployment tool. A candidate holds no secret except short-lived provider tokens: one token per scenario namespace, scoped to the exact run/candidate/scenario, operation IDs and expiry, and discarded when that scenario ends. No other credential ever enters a candidate sandbox.
4. The dashboard displays state but cannot manufacture state transitions. It calls the same authenticated control API as scripts.
5. A candidate HTTP 200, UI success text or Jev `DONE` is an observation, never proof of correctness.
6. The original incident namespace is append-only and cannot be reset. Candidate and smoke runs receive fresh namespaces.
7. Only deterministic code can issue a `ROUTE_SAFE_HANDLER` lease, and only after evidence-set validation.

### 4.2 Modal services

Deploy one Modal app with these separately configured functions:

| Function | Containers | Secret/mount access | Responsibility |
| --- | --- | --- | --- |
| `control_asgi` | `min_containers=1`, `max_containers=1` | control secret + control snapshot volume | dashboard/static assets, API, state machine, events, receipt; sole control-store writer; bounded in-memory latest-frame slots are non-authoritative |
| `live_store_asgi` | `min_containers=1`, `max_containers=1` | live internal secret + live snapshot volume | live synthetic storefront and atomic handler router |
| `provider_asgi` | `min_containers=1`, `max_containers=1` | provider signer + provider snapshot volume | mock captures/refunds/status and evaluator-only ledger |
| `orchestrate_incident` | `max_containers=1` per run policy | control event credential, Gemini key | capsule, Gemini diagnosis, candidate specs, scheduler, selection |
| `run_candidate` | `max_containers=3` | TypeSafe key and evidence-upload credential; neither is passed into its Sandbox | one desktop Sandbox, Jev decision loop, CUA calls via `Sandbox.exec`, API/UI scenarios and frame/evidence upload |

`max_containers=1` makes each mutable trusted store a single process, but it does not by itself admit concurrent requests: Modal serves one input per container unless the ASGI function declares `@modal.concurrent(max_inputs=…)`. Size it for one long-lived SSE stream plus three 500 ms frame polls plus CAS/lease writes, or the dashboard will stall behind a single in-flight input. Inside each service, an `asyncio.Lock` plus `BEGIN IMMEDIATE` SQLite transactions serialize mutations. This is a hackathon topology, not a high-availability payment architecture.

SQLite operates on local container disk. After every critical transaction, use SQLite's backup API to create a **closed snapshot file**, atomically rename it into the service's Modal Volume directory, write a SHA-256 sidecar, then call `volume.commit()`. On cold start, copy and verify the latest closed snapshot into local disk before opening SQLite. Do not run a live WAL database directly across multiple Modal containers and do not rely on last-write-wins Volume semantics. A restart increments `service_epoch`, restores `SAFE_HOLD`, and requires operator revalidation before a new lease.

If snapshot persistence is not complete by T+2:20, keep all trusted services warm, export the final receipt and label crash recovery as unimplemented. Do not claim durable HA.

---

## 5. Canonical incident and domain model

### 5.0 The Modal-hosted synthetic production app

Build a real, minimal storefront called **NightMart**, not a decorative decoy animation. `live_store_asgi` hosts it on Modal and serves both JSON APIs and two static HTML/CSS/JS checkout variants from the same backend. The catalogue has one product, `SKU-A` at £79.99, quantity controls, a £10 voucher case, email/address fields, order status and receipt page. The app uses only synthetic identities and the separate mock provider.

The live Modal deployment contains three required preinstalled router modes, plus one optional gated mode:

- `BUGGY`: enabled only by the operator before the incident; fresh idempotency key after a lost response causes the real double capture;
- `SAFE_HOLD`: default containment after detection; browsing/history works, new capture attempts show a truthful pending/temporarily-held message;
- `SAFE`: the hash-verified inquiry-first handler activated under the repair lease;
- `LEGACY`: the previous release's checkout handler, installed and hash-verified in the live image and live-eligible under the identical evidence gate when built and tested in time (`POLICY_LIVE_A=1`, §14.1). If it is not built and tested by Gate G3 it is disabled for the run and the receipt says so.

The dashboard's **Trigger incident** button creates one frozen intent, arms `DROP_AFTER_CAPTURE_ONCE`, drives the checkout and shows a normal-looking success/HTTP 200 next to two provider ledger rows. The dashboard's later activation is not a frontend animation: it CAS-updates `router_state` in the live store, reads it back, then Jev + CUA drives a new loss-after-capture checkout through the same Modal URL. The repaired run must produce exactly one capture. This gives the audience an observable before/after against the same service and persistent data.

SQL injection stays off the critical path. It creates a second threat model, oracle and remediation path that would weaken the silent-money-failure story. Per the team's explicit decision it may exist only as a gated playbook started after the core demo is frozen and rehearsed, reusing the same evidence philosophy; otherwise it is roadmap material.

### 5.1 Incident sequence

1. Create immutable `CheckoutIntent(intent_id, customer_id, cart_hash, amount_minor=7999, currency='GBP')`.
2. Buggy handler creates `operation_id=op_1`, `idempotency_key=key_1`, persists both, calls provider.
3. Provider appends one capture and deliberately drops the response once.
4. Buggy handler treats the uncertainty as failure, creates `key_2`, and calls capture again for the same operation.
5. Provider correctly appends a second capture because a different idempotency key represents a new request.
6. The store may show `PAID` and HTTP 200, but the independent detector sees two positive captures for one frozen intent.
7. NightWatch records the harmed intent, switches future synthetic intents to `SAFE_HOLD`, and starts its repair run.

The provider is not faulty in this incident. It honours idempotency per key. The application violated the logical checkout invariant by changing the key after an uncertain result.

### 5.2 Correct safe-handler algorithm

```text
transaction:
  get-or-create order under UNIQUE(intent_id)
  get-or-create payment operation under UNIQUE(intent_id)
  persist the operation_id, stable idempotency_key, amount and currency
commit

try provider.capture(operation_id, stable_key, frozen_amount, frozen_currency)
on success:
  atomically mark PAID, create one confirmation, fulfill once
on timeout/connection loss:
  query provider captures for operation_id
  exactly one matching capture -> atomically mark PAID, confirm once, fulfill once
  zero captures or lookup unavailable -> PENDING_CONFIRMATION; do not capture again
  more than one or mismatched money -> QUARANTINED + incident; do not capture again
```

The pre-capture timeout case remains truthfully pending with no confirmation. Availability is never purchased by inventing a successful payment.

### 5.3 Storage tables and constraints

#### Store database

- `checkout_intents`: `intent_id PK`, `customer_id`, `cart_hash`, `amount_minor CHECK > 0`, `currency`, `created_at`.
- `orders`: `order_id PK`, `intent_id UNIQUE FK`, `status`, frozen amount/currency, `created_at`, `updated_at`.
- `payment_operations`: `operation_id PK`, `intent_id UNIQUE FK`, `idempotency_key UNIQUE`, frozen amount/currency, `state`.
- `confirmations`: `confirmation_id PK`, `order_id UNIQUE FK`, `created_at`.
- `fulfillments`: `fulfillment_id PK`, `order_id UNIQUE FK`, `sku`, `quantity CHECK > 0`, `created_at`.
- `refund_intents`: `refund_intent_id PK`, `operation_id FK`, `amount_minor CHECK > 0`, `UNIQUE(operation_id, refund_intent_id)`.
- `router_state`: one row with `mode`, `generation`, `handler_hash`, `rollout_pct` (0–100 probe-routing percentage, meaningful only while `mode=SAFE_HOLD`), `bucket_seed` (stable probe-bucket hash seed), `lease_id`, `lease_expires_at`, `updated_at`. The percentage is what makes "1 routed, 19 held" representable in staged smoke; without it the router can only express 0% or 100%.

#### Provider database

- `registered_operations`: `(namespace, operation_id) PK`, logical `intent_id`, frozen amount/currency, allowed actions.
- `captures`: append-only, `capture_id PK`, namespace, operation, key, amount/currency, timestamp; `UNIQUE(namespace, idempotency_key)`.
- `refunds`: append-only, `refund_id PK`, namespace, operation, refund-intent ID, amount, timestamp; `UNIQUE(namespace, operation_id, refund_intent_id)`.
- `fault_schedules`: namespace/scenario-scoped one-shot fault with generation and consumed timestamp.

The provider rejects unknown operations, cross-namespace operations, mismatched amount/currency, changed parameters under the same idempotency key and refunds beyond captured total. Same-key/same-parameter replay returns the cached capture.

### 5.4 Invariants

| ID | Deterministic rule | Evidence source |
| --- | --- | --- |
| `INV-01` | One logical intent has at most one order, one provider operation, one successful capture and one confirmation, regardless of retries/keys. | store DB + evaluator ledger + frozen intent map |
| `INV-02` | `PAID`/refunded means exactly one matching capture and one confirmation; `DECLINED` means zero; `PENDING_CONFIRMATION` means zero confirmation and no false-success UI. | store DB + ledger + browser outcome |
| `INV-03` | Capture/refund amounts are positive integer pence; refunds never exceed capture; replaying a refund intent appends nothing. | ledger |
| `INV-04` | Inventory fulfillment occurs exactly once per paid order and decrements by the purchased quantity exactly once. | fulfillment rows + stock |
| `INV-05` | The HTTP/UI journey remains available and displays a state consistent with the trusted payment state. | browser/API trace + store DB + ledger |
| `INV-06` | Original incident records and captures remain immutable and separated from reproduction/candidate namespaces. | provider namespace digests + control receipt |

Never implement `all(result.passed for result in results)` without first proving the exact required set is present. Evidence-set validation must require each `(candidate_id, scenario_id, invariant_id)` tuple expected by the registry exactly once.

---

## 6. Frozen incident capsule

`IncidentCapsule` is the only evidence Gemini and candidate creation may consume. Build it after `SAFE_HOLD` is confirmed.

Required contents:

- incident ID, run ID, UTC and monotonic start times;
- original namespace and harmed intent/order/operation IDs;
- read-only ledger rows and store rows relevant to the harmed intent;
- current release hash, previous release hash and safe-handler hash;
- bounded recent application logs with secrets removed;
- the exact buggy retry module and bounded diff from known-good;
- seed SQL/JSON hash, scenario-registry hash, oracle code hash and image digest;
- fault schedule and expected symptom, explicitly marked as fixture knowledge;
- `capsule_sha256` over canonical JSON;
- a list of exclusions and unavailable evidence.

Freeze before reproducing candidates. Every result must echo capsule, code, seed, scenario and oracle hashes. A mismatch fails the candidate before scoring. Because `apps/live_store/**` is packaged into the pinned candidate image, freeze its bundle hash at T+2:20: any later change alters the desktop-image digest, invalidates every recorded Sandbox/CUA evidence item and the capsule, and requires a full re-run with a capsule note. Old evidence is void, not "close enough".

---

## 7. Strict Pydantic contracts

All boundary models inherit:

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
    )
```

Do not add `validate_assignment=True` here: assignment is rejected while the model is frozen, so the setting is inert and any code relying on it raises instead of validating. If a mutable internal state model needs assignment validation, give it its own base class rather than weakening `StrictModel`.

Use `default_factory` for collections, timezone-aware UTC validators for wall-clock fields, monotonic integer nanoseconds for durations, constrained strings, `PositiveInt` for pence and quantities, enums/Literals for all policy-bearing values, and lowercase 64-character SHA-256 types. For JSON inputs, validate with `model_validate_json(..., strict=True)` and explicit datetime validators because JSON strictness is not identical to Python-object strictness.

### 7.1 Required models

| Model | Essential fields and constraints |
| --- | --- |
| `IncidentEvent` | event ID, incident/run IDs, strict event kind, UTC time, monotonic ns, state version, redacted payload, prior event hash, event hash |
| `IncidentCapsule` | fields in Section 6; canonical hash; no secret-bearing arbitrary dicts |
| `GeminiDiagnosis` | 1–3 hypotheses, cited evidence IDs, contradiction IDs, requested experiment enum, uncertainty, model/version |
| `PatchProposal` | base SHA, target path exactly `apps/live_store/domain/payment_retry.py`, unified diff, rationale, expected behavior, risks, tests; max 40 changed lines after parsing |
| `CandidateSpec` | A/B/C ID, kind, image/code/base/capsule/seed hashes, provider namespace, immutable rank, live eligibility fixed by policy |
| `BrowserObservation` | origin, URL, page generation, observed controls with action IDs/roles/names/states, visible status text, observation hash |
| `JevDecision` | decision ID, chosen action ID, operation enum, returned model version, confidence statistic, raw probabilities, observation hash |
| `BrowserFrame` | run/candidate/scenario, strict increasing sequence, CUA session ID, required CUA snapshot ID returned by the same call that produced the image, optional capture ID when CUA returns one, sandbox ID, phase enum `SAMPLE/BEFORE_ACTION/AFTER_ACTION/TERMINAL`, capture monotonic time, image SHA-256 (**the frame's canonical identity**), MIME enum, declared image size <=350 KB, optional Jev decision/action overlay fields; binary image is the separately hashed multipart part |
| `BrowserBarrierState` | run/generation, exact expected candidate set, ready candidates with sandbox/session hashes, released time or typed timeout |
| `ScenarioResult` | candidate/scenario, result enum, start/end, app facts, ledger evidence IDs, browser trace, invariant results, all hashes, failure reason |
| `InvariantResult` | invariant ID, PASS/FAIL/ERROR, expected summary, observed summary, evidence IDs; PASS requires non-empty evidence |
| `CandidateEvaluation` | exact scenario set, exact invariant matrix, result, timing, sandbox/function IDs, evidence-set hash |
| `StageEvent` | requested percentage, routed/held counts, actual bucket IDs, normal/loss probe counts and results |
| `RepairLease` | lease ID, action=`ROUTE_SAFE_HANDLER`, selected live-eligible candidate (B or `LEGACY`), evidence hash, selected handler hash, scope=`synthetic_checkout_router`, expected/current router generation, issued/expires UTC, guardian interval |
| `RepairReceipt` | incident/capsule/run/evidence hashes, original harm, containment, candidate matrix, decision basis, stage results, lease/readback, model IDs, limitations, demo mode, degraded reasons |

### 7.2 Visible Pydantic prize proof

The dashboard must include a small **Schema Gate** panel with counters and one safe demonstration:

- accept and render a valid `PatchProposal`;
- reject a prepared malformed proposal containing an extra field or forbidden target path;
- show the exact validation error and that no sandbox/deployment was created;
- link receipt fields back to generated JSON Schema names;
- if Logfire is live, link the validation/agent trace; otherwise show local trace IDs and mark hosted tracing unavailable.

Do not intentionally corrupt a real Gemini response for theatre. The malformed object is a labelled negative control.

---

## 8. Control-plane state machine and concurrency

### 8.1 States

```text
IDLE
  -> DETECTED
  -> SAFE_HOLD
  -> CAPSULE_FROZEN
  -> REPRODUCING
  -> VALIDATING
  -> SELECTING
  -> STAGED_SMOKE
  -> LEASED

From every nonterminal state:
  -> SAFE_HOLD (operator safe-stop, restart uncertainty, lease expiry)
  -> ESCALATED (failed gate, timeout, credential/provider/oracle failure)

LEASED -> SAFE_HOLD on expiry, failed guardian, manual stop or state mismatch.
No transition returns to BUGGY.
```

### 8.2 Compare-and-swap transition rule

The control database holds `(incident_id, state, version, stop_requested, active_run_key)`. Every transition is one `BEGIN IMMEDIATE` transaction:

1. read row and assert expected state/version;
2. assert `stop_requested=false` for forward transitions;
3. insert the new event with a unique idempotency key;
4. update state and increment version with `WHERE version=:expected`;
5. require exactly one updated row;
6. commit and persist snapshot;
7. publish SSE only after commit.

`POST /run` accepts a client idempotency key. Duplicate calls return the existing run. A unique `(incident_id, run_key)` constraint prevents parallel repair runs.

### 8.3 Atomic lease activation

Lease issuance and live router activation are a two-system operation, so use a fail-closed protocol:

1. Control transaction creates lease in `PENDING_ACTIVATION` only from `STAGED_SMOKE`, with expected router generation and evidence/hash bindings.
2. Control calls live store `PUT /internal/router` with `mode=SAFE`, lease ID, expiry, expected generation and safe-handler hash.
3. Live store atomically checks current generation, current mode is `SAFE_HOLD`, installed handler hash and expiry; writes `SAFE`; increments generation; returns signed readback.
4. Control verifies signature, generation, handler hash, scope and lease ID.
5. Control transaction changes lease to `ACTIVE` and state to `LEASED`.
6. If steps 3–5 time out or disagree, control calls idempotent `SAFE_HOLD`, records activation failure and escalates.

On restart, the live store defaults to `SAFE_HOLD` unless an unexpired active lease can be verified against control. The control plane also treats uncertain activation as `SAFE_HOLD`. The guardian polls every 15 seconds and never writes `BUGGY`.

### 8.4 Safe Stop race

`POST /safe-stop` first persists `stop_requested=true`, then calls live `SAFE_HOLD`, cancels pending Modal calls/sandboxes best-effort, and records cleanup results. Lease issuance must check the stop flag in its transaction. Test simultaneous `/run` and `/safe-stop`, stop during staged smoke, stop after router write but before control acknowledgement, and restart at each lease boundary.

---

## 9. API contracts

Every operator endpoint, including reads, requires `Authorization: Bearer $NIGHTWATCH_OPERATOR_TOKEN`; mutating endpoints also require `Idempotency-Key` and a strict Pydantic body. The public synthetic storefront is the only unauthenticated UI. Internal endpoints have separate secrets; never reuse the operator token.

### 9.1 Control API

| Method/path | Request | Response/purpose |
| --- | --- | --- |
| `POST /api/reset-demo` | `ResetDemoRequest` | Creates a fresh live run namespace and seed; never deletes original incident history. |
| `POST /api/deploy-bug` | `DeployBugRequest` | Sets live synthetic router to BUGGY only before incident start and only when no historical incident is active. |
| `POST /api/trigger-checkout` | `TriggerRequest` | Runs the labelled incident fixture once. |
| `POST /api/incidents/{id}/run` | `RunRequest` | CAS to repair run and spawn orchestrator; duplicate key returns same run. |
| `POST /api/incidents/{id}/safe-stop` | `SafeStopRequest` | Persist stop, hold new checkouts, cancel work, never restore BUGGY. |
| `GET /api/incidents/{id}` | none | Typed snapshot with state/version and authoritative links. |
| `GET /api/incidents/{id}/events` | `Last-Event-ID` supported | SSE replay from committed event table. |
| `GET /api/incidents/{id}/receipt` | none | Canonical signed/hashed receipt JSON. |
| `GET /api/worlds/{id}/health` | none | World lifecycle, hashes, sandbox/function IDs and cleanup state. |
| `GET /api/runs/{run_id}/frames/{candidate_id}/latest` | `after` sequence plus operator auth | Latest run-bound image bytes with typed metadata headers, `ETag=image_sha256` and `Cache-Control: no-store`; returns 304/no-content when unchanged and never falls through to a prior run. |
| `POST /internal/events` | signed `IncidentEventInput` | Sole path for workers to propose events; control validates and writes. |
| `POST /internal/evidence` | bounded evidence envelope | Stores evidence by digest; rejects oversized/untyped payloads. |
| `POST /internal/frames` | multipart: strict `BrowserFrame` metadata JSON + binary image, scoped runner auth | Uses `model_validate_json(..., strict=True)`, streams with a 350 KB hard cap, verifies declared size/MIME/hash/candidate/run/sequence, then stores latest frame and keyframe manifest. |
| `POST /internal/worlds/{candidate_id}/browser-ready` | sandbox/session/hash tuple | Registers readiness for the current barrier generation. |
| `GET /internal/runs/{run_id}/browser-barrier` | scoped runner auth | Releases a signed generation only when all expected eligible worlds are ready or returns a typed timeout. |

### 9.2 Live store internal API

- `PUT /internal/router`: CAS router mode/generation; once the incident has started the permitted targets are `SAFE_HOLD` and `SAFE`, plus `LEGACY` only when the §14.1 gated stretch is enabled. `BUGGY` is unreachable after `SAFE_HOLD`.
- `GET /internal/router`: signed readback.
- `GET /internal/state/{intent_id}`: evaluator-only app truth.
- `POST /internal/probes`: creates only registered synthetic probe intents with frozen values.

Public store API:

- `POST /api/intents`; `GET /api/intents/{id}`;
- `POST /api/checkout/{intent_id}`;
- `GET /api/orders/{order_id}`;
- `POST /api/refunds`.

### 9.3 Provider API

- `POST /capture(operation_id, idempotency_key, amount_minor, currency)`;
- `GET /operations/{operation_id}/captures` for safe recovery;
- `POST /refund(operation_id, refund_intent_id, amount_minor)`;
- evaluator-only `GET /internal/ledger/{namespace}`;
- evaluator-only `POST /internal/namespaces` and operation registration.

Candidate tokens are signed and bound to `{incident_id,candidate_id,scenario_id,namespace,allowed_operation_ids,expiry}`. They cannot call evaluator or namespace-management routes. Log token fingerprints only, never raw tokens.

---

## 10. Gemini integration

### 10.1 Responsibility

Gemini may:

- rank up to three hypotheses from the frozen capsule;
- cite the exact evidence IDs supporting and contradicting each hypothesis;
- request only experiments already enumerated by code;
- produce Candidate C's `PatchProposal`;
- emit the advisory **triage** block (category, severity, short rationale, confidence) defined in §10.4.

Gemini may not invent provider facts, choose the winner, alter tests/fixtures/oracle/provider, run commands, issue a lease or deploy code.

### 10.2 Pydantic AI implementation

Use `pydantic-ai-slim[google]` and Google AI Studio via `GOOGLE_API_KEY`. Instantiate the configured model as `Agent(f"google:{settings.gemini_model}", output_type=GeminiDiagnosis)` and a second bounded agent/output for `PatchProposal`. The event-day default model must be selected by the T+0 preflight and recorded in the receipt; do not silently change it mid-run. `GEMINI_MODEL` is configuration, not hard-coded marketing copy.

Prompt input is the canonical capsule plus strict instructions. Validate the response, evidence references and patch independently. A schema-valid answer is still only a proposal.

### 10.3 Patch guard

Reject Candidate C unless all checks pass:

- base commit/hash equals the capsule;
- unified diff parses without invoking a shell;
- exactly one regular file is changed: `apps/live_store/domain/payment_retry.py`;
- no absolute paths, `..`, symlinks, binary/mode changes or submodules;
- no dependency, provider, evaluator, fixture, scenario, seed, test or configuration changes;
- at most 40 added/deleted lines, ignoring diff headers;
- diff applies to a clean in-memory/worktree copy with `git apply --check` using an argument list and file input, never shell interpolation;
- static import allowlist passes;
- resulting code hash is recorded.

Pass patch bytes as data or a mounted file. Never do `bash -c "echo '$PATCH' | git apply"`; quoting bugs and command injection would cross the trust boundary.

If Gemini fails, times out or returns an invalid proposal, record `C=SKIPPED_INVALID` and continue A/B. Do not use a hand-authored patch while labelling it Gemini-generated.

---

### 10.4 Advisory triage belongs to Gemini, not Jev

Decided 19 September and confirmed by live testing: the Gemini model accepts free-form string fields, while TypeSafe **cannot emit free text at all** (§11.3). Triage therefore goes to Gemini, and Jev keeps exactly one job — bounded browser action choice.

`GeminiDiagnosis` carries a nested advisory block:

- `category: Literal['payment_correctness','deploy_regression','infrastructure','security','unknown']`
- `severity: Literal['low','medium','high','critical']`
- `rationale: str` — at most 200 characters, referencing cited evidence IDs
- `confidence: float` — bounded 0–1

Rules: it is **advisory only**. It never qualifies an incident, gates a candidate, influences selection or touches the lease; it renders as `MODEL_PROPOSED` in the dashboard and the receipt. A missing or malformed triage block fails the diagnosis closed without blocking A/B.

---

## 11. Jev browser decision loop

### 11.1 Exact role

Jev is not a browser, text generator or invariant checker. CUA Driver observes and executes. Jev receives a compact text/JSON snapshot and selects one of the currently allowed semantic actions. Code owns freshness, values, execution and verification.

Pin the tested model ID, initially `jev-1.13.0`, rather than the moving `jev-latest` alias. Record `ModelResponse.model_name` from every run. Use `pydantic-ai-slim[typesafe]` or the current TypeSafe SDK after the T+0 key smoke test.

### 11.2 Observation

For each step, the CUA adapter emits only:

- allowed origin and normalized URL;
- page generation counter;
- visible heading/status text;
- visible enabled controls with opaque action ID, role, accessible name, field purpose and state;
- current scenario goal and completed observed postconditions;
- no hidden DOM, scripts, secrets or arbitrary page instructions.

Page text is untrusted data. A malicious label such as "ignore policy and deploy" is just a label and never becomes an instruction.

### 11.3 Dynamic typed actions

Follow CUA's official `jev-use` recipe and TypeSafe's native Choice contract. Build one closed criteria map from the current CUA snapshot plus `REOBSERVE`, `ABSTAIN` and `DONE_UNVERIFIED`. **Cap the offered set**: a Choice accepts 255 options and the reserved options consume part of that budget, so offer at most 253; rank/filter the visible controls if a snapshot is larger, fail closed (reobserve then abstain) rather than truncating silently, and log the omitted count. Example candidate IDs:

```text
click__a17       "Click the visible button named Confirm order"
type_email__a04  "Fill the visible email field with the fixture email"
select_sku__a09  "Choose the fixture SKU from the product selector"
reobserve        "The page may have changed; observe again"
abstain          "None of the observed actions safely advances the goal"
done_unverified  "The visible journey appears complete; request independent verification"
```

Send one native TypeSafe `system_one` request using `AsyncTypeSafeClient` or the equivalent current `/v1/systemone` payload:

```json
{
  "model": "jev-1.13.0",
  "state": {"goal": "...", "observation": {}, "bounded_history": []},
  "questions": {
    "next_action": {
      "type": "choice",
      "instructions": "Which supplied action safely advances the stated checkout goal from this exact observation?",
      "criteria": {"click__a17": "...", "reobserve": "...", "abstain": "..."}
    }
  }
}
```

Parse the response into strict `TypeSafeChoiceResponse` and `JevDecision` Pydantic models. Reject a choice absent from the submitted criteria before any CUA call. Preserve raw probabilities, confidence statistic, response model ID, request ID and observation hash. Confidence measures distribution concentration, not correctness. Do not use one universal threshold; calibrate only a narrow low-margin rule from event-day smoke cases. A low-margin action reobserves once, then abstains. An abstention never becomes a blind click.

**Live-verified contract (19 September — `pydantic-ai-slim[typesafe]` 2.46.0, `typesafe-sdk` 0.7.0, model `jev-1.13.0`).** TypeSafe outputs are restricted to: `bool`; a `Literal`/`Enum` of two or more strings; a `float` bounded `ge=0, le=1`; a list of `Literal`/`Enum`; a rubric of whole numbers from 0 with a description per level; or a model composed of these. **Free-form text is not supported** — it raises before any API call — so Jev can never produce prose, and any "explain yourself" field is a design error. Observed shapes: `Choice = {type, instructions, criteria}`, `ChoiceAnswer = {type, choice, confidence, probabilities}`. `TypeSafeModel(model_name, *, provider, profile, settings)` takes **no `api_key`** — auth comes from the environment/provider. First live pilot decision returned `choice='click__a17'`, `confidence=0.27`, `probabilities={click__a17: 0.52, abstain: 0.45, reobserve: 0.03}` — direct confirmation that confidence is a margin, not a correctness probability, and that the non-winning options must be preserved in the trace.

### 11.4 Execution guard

Before executing the returned decision, the CUA adapter rechecks:

- observation hash and page generation still match;
- same origin and expected route;
- target action ID still maps to one visible, enabled control with the expected role/name;
- on Linux X11 every click uses the explicit `input_route: dom_event` path, because trusted CDP pointer input is refused on that platform; never assume a dispatched click proves activation, and always confirm the outcome from a fresh snapshot plus the trusted store/provider APIs;
- typed/selected value comes from the scenario fixture allowlist;
- submit has not already entered an uncertain state.

After a click, wait for a specific route/DOM/network condition and reobserve. On uncertain submit, query trusted state; never click submit again blindly. Maximum 20 decisions or 25 seconds per UI scenario. `DONE_UNVERIFIED` triggers the oracle and is not a pass.

### 11.5 Why this is meaningfully Jev

UI X says **Pay now** with an always-visible promo field. UI Y reorders fields, says **Confirm order**, and hides the voucher field behind **Add voucher**. Selectors and action IDs change. The semantic goal and fixture values remain the same. Jev + CUA is the only browser path.

### 11.6 CUA Driver inside every Modal candidate sandbox

Use the official CUA `jev-use` pattern rather than inventing a second computer-use agent:

```text
CUA Driver semantic_v2 snapshot
        -> compact observed controls + immutable snapshot/capture ID
        -> application constructs bounded candidate action IDs
        -> Jev Choice selects one ID, REOBSERVE or ABSTAIN
        -> Pydantic validates JevDecision and supplied-candidate membership
        -> adapter rechecks snapshot/session/origin/target freshness
        -> CUA Driver executes the bound browser action
        -> fresh CUA snapshot observes UI effect
        -> trusted store/provider API proves the actual postcondition
```

CUA performs observation and execution; it does not choose policy or decide a candidate passed. Jev receives no screenshot bytes, CUA tool names, raw tool arguments, environment data or credentials. It sees only the goal, compact typed regions/controls, bounded history and supplied action IDs.

Each A/B/C Modal Sandbox uses the same pinned desktop image containing:

- a minimal X11 desktop (`Xvfb` plus Openbox or Xfce), D-Bus and AT-SPI accessibility services;
- a pinned **Google Chrome stable** installed as a **root-owned `.deb`** (CUA validates Chrome on Linux X11; Debian Chromium is descriptor-backed but not product-validated — the receipt records the exact installed version), launched and owned by the controller identity, with a world-local mode-0700 profile, `--force-renderer-accessibility` and a **loopback-only, PID-owned DevTools endpoint**. CUA Driver 0.28.2 documents no pipe transport; CDP is unauthenticated and same-OS-user processes sit outside the driver boundary, so enforcement is the app/controller OS-user split, file modes and the controller-owned socket. **The receipt must not claim "pipe".** Wherever an older section of this plan says "Chromium", read it as this pinned **Google Chrome stable** build — the product was changed after measurement, not the architecture.
- the event-tested CUA Driver binary;
- the candidate FastAPI app and world-local SQLite database;
- no TypeSafe, Gemini, control-plane, evaluator or Modal account secret; the app process receives only its expiring world/scenario provider token.

Sandbox bootstrap creates two non-root identities: `nightwatch_app` owns only the candidate bundle/DB/provider-token environment, while `nightwatch_controller` owns the display, the Chrome profile and its loopback DevTools endpoint, and the CUA socket. The app user must be unable to read the controller socket/profile, signal the Driver/Chromium processes or access their file descriptors; the controller has no provider token. Start X11, accessibility bus and window manager under the controller, the candidate app under the app identity, then disable CUA telemetry and start `cua-driver serve` on a mode-0600 controller-owned Unix socket. Because Modal `Sandbox.exec` has no per-user parameter, the bootstrap script performs an explicit privilege drop (`setpriv` or `su`) for each process and records the effective UID of the app, the controller and the Driver in the evidence bundle. CUA runs in `bounded` mode with a generated capability manifest that allows only the CUA-owned Chromium/profile, the exact loopback candidate origin, and exactly this **verified working tool set**: session `start_session`/`end_session`, `launch_app`, `list_windows`, `browser_prepare`, `browser_navigate`, `browser_click` (`input_route: dom_event`), `browser_type` and `get_browser_state` (`semantic_v2`, `include_screenshot`), with `resources.apps` scoping `/opt/google/chrome/chrome` (`windows: all`, `terminate: driver_launched`) and `desktop.display: false`. `list_windows` and the app scope were measured as **required** for window binding and enumeration. `semantic_v2` is a `snapshot_format` value of `get_browser_state`, not a tool name, and screenshots come from `include_screenshot`. The manifest stays **origin-scoped** and **fails closed at startup** if it lists generic input tools such as `click`, `type_text`, `page` or `get_window_state`. No shell, clipboard, file, native-app, desktop-wide or arbitrary-origin action is exposed to Jev.

The corresponding trusted `run_candidate` Modal Function owns `TYPESAFE_API_KEY`. It invokes CUA as the controller identity with argument-array `Sandbox.exec` calls to `cua-driver call ... --socket /tmp/nightwatch-cua.sock`; the secret is never passed into `Sandbox.create`, an environment variable, a file or command argument inside the sandbox. The runner parses the strict CUA response, constructs the allowlisted Jev Choice request, validates the selected ID, then asks CUA to execute the prebound action. Candidate code can still influence rendered web content, so UI/CUA evidence is corroborative; only the external provider ledger and trusted app-state read determine the invariant result.

Create one unguessable `world_session` name from run/candidate/scenario plus a nonce. Pass that same explicit session on **every** `start_session`, `browser_prepare`, `get_browser_state`, `semantic_v2`, navigate, click, type, screenshot and `end_session` call; never rely on a CLI implicit session. Bind and record the exact browser PID/window, `target_id`, `tab_id` and snapshot/capture IDs. Refs are session- and snapshot-bound and must be reacquired after navigation or mutation. A session TTL/expiry aborts the step; before any side effect it may start a fresh session and reobserve, while after an uncertain submit code queries trusted state and never blindly repeats. Always call `end_session`, revoke the capability manifest and kill the private CDP transport in cleanup. S01 and S02 are serial within a world, but A/B/C worlds enter a trusted barrier and begin the hero S02 browser journey concurrently. This produces three real Jev decision loops, three CUA sessions and three Chromium desktops inside the three actual candidate sandboxes.

### 11.7 Concurrent visual evidence stream

Every action observation uses `semantic_v2(include_screenshot=true)` so one snapshot-bound CUA response produces:

1. compact semantic state and refs used to construct Jev's bounded choices; and
2. the matching uninterpreted screenshot/capture ID shown to judges, never sent to Jev.

Before and after each action, the trusted runner converts the screenshot to bounded JPEG/WebP and uploads a strict `BrowserFrame` through a scoped evidence-ingest token:

```text
candidate_id, scenario_id, frame_seq, captured_at, capture_id, snapshot_id?,
sandbox_id, cua_session_id, image_sha256, image_size <= 350 KB,
phase = SAMPLE | BEFORE_ACTION | AFTER_ACTION | TERMINAL,
jev_decision_id?, selected_action_label?, confidence?
```

Frame bytes never enter SQLite and never cause a per-frame Modal Volume commit. After validation, control atomically swaps each run/candidate's bounded in-memory latest-frame slot; its queue length is one, so an older `SAMPLE` is coalesced rather than blocking CAS/SSE/lease work. SSE announces metadata and the dashboard fetches image bytes from `/api/runs/{run_id}/frames/{candidate_id}/latest?after={seq}`. `BEFORE_ACTION`, `AFTER_ACTION` and `TERMINAL` keyframes are also written to a bounded temporary artifact directory; when the scenario ends, their manifest and hashes are committed in one control transaction and the compact bundle is snapshotted once. Losing hot frame bytes on control restart is an honest display degradation, never loss of authoritative payment/evaluation truth.

While a browser scenario is active, each world must publish **at least 1 fresh frame/second, target 2 frames/second**. A per-world sampler requests a CUA window screenshot every 500–1000 ms, reading the image through `get_browser_state(include_screenshot=true)` and recording the snapshot ID returned by that same call, so the sampler never mints a new semantic snapshot that would invalidate the references Jev judged. It shares a lock with the action loop: sampling pauses only between accepting Jev's snapshot-bound decision and completing/rejecting the corresponding CUA action, then resumes immediately. Per-world ingest is capped at 2.5 frames/second and 800 KB/second with a short upload timeout; stale `SAMPLE` frames may be dropped, action keyframes may not. If a newer semantic snapshot supersedes the one Jev judged, the old decision is rejected and Jev is asked again; freshness is never traded for frame rate.

The three tiles update independently, so judges see genuine concurrent progress without exposing a raw VNC port or bearer token. Each tile overlays candidate/scenario, real Modal Sandbox ID, short snapshot ID, Jev-selected action, action number, measured FPS and oracle status. The stall clock freezes while a CUA action is in flight, so one slow action cannot masquerade as a stall. If a world produces no fresh frame for 5 seconds, its tile changes to `FRAME_STALLED` amber; after 10 seconds the UI scenario fails `ERROR_FRAME_STREAM` as a display/browser-evidence failure only — never as a payment or invariant failure. A frozen tile is labelled `WAITING`, `ABSTAINED`, `FAILED` or `COMPLETE`; it never loops a fake recording. The dashboard reports actual per-world and aggregate frame rates from capture timestamps.

Keep an optional noVNC service only as a post-core debugging aid. It is not the judged path because authenticated iframe/WebSocket proxying adds avoidable risk and token leakage. The exact CUA screenshots are stronger evidence: their snapshot IDs are the ones tied to Jev's decisions.

### 11.8 Hard CUA-in-Modal preflight gate

Before building the full dashboard, prove one complete desktop world:

1. build the pinned Modal desktop image and record its digest;
2. start one Sandbox with separate app/controller users; prove the app user is denied the controller socket, the Chrome profile, its loopback DevTools endpoint and process controls;
3. prove X11, D-Bus/AT-SPI and CUA Driver readiness with telemetry disabled, then run `browser_prepare -> get_browser_state -> semantic_v2(include_screenshot=true)` against the exact candidate tab;
4. keep the same explicit named session across separate calls; prove a ref minted by call N works in call N+1 and is rejected under a different session;
5. make one live Jev Choice call from the trusted runner and execute the chosen action through the sandbox CUA daemon;
6. verify the result from external app/provider state, upload at least five genuine frames over five seconds, end the named session and terminate everything;
7. record CUA Driver/Chromium versions, display/CDP mode, configured session TTL, Modal Sandbox ID and total cold-start time.

This is a hard full-demo dependency because Linux/X11 support does not prove this exact Modal/gVisor image works. Build the pinned desktop image first — it is the long pole — and keep the core/API-only demo as the **default** deliverable until this gate is green. If it is not green by **T+0:50**, full mode is `AT_RISK` and Track B gets one final focused window while Track A continues the core system; if it is still not green at T+1:30, declare reduced mode and stop allocating critical-path time to the three-browser wall. Do not introduce another browser controller. S01/S02 remain `ERROR_BROWSER_STACK`, and the submission cannot claim browser-agent or concurrent-browser completion. CUA Fleets, CUA Sandbox and Lume remain out of scope because Modal is the required isolation/concurrency platform.

**Incident-day outcome (19 September): the gate is NOT GREEN on driver 0.28.2.** Typed `browser_navigate` **and** `semantic_v2` observation are refused from a fresh `about:blank` page under an origin-scoped bounded manifest — the refusal reads the *current*, opaque origin, and declaring `"null"`/`"about:blank"` is rejected by the manifest loader at daemon startup; the existing-profile attach route also fails its endpoint proof against a live, PID-owned loopback endpoint. Browser scenarios are declared `ERROR_BROWSER_STACK` and the demo runs in **reduced mode**. One mechanism remains **untested rather than disproven** — seeding a driver-owned `isolated_named` profile with Chrome startup URLs — and a CDP first-navigation probe was **never attempted**; neither is claimed as working. Full evidence: `infra/BROWSER_STACK_NOTES.md`.

---

## 12. Modal candidate execution

### 12.1 Correct concurrency pattern

`run_candidate` is a deployed Modal Function. Consume `map.aio` as an async iterator, not a context manager:

```python
@app.function(
    image=runner_image,
    secrets=[typesafe_secret, evidence_ingest_secret],
    max_containers=3,
    timeout=240,
)
async def run_candidate(spec_json: str) -> str:
    spec = CandidateSpec.model_validate_json(spec_json, strict=True)
    result = await CandidateRunner(spec).run()
    return result.model_dump_json()

async def race(specs: list[CandidateSpec]) -> list[CandidateEvaluation]:
    results: list[CandidateEvaluation] = []
    inputs = [s.model_dump_json() for s in specs]
    async for item in run_candidate.map.aio(
        inputs,
        order_outputs=True,  # deliberate: preserves input-index -> candidate identity
        return_exceptions=True,
    ):
        if isinstance(item, BaseException):
            results.append(error_evaluation(item))
        else:
            results.append(CandidateEvaluation.model_validate_json(item, strict=True))
    return results
```

**`order_outputs=True` is deliberate** (recorded decision, 19 September; supersedes the earlier sketch). With `order_outputs=False` the async iterator yields in completion order while exceptions arrive with **no candidate identity** — a bare exception cannot be matched to a world, and guessing can mark the wrong candidate `ERROR`, which changes deterministic selection. Ordered output preserves the one-to-one input-index → candidate mapping, so a crashed container is attributed to the world that actually failed. The cost is streaming granularity on the dashboard, which is acceptable because the race is collected before selection.

`.map()` parallelises function inputs but does not itself prove three sandboxes. Each `run_candidate` invocation must create exactly one `modal.Sandbox`, record its ID/lifecycle and terminate it in `finally`. When extra worlds are added — the four-pane target is A, B, C plus a live negative-control world — raise `max_containers` to match; never reuse one world for two candidates.

### 12.2 World lifecycle

For A/B/C independently:

1. derive a fresh candidate namespace and scoped provider token;
2. validate image/code/seed/capsule/oracle/scenario hashes;
3. create one sandbox from the pinned NightWatch desktop image with explicit timeout and idle timeout;
4. transfer the candidate bundle and patch as files/data, not interpolated commands;
5. bootstrap Xvfb, D-Bus/AT-SPI, window manager and bounded CUA daemon as `nightwatch_controller`, plus candidate FastAPI as `nightwatch_app`, using the explicit privilege drop described in §11.6; deny the app user access to the controller socket, the Chrome profile, process controls and the loopback DevTools endpoint, or fail full mode;
6. create an authenticated Connect Token for port 8080 with non-secret metadata so the trusted API runner can reach the candidate; Chromium inside the world uses loopback;
7. create the explicit named CUA session; run `browser_prepare`, `get_browser_state` and `semantic_v2(include_screenshot=true)` through the loopback DevTools binding; on readiness/session/ownership failure terminate and return `ERROR_STARTUP`;
8. run this world's scenarios with **bounded concurrency and per-scenario isolation**: every scenario gets its own app-DB generation file copied from the frozen seed, its own provider namespace and its own short-lived token, and asserts seed/code/fault hashes before executing. UI scenarios stay serial within a world (one Chromium and one CUA session per world is a hard constraint); API scenarios may run in bounded parallel batches because they share no mutable state. Isolation is what replaces serialisation and keeps the run inside the §14.4 budget without letting incompatible stock or money states share a database. The 1–2 FPS CUA frame sampler runs only during browser scenarios;
9. register `BROWSER_READY` with the trusted control barrier; after all eligible worlds are ready, release one barrier generation so A/B/C begin S02 within a two-second window;
10. for every browser step, pass the same explicit session to CUA, obtain state/frame, call Jev from the trusted runner, validate the selected ID/session/snapshot freshness, execute through the sandbox CUA socket, publish before/after frames, then independently query app/provider state;
11. run S01 after S02 in each world, using a new CUA session and temporary Chromium profile plus a fresh app DB reset and provider namespace;
12. upload bounded evidence and result digests to control;
13. stop frame sampler, end/revoke CUA sessions, stop the daemon/browser/display, revoke/expire credentials and terminate the sandbox idempotently in `finally`.

Candidate sandboxes have no Gemini/Jev/control/evaluator/Modal credentials and no writable trusted volume. The candidate app's only secret is its short-lived provider token bound to exact run/candidate/scenario namespace, operation IDs and expiry; the controller user does not receive it. The **trusted `run_candidate` Function container**, outside the Sandbox, has only `TYPESAFE_API_KEY` and narrowly scoped event/frame/evidence-ingest credentials. It never passes those values into `Sandbox.create`, sandbox environment variables, files, logs or CUA calls. Tests inspect both users' environment/log exposure and prove that neither can call evaluator, another namespace or another operation. Default sandbox outbound networking is broader than ideal, so the real security boundary is that narrow provider token. If event-day testing proves Modal's outbound allowlist works with the provider hostname, enable it and record that; otherwise do not claim egress isolation. If egress control is enabled, remember that a domain-only allowlist blocks the in-world browser's loopback origin — also allow `127.0.0.1/32`, or the hero journey cannot reach its own app. An encrypted port alone is not authentication; use Connect Tokens.

### 12.3 Measured Modal proof

Persist per candidate:

- Function call ID and Sandbox ID;
- created, scheduled, started, ready, scenario-start, finished and terminated monotonic times;
- image digest, app code hash and configuration hash;
- authenticated endpoint creation/readiness result;
- CUA Driver version, session/profile/process IDs, semantic snapshot IDs and cleanup result;
- maximum observed active worlds computed from interval overlap;
- termination result.

The dashboard renders these facts. It does not animate three bars without the underlying IDs.

---

## 13. Scenario registry and oracle

Every scenario starts from its own app-DB generation copied from the frozen pre-transaction seed, its own fresh provider namespace, its own short-lived scenario token and a namespace-scoped fault schedule; no two scenarios share a database or a namespace. Copying the seed to a new file is safe while the source is quiescent (SQLite backup API), so scenarios never wait on one another's mutations. UI scenarios run serially within a world because there is exactly one Chromium/CUA session there; API scenarios may run in bounded parallel batches. The concurrency the demo shows is primarily across A/B/C worlds.

| ID | Surface | Exact case | Required outcome | Invariants |
| --- | --- | --- | --- | --- |
| `S01` | UI X | SKU-A, qty 1, no fault, £79.99 | PAID; 1 order/capture/confirmation; stock 99 | 01,02,04,05 |
| `S02` | UI Y | SKU-A, qty 1, `DROP_AFTER_CAPTURE_ONCE` | PAID only after inquiry; 1 capture/confirmation | 01,02,05 |
| `S03` | API | two concurrent submits, same intent | same order; 1 operation/capture/confirmation | 01,02,05 |
| `S04` | API | refresh/replay after paid | same order/confirmation; no new capture | 01,02 |
| `S05` | API | SKU-A qty 2, promo £10.00, loss after capture; £149.98 | PAID; one capture for 14998; stock 98 | 01,02,04 |
| `S06` | API | full refund £79.99, replay same refund intent | one refund; total 7999; `REFUNDED_FULL` | 01,02,03 |
| `S07` | API | distinct partial refunds £20 + £10; replay second | two refunds; total 3000; `REFUNDED_PARTIAL` | 01,02,03 |
| `S08` | API | `TIMEOUT_BEFORE_CAPTURE_ONCE` | PENDING; zero capture/confirmation; stock 100; no blind retry | 01,02,05 |

### 13.1 Negative controls

Run against the oracle, not as candidate fixes:

- `NC-01`: fake app state/UI says PAID but ledger has zero capture. Must fail `INV-02` and `INV-05`.
- `NC-02`: two orders share one intent and each has one capture. Must fail `INV-01` even though each order looks locally consistent.

Also unit-test same-key replay, same-key changed amount returns 409, unknown operation rejection, forged operation-to-intent mapping, simultaneous refund cap, cross-namespace access and original-ledger immutability.

### 13.2 Candidate verdict

A candidate is `PASS` only when:

- all required scenario IDs are present exactly once;
- the exact invariant set for each scenario is present;
- every invariant result is PASS with non-empty trusted evidence IDs;
- all hashes and namespaces match;
- no evaluator/provider/control error occurred;
- both negative controls failed for the expected reason in the current oracle build.

No invariant verdict depends on a browser frame stream. A `FRAME_STALLED` or `ERROR_FRAME_STREAM` outcome degrades the display/browser-evidence claim for that world only (see §3.1); it never changes a candidate's payment verdict.

Candidate status enum: `PENDING | RUNNING | PASS | FAIL | ERROR | SKIPPED_INVALID`. `ERROR` never sorts above a valid failure or becomes eligible.

---

## 14. Deterministic selection, staged smoke and lease

### 14.1 Selection policy

Code owns this fixed table:

| Rank | Candidate | Eligibility |
| --- | --- | --- |
| 0 | B prepared safe handler | live eligible only if full required evidence passes |
| 1 | A known-good release | evidence-only in this build |
| 2 | C Gemini patch | proposal-only in this build |

Selection outcome is therefore either `B` or `SAFE_HOLD_ESCALATE`. A and C remain valuable counterfactual and engineering evidence. The dashboard must not label A or C "deployable".

Two honesty rules keep this table from reading as "we always flip the switch we shipped":

1. **Counterfactual labelling.** Everywhere A and C appear — dashboard, receipt and video narration — they carry `COUNTERFACTUAL` / `PROPOSAL_ONLY` labels. Never imply they could have been auto-activated in this build.
2. **The claim is verification, not suspense.** For this fixture the safe handler is the correct repair, and pretending the outcome is uncertain would be theatre. The judge-facing claim is that the policy refuses anything unproven: a B that fails any gate produces `SAFE_HOLD + ESCALATED` rather than a hopeful activation, and the receipt states plainly that B was selected *because it passed every gate*, with A and C supplying counterfactual evidence rather than competition.

**Committed second live option (team decision, 19 September).** Install the previous release's checkout handler in the live image as the fourth hash-verified router mode `LEGACY` and default `POLICY_LIVE_A=1`. Rank 1 is then genuinely live-eligible under the identical evidence gate and staged smoke: if B fails any gate, policy routes to `LEGACY` instead of escalating, and the selection record states which live-eligible route passed with the lower configured disruption. This does not change the happy-path winner — B still wins when it passes — it changes whether a B failure is recoverable. **Hard drop rule:** if `LEGACY` is not built *and* tested by Gate G3, `POLICY_LIVE_A` is set to 0 for the run and the receipt states "single live-eligible candidate" explicitly rather than implying a choice that does not exist.

### 14.2 Staged smoke

The live app stays in `SAFE_HOLD`. Control creates 20 deterministic synthetic probe intents per stage, using fixed hash buckets:

- 5% stage: 1 routed through safe handler, 19 held; routed probe uses post-capture-loss case;
- 25% stage: 5 routed, 15 held; includes normal and loss cases;
- 100% stage: 20 routed, 0 held; includes at least 10 normal and 2 loss cases, remaining probes deterministic mix.

The router expresses each stage as `rollout_pct` (5/25/100) plus a stable `bucket_seed` over the probe intent ID, set through `PUT /internal/router` while `mode=SAFE_HOLD`, so "1 routed, 19 held" is exactly representable instead of being approximated by a boolean mode. The dashboard shows routed/held counts computed from actual bucket IDs, never from the requested percentage. Each routed probe uses its own provider operation and the same invariant oracle. Held probes must have zero captures. A stage fails on any invariant, unexpected routing count, stale generation or provider/evaluator error. If 60 probes threatens the T+6:00 cutoff, the reduced demo performs 5% and 100% and records 25% as omitted; it must not claim all three stages.

### 14.3 Repair lease

After staged smoke, issue a 120-minute synthetic-demo lease bound to:

- the selected live-eligible candidate (B or `LEGACY`) and its code/handler hash;
- exact evidence-set hash;
- live router generation and service epoch;
- scope `synthetic_checkout_router` only;
- UTC issue/expiry and 15-second guardian interval.

Expiry, guardian failure, handler/hash mismatch, service restart or Safe Stop changes the live route to `SAFE_HOLD`. It never restores `BUGGY`. The original double capture remains visible for reconciliation; NightWatch claims prevention of additional synthetic harm, not automatic reversal of the first harm.

---

### 14.4 Runtime budget and the sub-5-minute target

The team target is a **complete incident-to-receipt run under five minutes on warmed infrastructure**. It is measured with monotonic timestamps, reported honestly in the receipt, and never converted into a fake pass if missed. The two-minute figure is the *video*; five minutes is the *run*.

| Stage | Budget | How it stays cheap |
| --- | --- | --- |
| Detect → `SAFE_HOLD` + capsule | <10 s | Preauthorized router write plus one CAS transaction. |
| Bad-release reproduction | 20–30 s | Deterministic API replay of the frozen fault. The live store trigger already produced the UI-visible double capture, so reproduction does not pay for a second CUA journey. |
| Gemini diagnosis + patch proposal | 10–25 s | Runs in parallel with A/B world startup; C never blocks A/B. |
| World build + desktop boot (A/B/C) | 30–45 s | Pre-built image, warm services (`min_containers=1`), parallel `map.aio`; C starts as soon as its patch validates. |
| Scenario suite (all eight, per world) | 60–90 s | Eight scenarios × three worlds; API cases in bounded parallel batches (4–6 at a time) with per-scenario DB files; only S01/S02 use the browser. |
| Selection | <2 s | Policy lookup over completed evidence sets. |
| Staged smoke (60 probes) | 30–45 s | Probes are independent synthetic intents and run in bounded batches of 10 instead of sequentially; every probe is still oracle-checked individually. |
| Lease + readback + receipt | <10 s | One atomic write, one readback, one snapshot commit. |

Rules that make the budget real without weakening evidence:

- **Isolation replaces serialisation.** Serial execution protected shared state; per-scenario DB files, namespaces and tokens achieve identical isolation while allowing bounded parallelism (§12.2, §13).
- **The browser is the scarce resource, not the protocol.** One CUA session and one Chromium per world means UI scenarios never parallelise inside a world — but they already parallelise across A/B/C through the barrier.
- **Nothing slow is paid twice.** Reproduction is API-driven; Gemini overlaps world startup; staged smoke for B may begin as soon as B passes, while A and C keep running and only update the receipt without changing an issued lease.
- **Back-pressure over speed.** If a batch would exceed per-world CPU or the frame-ingest caps, the scheduler lowers batch size rather than dropping oracle checks. A slower truthful run beats a fast unverified one.
- **Measure, then report.** The receipt carries measured per-stage wall-clock times and the dashboard shows the real elapsed clock. p50/p95 come from rehearsals, never from vendor microbenchmarks.

## 15. Dashboard and operator experience

Build one responsive 1440p-first command centre; no authentication UX beyond operator-token entry for the hackathon. The dashboard is a projection of committed control-plane events and current `BrowserFrame` objects. It is not the orchestrator and cannot manufacture progress.

```text
+-- NIGHTWATCH | incident NW-001 | SAFE_HOLD | elapsed 01:42 | SAFE STOP --+
| LIVE NIGHTMART                         | TRUSTED MONEY TRUTH              |
| checkout says PAID / HTTP 200          | logical intent: pi_live_001      |
| before: DROP_AFTER_CAPTURE_ONCE        | CAPTURE £79.99 x2  [INCIDENT]   |
| after: protected checkout pending      | original rows remain immutable   |
+----------------------------------------+----------------------------------+
| CANDIDATE A / ROLLBACK                 | CANDIDATE B / SAFE HANDLER        |
| [actual CUA screenshot, 16:9]          | [actual CUA screenshot, 16:9]    |
| RUNNING · 1.8 fps · step 4 · S02       | RUNNING · 2.0 fps · step 5 · S02|
| sb-a91… · cua-7e… · snap-31…           | sb-b82… · cua-19… · snap-48…     |
| Jev: click "Pay now" · oracle pending | Jev: open "Add voucher"          |
+----------------------------------------+----------------------------------+
| CANDIDATE C / GEMINI PATCH             | DECISION + SCHEMA GATE           |
| [actual CUA screenshot, 16:9]          | B eligible / A failed / C proof  |
| RUNNING · 1.6 fps · step 3 · S02       | Pydantic: 214 valid / 1 rejected |
| sb-c73… · cua-4c… · snap-27…           | staged 5% -> 25% -> 100%         |
| Jev: type fixture email · oracle wait  | lease, guardian, receipt hashes  |
+----------------------------------------+----------------------------------+
| TIMELINE: DETECT -> HOLD -> FREEZE -> SPAWN 3 -> BARRIER -> TEST -> LEASE |
| Gemini hypotheses/evidence | lifecycle overlap graph | download receipt   |
+----------------------------------------------------------------------------+
```

The `Pydantic: n valid / m rejected` counter means boundary-model validations performed in this run, counted from the validation audit table; the dashboard shows that definition on hover so the number is never decorative. Candidate cards likewise show a real reason for every eligibility decision, never a bare score.

### 15.1 Three-browser wall

The A/B/C panes are the centrepiece, not thumbnail decoration. Each pane:

- renders only the newest hash-verified screenshot captured from the CUA session inside that candidate's own Modal Sandbox;
- fetches `/api/runs/{run_id}/frames/{candidate_id}/latest?after={last_seq}` every 500 ms and also reacts immediately to `browser.frame` SSE metadata; responses use `Cache-Control: no-store`, an ETag equal to the image hash and a monotonically increasing sequence;
- shows actual measured rolling FPS over the last five seconds, last-frame age, Sandbox ID, CUA session ID, short snapshot ID, scenario, action number, Jev-selected label and trusted-oracle state;
- keeps the last genuine frame visible after completion and labels it `COMPLETE`, `FAILED`, `ABSTAINED` or `WAITING`; it never loops a recording or duplicates another candidate's frame;
- turns amber after 5 seconds without a new frame and red after 10 seconds, with the stall clock frozen while a CUA action is in flight, exactly matching the backend `ERROR_FRAME_STREAM` transition;
- opens a detail drawer containing the semantic controls offered to Jev, the Choice distribution, freshness checks, action result and independent ledger/app postcondition.

Active panes must sustain at least one genuinely new frame each second and target two. The default capture is 960x540 JPEG or WebP at an event-tested quality, capped by the `BrowserFrame` schema. Only the latest frame is retained in hot control storage; before/after/action/terminal keyframes go into the evidence bundle. This bounds memory while preserving the proof trail.

### 15.2 Operator story and visual rules

- Money truth is the hero: show two ledger captures beside the healthy HTTP/UI, then one capture after activation.
- Start A/B/C through one `Run candidates` action. The button becomes disabled after the idempotent run command is accepted.
- Release the synchronized browser barrier only when all three eligible panes report `BROWSER_READY`; display the two-second start skew and lifecycle overlap graph.
- Always label whether a fact is `OBSERVED`, `MODEL_PROPOSED`, `POLICY_DECIDED` or `TRUSTED_VERIFIED`.
- Candidate cards show real IDs, hashes, scenario counts, invariant failures and cleanup state.
- Gemini text is summarized into typed hypotheses, not a wall of prose.
- The Jev detail shows the exact bounded options, selection distribution and verification status; confidence never creates a green pass.
- Red means invariant failure, amber means uncertainty/hold/stall, green means trusted verification only.
- Safe Stop stays fixed in the top bar and requires one confirmation; its result is read back from the router before the UI changes.
- SSE reconnect uses `Last-Event-ID`; refresh reconstructs the view from persisted events and then refetches the three latest frames.
- A fourth full-width `Protected live checkout` drawer appears only after B's lease readback. Jev + CUA drives the same Modal-hosted NightMart URL and the ledger visibly remains at one capture for the new intent.

---

## 16. Repository shape and frozen contracts

```text
NightWatch/
  README.md
  Final-nightwatch-plan.md
  pyproject.toml
  uv.lock
  .env.example
  modal_app.py                 # thin shim only: imports services_a + services_b; exported function names are frozen
  modal/
    services_a.py              # control/live_store/provider/orchestrator definitions (Track A)
    services_b.py              # run_candidate + pinned desktop image wiring (Track B)
  apps/
    contracts/
      base.py
      incident.py
      payment.py
      browser.py
      evaluation.py
      lease.py
    control_plane/
      app.py
      config.py
      store.py
      state_machine.py
      events.py
      routes.py
      receipt.py
      static/                 # generated at deploy from apps/dashboard/dist, gitignored, mounted read-only
    live_store/
      app.py
      store.py
      router.py
      domain/
        checkout.py
        payment_retry.py      # only Candidate C patch target
        refund.py
    trusted_provider/
      app.py
      auth.py
      ledger.py
      faults.py
    dashboard/                # React/Vite source
    storefront/               # minimal static UI X/Y source
  services/
    detector.py
    capsule.py
    gemini_agent.py
    patch_guard.py
    candidate_factory.py
    scheduler.py
    oracle.py
    selector.py
    canary.py
    lease_guardian.py
    frames/
      frame_store.py           # latest frame slot + evidence keyframe manifest (Track B)
      browser_barrier.py       # readiness generation and synchronized release (Track B)
    jev/
      questions.py            # all questions/thresholds in one reviewable file
      observe.py
      decide.py
      execute.py               # strict Jev decision and freshness guard
      cua_client.py            # trusted runner -> world-local CUA socket
      frame_stream.py          # 1 fps minimum / 2 fps target sampler
    worlds/
      interface.py
      modal_world.py
      local_world.py          # labelled dev fallback only
  infra/
    modal_desktop_image.py    # pinned X11/AT-SPI/Chromium/CUA image
    start_desktop_world.sh    # starts display, app, browser and CUA daemon
    cua_capabilities.json     # generated bounded browser-only manifest
  fixtures/
    store_seed.sql
    scenarios.json
    expected/
  scripts/
    preflight.py
    reset_demo.py
    run_demo.py
    verify_receipt.py
    benchmark_browser.py
    verify_browser_stack.py   # dependency/import/runtime allowlist gate
    secret_scan.py
  tests/
    unit/
    integration/
    isolation/
    browser/
    fault_injection/
  docs/
    ARCHITECTURE.md
    API.md
    DEMO.md
    SAFETY.md
```

### 16.1 Contract-freeze contents

At T+0:20 both branches must share and stop independently editing:

- package/tool versions and lockfile;
- all `apps/contracts/**` models and generated JSON Schemas;
- `fixtures/scenarios.json`, scenario IDs and invariant matrix;
- endpoint method/path/body/response examples, **including a frozen multipart example plus contract test for `POST /internal/frames`**, shipped by Track A inside the first hour so Track B is never blocked on a schema it cannot see;
- the single codegen path from committed JSON Schemas to dashboard TypeScript types (`npm run gen:types`), so no hand-written client schema exists on either branch;
- service interfaces in `services/worlds/interface.py`;
- the `modal_app.py` exported-function-name list, and the `apps/live_store/**` bundle hash (re-frozen at T+2:20 under §6);
- a three-environment Modal layout: `nightwatch-a` (Jazil / Track A services), `nightwatch-b` (Akshay / Track B), and `nightwatch-demo` for the integrated app, which only **Jazil** deploys from `integration/nightwatch-demo`; Akshay may use `modal serve` / `modal run` for ephemeral dev but never `modal deploy`;
- expected environment variable names;
- seed, scenario and contract hashes.

One designated contract owner makes later contract edits. The other builder requests the change and rebases. No duplicated "temporary" schemas on separate branches.

---

## 17. Clean two-branch ownership

The split is fixed: **Jazil owns Track A, Akshay owns Track B.** Do not divide a track across laptops, and do not swap paths mid-build.

### Track A: domain, authority, Gemini and proof

**Owns exclusively:**

- `apps/contracts/**` after joint freeze (Track A is the contract owner for this package);
- `apps/live_store/**`;
- `apps/trusted_provider/**`;
- `apps/control_plane/**` Python **except** the frame/barrier implementation, which lives in `services/frames/**` and belongs to Track B; Track A owns the routes, state machine, events, receipt and the frame-ingest HTTP contract;
- `modal/services_a.py`;
- `services/detector.py`, `capsule.py`, `gemini_agent.py`, `patch_guard.py`, `oracle.py`, `selector.py`, `canary.py`, `lease_guardian.py`;
- `scripts/preflight.py`, `scripts/run_demo.py`, `scripts/reset_demo.py`, `scripts/verify_receipt.py`, `scripts/secret_scan.py`, and `tests/conftest.py`;
- fixtures and deterministic unit/integration/fault tests;
- final README and docs after merge.

**Track A done means:**

- buggy fixture reliably produces two captures while health is 200;
- safe handler passes local S01/S02/S08 and negative controls catch lies;
- the `LEGACY` route handler is installed, hash-verified and passes the same local suite — or it is explicitly disabled at Gate G3 and the receipt says so;
- strict models reject malformed objects;
- state CAS, safe hold, selector and lease activation/readback work locally;
- Gemini can return a typed diagnosis and bounded proposal, with invalid fallback;
- receipt can be generated and independently verified.

### Track B: Modal, Jev, browsers and presentation

**Owns exclusively:**

- `modal/services_b.py` plus the shim `modal_app.py` (function names frozen; import wiring only);
- `services/worlds/**`;
- `services/scheduler.py`;
- `services/jev/**`;
- `services/frames/**` (frame store, browser barrier, CUA session plumbing);
- `apps/dashboard/**` including the built `dist/`, and `apps/storefront/**`;
- `scripts/benchmark_browser.py`, `scripts/verify_browser_stack.py`;
- Modal/isolation/browser tests;
- browser benchmark and visual demo script.

**Track B done means:**

- three specs create three distinct concurrent Modal Sandboxes with real lifecycle evidence;
- candidate endpoint uses Connect Token and cleanup is guaranteed;
- every A/B/C runner starts its own Chromium profile and CUA session inside its own Modal Sandbox; cleanup is proven;
- the official CUA `jev-use` preflight passes, then Jev + CUA controls UI X and Y with snapshot-freshness and abstention guards;
- the three dashboard panes render the exact sandbox CUA screenshots at a measured minimum 1 fps and target 2 fps, with honest stall states, plus real SSE events and Safe Stop;
- a local adapter implements the same `WorldRunner` interface for development, visibly labelled when used.

### Shared files and rule

Only during the first twenty minutes may both edit `pyproject.toml`, `.env.example`, contracts and interfaces. After the freeze, Track A owns dependency/contracts/docs changes; Track B requests them in a short `CONTRACT_CHANGE.md` or message. Track B never edits `pyproject.toml`, `uv.lock` or the frozen exported signatures in `modal_app.py`: a needed change is appended to `CONTRACT_CHANGE.md` on its own branch and is *not* implemented locally, which is what stops two AI agents from quietly inventing parallel schemas. Each track deploys only to its own `MODAL_ENVIRONMENT`; **Jazil is the sole designated deployer** because the hackathon credits live on his workspace, and the integrated app deploys to `nightwatch-demo` only from the integration branch. Each commit must touch owned paths only. Both builders are working in the same codebase and must not revert or overwrite the other's changes.

---

## 18. Six-hour execution plan with gates

**Clock.** `T+0` is whenever the two of you actually start coding — deliberately not fixed in advance. Every milestone below is an offset from `T+0`, with two absolute anchors that never move: **19:00 submission** and **20:00 live demo**. If the start slips, cut ambition from the **back** of the schedule (declare reduced mode at the first gate you can no longer reach) — never compress the gates themselves, and never convert a missed gate into a pass.

### T+0:00–T+0:20: joint credential preflight and contract freeze

- Create both track worktrees and the shared `integration/nightwatch-demo` branch from the same clean base (§19).
- Run the smallest live call for Gemini structured output, Jev dynamic choice and Modal sandbox/connect-token/readiness.
- Run CUA's official mock and live `jev-use` dependency checks, start building the pinned desktop image, and freeze the CUA/frame/barrier interfaces. The complete CUA-in-Modal proof has a separate T+0:50 gate.
- Confirm provider-to-sandbox network path.
- Freeze schemas, scenarios, interfaces, env names and ownership.
- Record actual package/model versions. Never build around an untested assumed API.

**Gate P at T+0:20:** all credentials are classified `WORKING`, `FAILED` or `UNAVAILABLE`; frozen contract tests pass. A failed optional service is removed now, not debugged at T+5:30. Jev and CUA are required rather than silently replaced.

### T+0:20–T+1:20: make the incident undeniable

Track A (the first ~45 minutes are contract-critical — Track B's whole critical path is blocked until these land, so they come first):

- **ship the strict `apps/contracts/browser.py` models, the `POST /internal/frames` multipart contract with a frozen example and contract test, and the barrier endpoints**;
- provider ledger/idempotency/operation registration;
- intent/order/payment tables and buggy/safe retry handlers;
- post-capture response-loss fault;
- original incident trigger and detector.

Track B:

- Modal trusted-service smoke;
- build the pinned Modal desktop image and complete the Section 11.8 CUA-in-Modal proof by T+0:50;
- candidate runner interface and A/B sandbox lifecycle;
- storefront UI X/Y shell and dashboard event shell;
- shared Jev/CUA observation/action contract and first real frame ingest.

**Gate CUA at T+0:50:** one Modal Sandbox proves X11/AT-SPI, Chromium, world-local CUA Driver, a live Jev Choice, one executed action, one independent postcondition and at least five genuine frames over five seconds. If this fails, Track B keeps the core/API-only demo as the default deliverable while continuing this exact stack, and Track A carries on regardless; no second browser controller is introduced.

**Gate G0 at T+1:20:** one logical intent makes exactly two ledger captures while `/health` is 200; original namespace cannot be reset. If this fails, stop all polish until it works.

### T+1:20–T+2:20: independent proof and isolation

Track A:

- INV-01–06 oracle;
- S01/S02/S08, negative controls and seed reset;
- state transitions through `SAFE_HOLD` and capsule freeze.

Track B:

- A/B world creation with separate namespaces/DBs;
- authenticated endpoint/readiness/cleanup;
- first real Jev + CUA journey with a fresh isolated profile/session and independent postcondition;
- measured overlapping workers.

**Gate G1 at T+2:20:** A/B concurrently run S02 and S08; oracle catches both negative controls; original ledger digest is unchanged; peak concurrency is at least two.

### T+2:20–T+3:20: control loop and visible product

Track A:

- full CAS state machine, idempotent run, event log/SSE;
- selector, safe-handler router and fail-closed lease/readback;
- `LEGACY` route mode, handler hash verification and its local test slice;
- S03–S07 API scenarios.

Track B:

- dashboard money-truth view and candidate cards;
- three-pane frame wall plus Jev UI X/Y loop with freshness/abstention;
- event replay and Safe Stop button.

**Gate G2 at T+3:20:** deterministic local end-to-end run succeeds without Gemini or Jev; safe-stop race cannot activate BUGGY; dashboard refresh reconstructs committed truth.

### T+3:20–T+4:20: AI and three-world race

Track A:

- Gemini diagnosis and Candidate C patch guard;
- receipt, schema rejection demo and optional Logfire;
- full oracle/evidence-set validation.

Track B:

- C bundle support;
- three-world `.map.aio` race and lifecycle metrics;
- real Jev runs in both variants with CUA session/snapshot-bound evidence and 1 fps minimum/2 fps target frame streams from all three worlds;
- isolation and candidate teardown tests.

**Gate G3 at T+4:20:** actual A/B/C calls start; three Sandbox IDs, three CUA session IDs and three Chromium process/profile IDs exist; two workers overlap; every active tile sustains at least 1 fps. If C is `SKIPPED_INVALID`, declare reduced mode and stop claiming a three-world browser race. No dashboard animation may outrun evidence.

### T+4:20–T+5:20: integration and recovery

- Run S01–S08 for all eligible candidates.
- Run negative controls once per oracle build.
- Select B or remain held.
- Execute staged smoke and issue/read back lease.
- Demonstrate guardian and Safe Stop.

**Gate G4 at T+5:20:** full or core mode is declared from evidence. Two clean rehearsals are required after the last material change. Do not add optional scope after this gate.

### T+5:20–T+6:00: freeze and package

- Merge with the protocol below.
- Run all automated gates and two `run_demo --verify` passes.
- Finalise README, architecture/API/safety/demo docs and receipt example.
- Secret-scan the public repo, its git history, screenshots and logs.
- Tag `demo-freeze` locally.

### T+6:00 until the 19:00 deadline: submission-only buffer

- Keep the public sync repository current and verify a clone-from-scratch setup from it.
- Submit source and explanation; the video is handled separately and is not a build task.
- No feature work unless it fixes a submission blocker.

---

## 19. Branch, worktree and merge protocol

Recommended branch names:

- `hackathon-base` from current `main`;
- `track-a/control-proof` and `track-b/modal-jev-cua-ui` from the frozen base;
- `integration/nightwatch-demo` for the merge.

**Repo/sync decision (team, 19 September): the GitHub repo is public and is the sync remote.** `origin` (`github.com/AkshayReddyGujjula/NightWatch.git`) is the shared repository; both laptops clone from it and push at every gate boundary so the two worktrees always share a base. This makes the repo part of the trust boundary: **API keys and tokens are shared separately, out-of-band, and are never committed, logged or screenshotted** — a secret scan is mandatory before every push (§21, §23).

Safe sequence:

1. Verify `git status`, current branch, remotes and existing worktrees.
2. Commit the T+0:20 frozen contracts on `hackathon-base`; tag `contract-freeze`.
3. Create three branches from that exact commit: the two track worktrees plus `integration/nightwatch-demo`. **T+5:20 is the last merge, not the first.** At every gate boundary (T+1:20, T+2:20, T+3:20, T+4:20) each track merges its tip into `integration/nightwatch-demo` and both run one shared `contract-check` command, so a conflict is found within the hour it was created instead of at the end of the day.
4. Commit small vertical slices only in owned paths.
5. At T+5:20 both stop editing and provide branch SHA, `git status`, test summary and changed-path list.
6. Create a backup ref for both tips.
7. Preview integration with `git merge-tree --write-tree` and audit any path overlap.
8. Track A merges first, then Track B rebases onto the result; confirm contract compatibility before the rebase, not during it.
9. Resolve only explicit ownership/contract conflicts; never accept a broad generated rewrite.
10. Run the full gate suite and two demo resets/runs before tagging `demo-freeze`.

The team has authorised ordinary pushes to the public sync repository. Force-pushes, history rewrites and anything that could expose a secret remain forbidden; run the secret scan before every push.

---

## 20. Automated test matrix

### Unit

- strict Pydantic extra-field/type/time/hash/enum rejection;
- provider same-key replay, changed-parameter 409 and operation registration;
- order/operation/confirmation/fulfillment uniqueness under concurrency;
- safe-handler timeout branches;
- refund replay and parallel cap;
- diff parser/path/line/import/symlink/binary rejection;
- exact evidence-set validation;
- selector cannot choose A/C/ERROR/missing evidence;
- `StrictModel` rejects attribute assignment because it is frozen, and no model depends on `validate_assignment`;
- lease expiry and state transition matrix.

### Integration

- buggy incident creates two captures and preserves original;
- SAFE_HOLD creates zero new captures;
- S01–S08 against safe handler;
- NC-01/NC-02 fail expected invariants;
- staged routing counts are exact;
- staged routing is expressed as `rollout_pct` + `bucket_seed`, and the reported routed/held counts are computed from actual bucket IDs rather than from the requested percentage;
- router CAS/readback/hash/epoch mismatch fails closed;
- receipt hash verifies.

### Race/fault injection

- two simultaneous checkout submissions;
- simultaneous refunds;
- `/run` vs `/safe-stop`;
- safe-stop at each lease boundary;
- provider loss before capture, after capture and inquiry unavailable;
- worker crash, readiness timeout, browser timeout and evidence-upload retry;
- restart from every control transition defaults to hold.

### Isolation

- A/B/C one-shot faults cannot consume one another;
- candidate tokens cannot read ledger/evaluator/internal routes;
- candidate cannot access another namespace;
- original ledger digest unchanged;
- three distinct DB paths, namespaces, Sandbox IDs and browser processes;
- cleanup terminates all sandboxes after success/error/cancellation.

### Browser/Jev

- official CUA mock connection check, live Jev check, in-sandbox isolated-profile cleanup and Modal-origin navigation pass;
- both UI variants complete with Jev choosing every browser action and CUA Driver executing every browser action;
- A/B/C show distinct Modal Sandbox, Chromium, CUA session and snapshot IDs; their S02 intervals overlap and their screenshot hashes differ where the rendered states differ;
- each active world emits at least five fresh captures during a five-second acceptance window, with strictly increasing sequence/time and matching computed image hashes; identical bytes are allowed only for a newly captured unchanged screen, never by replaying a prior sequence or another candidate's frame;
- stale action ID, changed page generation, invisible/disabled target and invalid fixture value refuse execution;
- stale CUA snapshot/ref/capture ID and cross-session target refuse execution;
- malicious DOM instruction has no policy effect;
- low-margin decision reobserves/abstains;
- uncertain submit never repeats capture;
- every click asserts the explicit `input_route: dom_event` path and never treats dispatch as proof of activation;
- a snapshot offering more than 253 candidate actions fails closed with a logged omitted count;
- the frame sampler never mints a snapshot that invalidates a ref Jev judged, and a stalled tile never changes a candidate's verdict;
- `DONE_UNVERIFIED` with false UI fails the oracle.

### Final commands

Exact commands depend on the frozen toolchain, but README must expose one canonical set such as:

```powershell
uv sync --frozen
uv run ruff check .
uv run mypy apps services
uv run pytest tests/unit tests/integration tests/fault_injection tests/isolation
uv run python scripts/preflight.py
uv run python scripts/run_demo.py --mode full --verify
uv run python scripts/run_demo.py --mode full --verify
uv run python scripts/verify_receipt.py artifacts/latest/receipt.json
uv run python scripts/verify_browser_stack.py
uv run python scripts/secret_scan.py
```

If frontend tooling is separate, add `npm ci`, lint, test and build commands and pin Node/package-lock. Do not leave setup as prose-only instructions.

---

## 21. Secrets, logging and observability

### Environment variables

```text
GOOGLE_API_KEY=
GEMINI_MODEL=
TYPESAFE_API_KEY=
TYPESAFE_MODEL=jev-1.13.0
MODAL_ENVIRONMENT=
POLICY_LIVE_A=1                # §14.1 committed second live option; set to 0 only if LEGACY is not built and tested by Gate G3
NIGHTWATCH_OPERATOR_TOKEN=
CONTROL_EVENT_TOKEN=
LIVE_INTERNAL_TOKEN=
PROVIDER_SIGNING_SECRET=
EVALUATOR_TOKEN=
LOGFIRE_TOKEN=                 # optional
CONDUCT_API_KEY=               # optional; unused unless real integration passes
CUA_DRIVER_VERSION=            # record exact installed version
CHROMIUM_VERSION=              # record exact desktop-image version
FRAME_INGEST_TOKEN=            # runner-only, scoped to one run/candidate
```

Create separate Modal Secrets for each function. Candidate sandboxes receive only their short-lived provider token through the process environment; they never inherit the runner's TypeSafe key.

Structured logs contain incident/run/candidate/scenario IDs, event/evidence hashes, status and durations. Redact authorization, cookies, token query parameters, Gemini/Jev raw secrets and customer fixture email. Do not put Connect Tokens in dashboard URLs, screenshots or receipt.

Pydantic Logfire is optional hosted observability, not the source of truth. If working, instrument Pydantic AI and key validation spans with redaction. The canonical local/Modal event table and receipt remain sufficient if Logfire is unavailable.

---

## 22. Presentation and video

Out of scope for this plan by team decision. The two-minute video and the live demo are handled separately by the team, and nothing in the build should be shaped around recording them.

What still matters to whoever presents: §3.1/§3.2 define what must actually run, §14.4 and the receipt carry the measured timings and evidence, and §15 defines the dashboard. The honest-mode rules (§3.2, §24, §29) apply to anything shown — no fabricated numbers, no replayed frames, and every degraded mode labelled as such.

---

## 23. README and submission checklist

README must contain, in this order:

1. one-sentence problem and a GIF/screenshot of duplicate-capture evidence;
2. architecture diagram and trust-boundary explanation;
3. exact partner roles and truthful degraded modes;
4. prerequisites, account/credit requirements and pinned versions;
5. `.env.example` field-by-field setup with no secrets;
6. local core-demo commands and Modal full-demo deploy/run commands;
7. test commands and expected output;
8. API endpoint table and links to `docs/API.md`;
9. safety model, limitations and synthetic-data statement;
10. public demo URL if stable, and an example receipt (the video is handled separately);
11. team members and explicit event-build disclosure.

Before 19:00 verify:

- public repository contains full source and correct licence;
- clone into a fresh directory and follow README once;
- no `.env`, keys, tokens, private URLs, cookies or personal paths in source/history/artifacts;
- all partner claims match the latest receipt;
- API/framework/tool docs are present;
- screenshots show no token query strings;
- submitted demo URL works or is clearly marked recorded/local;
- final commit SHA and receipt hash are recorded in submission text.

---

## 24. Kill switches and truthful fallback matrix

| Failure | Automatic behaviour | What may still be claimed |
| --- | --- | --- |
| Gemini unavailable/invalid | C=`SKIPPED_INVALID`; continue A/B; remain held unless B passes | Modal/Pydantic/core recovery; no Gemini patch claim |
| Jev unavailable | Browser tasks fail closed; continue deterministic API evidence while fixing the Jev call | Reduced API-only system; no browser-agent/TypeSafe claim |
| CUA Driver setup/runtime fails | Browser tasks fail closed; preserve Modal/API work and keep Track B focused on the single Jev + CUA stack | Reduced API-only system; no browser-agent/CUA claim |
| Jev low confidence/stale | reobserve once then abstain; candidate UI scenario fails | Safe abstention; never blind action |
| Modal unavailable | local adapter can demonstrate logic; hold live route unless separately verified | Product concept only; no Best Use of Modal claim |
| One sandbox fails | mark candidate ERROR, clean it up; exact evidence set prevents accidental pass | Remaining outcomes, but full three-world claim only if all actually ran |
| Provider/evaluator unavailable | fail candidate/run; `SAFE_HOLD` | Containment and escalation |
| Gemini patch violates guard | reject before Sandbox C | Visible Pydantic/patch safety gate |
| All candidates fail | `SAFE_HOLD + ESCALATED` | Correct autonomous refusal |
| Dashboard disconnects | control run continues; replay committed SSE on reconnect | Backend evidence, not live animation |
| Lease guardian fails/expires | live route -> `SAFE_HOLD` | Revocable containment |
| Snapshot/restart uncertainty | restore data if verified, increment epoch, remain held | No durable-HA claim |
| Conduct unavailable | no logo/integration claim; local workflow map may be labelled static | Nothing lost from core demo |
| 180-second target exceeded | report actual duration; do not turn timeout into PASS | Correctness and measured performance |

`SAFE_HOLD` means reads, history and reconciliation remain available, but new synthetic payment capture is refused/pending. It is a containment mode, not a claim that checkout is fully available.

---

## 25. Architecture decisions

### ADR-001: one silent payment incident

**Status:** Accepted  
**Decision:** build the duplicate-capture incident only.  
**Alternatives:** SQLi/IDOR suite; generic broken checkout; multiple incidents.  
**Reason:** a healthy-HTTP/money-wrong failure is instantly legible, tests real invariants and supports all partner technologies without spreading two people across unrelated demos.  
**Consequence:** `flow.md` attack scenarios are roadmap material and should be labelled superseded in README.

### ADR-002: deterministic authority around AI

**Status:** Accepted  
**Decision:** Jev selects bounded semantic actions; Gemini produces bounded diagnosis/patch proposals; code owns money, policy, evidence and actuation.  
**Alternative:** conversational autonomous repair agent.  
**Reason:** typed output is an interface guarantee, not a truth guarantee. Financial correctness needs independent evidence.  
**Consequence:** more explicit schemas and oracle code, substantially stronger judge credibility.

### ADR-003: activate only a preinstalled safe handler

**Status:** Accepted  
**Decision:** Candidate C is proposal-only; Candidate B may activate by feature route in the current live process/DB.  
**Alternatives:** redeploy the generated patch; point production at the passing sandbox; replace live DB with candidate state.  
**Reason:** the alternatives require build provenance, database/state transfer and rollback semantics that cannot be made credible in six hours.  
**Consequence:** the demo honestly proves automated containment and verified code proposal, not autonomous permanent production patching.

### ADR-004: separate provider/evaluator from candidates

**Status:** Accepted  
**Decision:** provider ledger and oracle are trusted external services; candidate app state is only one evidence source.  
**Alternative:** each world owns and reports its own mock ledger.  
**Reason:** code under test must not be able to forge the evidence that passes it.  
**Consequence:** more authentication/namespace plumbing; much stronger proof.

### ADR-005: Modal Functions orchestrate Modal Sandboxes

**Status:** Accepted  
**Decision:** `run_candidate.map.aio` gives three trusted runners; each runner creates exactly one desktop Sandbox containing exactly one candidate app, Chromium profile/process and CUA session for the synchronized hero scenario.  
**Alternatives:** three sequential sandboxes; local Docker; a single shared browser.  
**Reason:** explicit concurrency is central to the product and Modal prize, while separate browsers avoid cross-world state.  
**Consequence:** lifecycle/cleanup must be first-class and real IDs must be shown.

### ADR-006: single-writer SQLite with closed Volume snapshots

**Status:** Accepted for demo, revisit for production  
**Decision:** each trusted stateful service has one container/writer, local SQLite and verified closed snapshots to its own Modal Volume.  
**Alternatives:** live SQLite file concurrently mounted on Volume; external Postgres; in-memory only.  
**Reason:** avoids concurrent same-file Volume semantics and extra database setup while preserving restart evidence.  
**Consequence:** no HA claim; restart is fail-closed and snapshot logic has an early kill criterion.

### ADR-007: CUA Driver executes the visible Jev journey

**Status:** Accepted behind the T+0:50 hard preflight gate  
**Decision:** run CUA Driver, a real Chromium process and a minimal X11/AT-SPI desktop inside each A/B/C Modal Sandbox. The trusted runner calls that world-local CUA daemon; Jev is the only action selector and CUA is the only browser observation/execution layer. Playwright is prohibited from dependencies, imports, generated code and runtime commands.  
**Alternatives considered:** a second browser automation stack; a laptop-side browser worker; CUA Fleet; browser sessions outside the candidate worlds.  
**Reason:** the judges must see the three actual isolated experiments, not three local proxies. CUA's official `jev-use` pattern provides semantic snapshot-bound actions, abstention and independent postcondition patterns, while Modal supplies the required isolation and concurrency. CUA Fleet would duplicate Modal.  
**Consequence:** the pinned desktop image and CUA-in-Modal smoke are the highest-risk Track B gate. UI evidence remains corroborative because candidate code shares the world; trusted provider/app-state evidence decides invariants. If the gate fails, the team reports a reduced API-only demo instead of substituting another browser controller.

---

## 26. Production roadmap, clearly separated from this build

After the hackathon, the next steps are:

- replace mock provider with provider-specific idempotency/inquiry adapters and reconciliation feeds;
- external transactional database, durable queue and mutually authenticated workload identity;
- signed build provenance, policy-as-code review and human approval for generated patches;
- deployment/state/schema compatibility analysis for rollback candidates;
- calibrated Jev datasets and action-risk-specific thresholds;
- customer-specific playbooks, blast-radius estimation and approval tiers;
- immutable audit store and formal evidence retention;
- real Conduct integration if it adds verified code-to-business-process context;
- broader incidents only after each has its own oracle and containment action.

Do not present roadmap items as implemented.

---

## 27. Copy-paste implementation prompt: Track A

> You own the NightWatch domain, trusted authority, Gemini and proof track. Read `Final-nightwatch-plan.md` fully before editing. You are not alone in the repository: another agent owns Modal worlds, Jev, browser automation and UI. Do not edit or revert their paths. Start from the `contract-freeze` commit in your own worktree: `git worktree add ../nw-track-a -b track-a/control-proof <CONTRACT_FREEZE_SHA>`. You own exactly the Track A paths in Section 17; you must not edit `modal/services_b.py`, `services/worlds/**`, `services/jev/**`, `services/frames/**`, `apps/dashboard/**` or `apps/storefront/**`. Any change you need in a file you do not own is appended to `CONTRACT_CHANGE.md` on your branch — do not implement it locally. Deploy only to `MODAL_ENVIRONMENT=nightwatch-a`. First verify the `contract-freeze` commit and generated Pydantic schemas. Implement only Track A-owned paths from Section 17. Work vertically in this order: trusted provider and ledger; buggy/safe retry handlers and real duplicate reproduction; invariant oracle and S01/S02/S08/negative controls; state CAS and SAFE_HOLD; full S03–S07; selector and fail-closed lease/readback; Gemini typed diagnosis and bounded patch guard; receipt and docs. Run the relevant tests after every slice. Never let a model response become a command or lease. Never reset the original namespace. If an interface change is needed, stop and request it from the contract owner instead of creating a second schema. At handoff provide branch SHA, clean/dirty status, changed paths, exact test commands/results, known gaps and any required contract change.

## 28. Copy-paste implementation prompt: Track B

> You own the NightWatch Modal, Jev, CUA/browser and presentation track. Read `Final-nightwatch-plan.md` fully before editing. You are not alone in the repository: another agent owns contracts, live store/provider, control authority, oracle, Gemini and receipt. Do not edit or revert their paths. Start from the `contract-freeze` commit in your own worktree: `git worktree add ../nw-track-b -b track-b/modal-jev-cua-ui <CONTRACT_FREEZE_SHA>`. You own exactly the Track B paths in Section 17; you must not edit `pyproject.toml`, `uv.lock`, `apps/contracts/**`, `apps/live_store/**`, `apps/trusted_provider/**`, the control-plane routes, `services/detector.py`, `capsule.py`, `gemini_agent.py`, `patch_guard.py`, `oracle.py`, `selector.py` or `canary.py`. Any change you need in a file you do not own is appended to `CONTRACT_CHANGE.md` on your branch — do not implement it locally. Deploy only to `MODAL_ENVIRONMENT=nightwatch-b`, and only if you are the designated deployer. Verify the `contract-freeze` commit and `WorldRunner`/event/frame/barrier interfaces. Implement only Track B-owned paths from Section 17. Your first deliverable is the Section 11.8 proof: one pinned Modal desktop Sandbox running X11/AT-SPI, real Chromium and a world-local CUA Driver; one live Jev Choice from the trusted runner; one CUA action; one independent postcondition; and at least five fresh dashboard frames in five seconds. CUA Driver is the only browser observer/executor and Jev is the only action selector. Playwright is forbidden. Then work vertically: A/B concurrent runners; UI X/Y; three-world barrier and `.map.aio` race; synchronized three-pane 1 fps minimum/2 fps target frame wall; C bundle; lifecycle/concurrency evidence; SSE replay and Safe Stop; browser/isolation tests. Each runner invocation creates exactly one candidate Sandbox, and every candidate's browser and CUA session live inside that same Sandbox. Jev returns decisions only and code validates snapshot/session/origin freshness before CUA acts. Never pass secrets into candidate sandboxes or interpolate patch text into a shell. If an interface change is needed, request it from the contract owner. At handoff provide branch SHA, clean/dirty status, changed paths, exact test commands/results, per-pane measured FPS, CUA/Chromium/session/snapshot evidence, real Sandbox/function IDs, known gaps and fallback mode.

---

## 29. Final go/no-go checklist

At T+5:20 answer every line from evidence:

- [ ] Is the incident one intent with two real ledger captures while health is 200?
- [ ] Is the original ledger preserved after all candidate runs?
- [ ] Did SAFE_HOLD precede experimentation and create zero new captures?
- [ ] Are A/B/C distinct real Modal Sandboxes, and did at least two overlap?
- [ ] Does every candidate have distinct DB/namespace/token state plus its own in-Sandbox Chromium profile/process and CUA session?
- [ ] Did all three active panes show genuine, monotonically sequenced CUA screenshot captures at >=1 fps, target 2 fps, with no replayed sequence or cross-candidate frame reuse?
- [ ] Did Jev actually answer and drive both UI variants, or is fallback labelled?
- [ ] Did CUA Driver execute the recorded hero journeys inside the actual Modal candidate Sandboxes with isolated profiles and snapshot-bound refs, or is the build explicitly reduced?
- [ ] Did Gemini actually produce the displayed typed diagnosis/diff?
- [ ] Did strict Pydantic validation reject malformed/unauthorised data before action?
- [ ] Is the required scenario/invariant evidence set exact and complete for every PASS?
- [ ] Did both oracle negative controls fail for the right reasons?
- [ ] Is every enabled live route (B, and `LEGACY` when enabled) hash-exact with matching evidence and router generations?
- [ ] Did staged routing counts and invariant checks match actual traffic?
- [ ] Does lease readback match and does Safe Stop/expiry lead only to hold?
- [ ] Does the receipt preserve prior harm and state honest limitations?
- [ ] Did two post-freeze reset-to-receipt runs pass?
- [ ] Does a clean clone follow README successfully?
- [ ] Are source, docs, two-minute video and secret scan ready before 19:00?

Any unchecked safety/evidence item forces the relevant claim into reduced mode. A correct refusal is a stronger demo than a fabricated autonomous success.

---

## 30. Sources consulted and implementation-time source of truth

Project sources:

- `PLAN.md`, `flow.md`, and `NightWatch - Complete Hackathon Implementation Spec.pdf` in this repository;
- the supplied Google Drive copy of the project specification;
- the supplied event screenshots and Luma event page.

Official live technical sources checked on 19 September 2026:

- Modal [Sandboxes](https://modal.com/docs/guide/sandboxes), [Sandbox networking and Connect Tokens](https://modal.com/docs/guide/sandbox-networking), [Function map API](https://modal.com/docs/sdk/py/latest/Function), [Volumes and consistency](https://modal.com/docs/guide/volumes), and [scaling](https://modal.com/docs/guide/scale);
- TypeSafe [documentation index](https://docs.typesafe.ai/llms.txt), [quick start](https://docs.typesafe.ai/introduction/quickstart), [Python SDK](https://docs.typesafe.ai/sdk/python), [Choice](https://docs.typesafe.ai/primitives/choice), [confidence](https://docs.typesafe.ai/confidence), [speculative fan-out](https://docs.typesafe.ai/patterns/fan-out), and [function-calling cookbook](https://docs.typesafe.ai/cookbooks/function_calling);
- CUA [repository](https://github.com/trycua/cua), official [Jev + CUA Driver recipe](https://cua.ai/docs/how-to-guides/driver/jev-use), [web-page driver guide](https://cua.ai/docs/how-to-guides/driver/drive-a-web-page), [semantic snapshots](https://cua.ai/docs/reference/cua-driver/browser-semantic-snapshots), [platform support](https://cua.ai/docs/reference/cua-driver/platform-support), and [Sandbox runtime constraints](https://cua.ai/docs/reference/sandbox-sdk/runtime-support);
- Pydantic AI [TypeSafe/Jev integration](https://pydantic.dev/docs/ai/models/typesafe/), [Google/Gemini integration](https://pydantic.dev/docs/ai/models/google/), and [Logfire integration](https://pydantic.dev/docs/ai/integrations/logfire/);
- Pydantic [strict mode](https://pydantic.dev/docs/validation/latest/concepts/strict_mode/);
- Google AI [Gemini models](https://ai.google.dev/gemini-api/docs/models) and [structured outputs](https://ai.google.dev/gemini-api/docs/structured-output).

APIs can move. The T+0 preflight and pinned lockfile are the event-day source of truth. If current SDK types contradict this plan, update the adapter and record the tested version; do not invent fields.

---

## 31. Stress-review findings and applied resolutions

Two adversarial review passes were run against this document before the build window: a **technical/feasibility pass** (external API reality checks against first-party docs, internal contradictions, race and trust-boundary analysis) and a **judge/delivery pass** (rubric fit, demo credibility, two-branch interlock and mergeability). Every confirmed finding was applied to the section that owns it rather than left as commentary. The log is kept so the builders do not re-litigate settled questions at 14:00.

### 31.1 Technical and feasibility findings

| # | Severity | Finding | Resolution |
| --- | --- | --- | --- |
| T1 | BLOCKER | CUA Driver on a headless Xvfb desktop inside Modal/gVisor is unproven, and the original 40-minute proof window was not credible; CUA's own documentation describes a logged-in graphical desktop. | §11.8 and §18: the desktop image is built first (it is the long pole), the gate moved to **T+0:50**, the core/API-only demo is the **default deliverable** until it is green, and reduced mode is declared at T+1:30 if it is not. |
| T2 | BLOCKER | On Linux X11, trusted CDP pointer input is refused; a click must use `input_route: dom_event`, and dispatch does not prove activation. | §11.4: `dom_event` is mandated for every click, the "hit target" assumption is removed, and activation is always confirmed from a fresh snapshot plus trusted state. |
| T3 | BLOCKER | The capability manifest listed pseudo-tools (`click`, `type`, `semantic_v2`, `screenshot`); the real typed tools are `browser_click`, `browser_type`, `browser_navigate` and `get_browser_state`, and an origin-scoped manifest fails closed if generic input tools are listed. | §11.6: exact typed tool names, `semantic_v2` named as a `snapshot_format` value, `include_screenshot` named as the image source, and the fail-closed startup behaviour stated. |
| T4 | MAJOR | Staged-smoke percentages (5/25/100) were not representable: `router_state.mode` could only express 0% or 100%. | §5.3, §9.2 and §14.2: added `rollout_pct` + `bucket_seed` to `router_state`, permitted through `PUT /internal/router` while `SAFE_HOLD`, with counts computed from actual buckets. |
| T5 | MAJOR | Per-scenario isolation contradicted a single shared app DB, and the S01/S05/S08 stock outcomes cannot coexist in one database. | §12.2 and §13: every scenario resets the seed, takes its own namespace and token, and runs **serially within a world**; concurrency is across A/B/C only. |
| T6 | MAJOR | A Choice accepts at most 255 options, so an uncapped candidate map can fail at runtime. | §11.3: cap the offered set at 253 including reserved options, and fail closed with a logged omitted count above it. |
| T7 | MAJOR | A `max_containers=1` control process cannot serve SSE plus per-500 ms frame polls plus CAS without declaring input concurrency. | §4.2: the ASGI functions must declare `@modal.concurrent(max_inputs=…)` sized for the SSE stream, the three frame polls and the writes. |
| T8 | MAJOR | The `<180 s` incident-to-lease target is not achievable once three desktop Sandboxes cold-start. | §3.3: the 180-second figure now applies only to `DETECTED -> SAFE_HOLD`; the full run is reported as a measured duration with no promised number. |
| T9 | MAJOR | The full-demo contract plus two clean rehearsals is over-scoped for two people and six hours. | §3.2, §11.8, §18 and §22: the **core demo is the committed deliverable**; the three-browser wall and full S01–S08 are the target, declared from evidence at G3/G4. |
| T10 | MINOR | Enabling Modal's domain-only egress allowlist would silently block the in-world browser's loopback origin. | §12.2: also allow `127.0.0.1/32`, or do not claim egress isolation. |
| T11 | MINOR | `BrowserFrame` conflated capture and snapshot IDs, and a sampler minting fresh semantic snapshots can invalidate the refs Jev judged. | §7.1 and §11.7: frames are identified by image SHA-256 plus the snapshot ID returned by the same call, and the sampler uses `get_browser_state(include_screenshot=true)` without minting a new semantic snapshot. |
| T12 | MINOR | `browser_prepare` requires a platform-attested or root-owned Chromium, and `Sandbox.exec` has no per-user parameter. | §11.6 and §12.2: Chromium is installed as a root-owned package, and the bootstrap performs an explicit `setpriv`/`su` privilege drop with recorded effective UIDs. |

### 31.2 Judge, demo and delivery findings

| # | Severity | Finding | Resolution |
| --- | --- | --- | --- |
| D1 | BLOCKER | Every gate assumed both tracks' artifacts, but no shared branch existed until T+5:20 — a blind-parallel window followed by a last-hour merge. | §18 and §19: `integration/nightwatch-demo` is created at the freeze and both tracks merge at every gate boundary, so T+5:20 is the **last** merge, not the first. |
| D2 | BLOCKER | `modal_app.py` spanned both tracks, so Track A could not deploy its own services without editing a B-owned file. | §16 and §17: split into `modal/services_a.py` and `modal/services_b.py` with a thin frozen-name shim `modal_app.py`. |
| D3 | BLOCKER | Track B's first tasks depended on browser contracts and frame-ingest endpoints that Track A was not scheduled to build in that window. | §18 and §16.1: Track A ships `apps/contracts/browser.py`, the `POST /internal/frames` contract with a frozen example, and the barrier endpoints **first**, inside the opening 45 minutes. |
| D4 | BLOCKER | The built dashboard wrote into Track A's tree while Track B owned the build. | §16 and §17: the dashboard builds to its own `dist/`, and `apps/control_plane/static/` is generated at deploy, gitignored and mounted read-only. |
| D5 | MAJOR | The frame store and browser barrier were A-owned although they are entirely Track B's domain, serialising B behind A. | §16 and §17: `services/frames/**` belongs to Track B; Track A keeps the HTTP contract and routes. |
| D6 | MAJOR | Two laptops deploying to the same Modal app would silently overwrite each other's functions and secrets. | §16.1 and §17: per-track `MODAL_ENVIRONMENT` values and a single designated deployer. |
| D7 | MAJOR | The agent prompts had no branch base, SHA, worktree command or change-request mechanism — exactly how two AI agents diverge into duplicate schemas. | §27 and §28: worktree commands with `<CONTRACT_FREEZE_SHA>`, explicit do-not-edit lists and a mechanical `CONTRACT_CHANGE.md` rule. |
| D8 | MAJOR | `scripts/**` and `tests/conftest.py` were unassigned and would be duplicated on both branches. | §17: every script and `conftest.py` now has one named owner. |
| D9 | MAJOR | `apps/live_store/**` is baked into Track B's image digest, so a late Track A change silently invalidates recorded evidence. | §6: the bundle hash is frozen at T+2:20; any later change voids prior evidence and forces a full re-run. |
| D10 | MAJOR | The frame-stall rule could fail a payment-correct candidate for a display-timing reason. | §3.1, §11.7, §13.2 and §15.1: the thresholds moved to 5/10 s, the stall clock freezes during an in-flight action, and a frame-stream failure degrades only the display/browser-evidence claim. |
| D11 | MAJOR | With A and C ineligible by construction, "the evidence chose the repair" reads to a judge as "you always flip the preinstalled switch". | §14.1: counterfactual labelling is mandatory, the claim is restated as verification rather than suspense, and `LEGACY` is now a committed genuinely live-eligible second route with a hard drop rule at Gate G3. |
| D12 | MAJOR | There was no live-demo runbook for the 20:00 slot and no reduced-mode video cut. | Superseded by team decision: presentation and video are handled outside this plan (§22); the engineering guarantees they rely on live in §3.1/§3.2, §14.4 and §15. |
| D13 | MINOR | `StrictModel` set `frozen=True` and `validate_assignment=True` together, which is inert and misleading. | §7: `validate_assignment` removed with the reason stated, and a separate mutable base prescribed where assignment validation is genuinely needed. |
| D14 | MINOR | Frozen "generated JSON Schemas" never said how the dashboard obtains TypeScript types. | §16.1: one codegen path (`npm run gen:types`) from committed schemas, so no hand-written client schema exists on either branch. |
| D15 | MINOR | §1 claimed no scoring rubric had been supplied, while the team did have one. | §1: the 50/20/30 rubric and the two side prizes are now stated and used to prioritise. |

### 31.3 Open risks accepted with eyes open

- **Modal egress isolation may not be configurable** for candidate sandboxes; the narrow, expiring provider token remains the real boundary, and the receipt must say so.
- **CUA-on-gVisor may still fail at T+0:50.** Reduced mode is pre-planned and honest; that is a scope outcome, not a plan failure.
- **Every pinned version** (Modal SDK, CUA Driver, Chromium, `jev-1.13.0`, the Gemini model) is verified at the T+0 preflight against live SDK types. If they disagree with this document, the adapter is updated and the tested version recorded — never the reverse.
- **Two people, six hours.** The committed scope is §3.2; everything in §3.1 is earned, not assumed.

### 31.4 Decisions taken in the interactive review (19 September)

Recorded so they are never re-litigated mid-build:

| # | Decision | Choice | Effect |
| --- | --- | --- | --- |
| 1 | Incident scope | **Both, payment first** | Payment is the demo. SQL injection is a gated post-freeze playbook with its own oracle, never on the critical path. |
| 2 | AI authority | **Code decides, AI proposes** | Gemini and Jev produce typed proposals only; invariants, selection and the lease stay deterministic. |
| 3 | Live repair | **Preinstalled handler + rollback route** | `POLICY_LIVE_A=1`: `LEGACY` is built, hash-verified and live-eligible alongside B, with a hard drop rule at Gate G3. |
| 4 | Evidence source | **Trusted outside oracle** | Ledger, oracle and fixtures live outside candidate worlds; candidates hold only scoped, expiring tokens. |
| 5 | Track ownership | **Akshay = Track B; Jazil = Track A** | Keys follow ownership: Jev stays with Akshay, the Gemini key is shared to Jazil. |
| 6 | Accounts and deploy | **Jazil's workspace; Jazil deploys** | Three environments (`nightwatch-a`, `nightwatch-b`, `nightwatch-demo`); Akshay never runs `modal deploy`. |
| 7 | Repo handling | **Public repo as the sync remote** | `origin` is shared and pushed at every gate boundary; keys travel out-of-band and are never committed — see §19. |
| 8 | Start time | **T+0 decided by the team** | The plan is written in relative time; only the 19:00 submission and 20:00 demo are fixed. A late start cuts scope from the back, never compresses gates. |
| 9 | Runtime | **Sub-5-minute target via bounded concurrency** | Per-scenario DB files replace serialisation; API cases and smoke probes run in bounded batches; UI stays serial per world (§14.4). |
| 10 | Presentation | **Out of scope** | The video and the live demo are handled by the team separately; nothing in the build is shaped around recording (§22). |
| 11 | Triage | **Gemini classifies; Jev does not** | Gemini emits an advisory typed triage block (category, severity, rationale, confidence) that never gates anything (§10.4). Recorded because live testing proved Jev cannot emit free text at all (§11.3). |
| 12 | Branch policy | **Main-based sync, not track branches** | Both builders push to `main`, running `git pull --rebase` immediately before every push and keeping commits inside their own §17 paths. This relaxes §19's track-branch scheme for speed and is recorded as a deliberate deviation. |
| 13 | Browser stack | **REDUCED MODE — driver-blocked, not disproven** | CUA Driver 0.28.2 refuses navigation and observation from a fresh `about:blank` origin under an origin-scoped manifest, and the existing-profile attach fails its endpoint proof. Browser scenarios are `ERROR_BROWSER_STACK`; nothing in the demo, dashboard or receipt may reference a browser journey (§11.8). |

---

## 32. Track A kickoff notes (verified 19 September, before the freeze)

Track A has not started. Everything below was verified live today against the real APIs and workspaces, so Track A can begin without re-deriving any of it.

### 32.1 Already done for you

- **Modal is configured and working.** Workspace profile `jxzxl07`; environments `main`, `nightwatch-a`, `nightwatch-b`, `nightwatch-demo`; secrets placed exactly as §16.1 requires — `nightwatch-a`: `nightwatch-gemini` + `nightwatch-control` · `nightwatch-b`: `nightwatch-typesafe` + `nightwatch-evidence-ingest` · `nightwatch-demo`: all six.
- Akshay's laptop authenticates against that workspace, and Jazil remains the only person who runs `modal deploy`.
- The repo scaffold is pushed: uv project, Python 3.12 pinned, `uv.lock`, `.env.example`, `.gitignore`, and the §16 directory tree.

### 32.2 Verified preflight facts — use these, do not re-derive them

- **Gemini**: `gemini-3.8-flash` answered a live strict-typed call through `pydantic-ai-slim[google]`; the key works, and **free-form string fields are supported** (this is why triage lives here).
- **TypeSafe**: `jev-1.13.0` answered a live call. See §11.3 for the hard output constraints, the `Choice`/`ChoiceAnswer` shapes, the missing `api_key` parameter and the first pilot confidence reading.
- **Not yet run**: the Modal Sandbox + Connect Token smoke — Track B is running it now.

### 32.3 What Track A ships first (Track B's critical path is blocked on it)

In this order, because Track B's browser path waits on all three:

1. `apps/contracts/browser.py` — the strict observation, decision and frame models;
2. `POST /internal/frames` — the multipart contract **plus a frozen example and a contract test** (Track B renders the three-pane wall against it);
3. the browser-barrier endpoints — readiness generation and synchronized release.

`apps/contracts/` is still empty in the repo. Nothing else on Track A blocks Track B.

### 32.4 Triage — decided, and it is Track A's work

Gemini owns incident triage; Jev does not (§10.4). Track A implements it in the Gemini agent and the incident contracts. Track B must not implement it.

### 32.5 Sync rules

- The **public GitHub repo is the sync remote**. Both builders push to `main`, run `git pull --rebase` immediately before every push, and keep every commit inside their own §17 paths.
- Never commit `.env`, a key or a token; the secret scan runs before every push. The repo is public.
- Track B has already pushed the storefront (`apps/storefront/**`, commit `a475f15`). Its `assets/api.js` holds **assumed** request/response field names behind a freeze note: the freeze reconciles that file against `apps/contracts/**` and `apps/live_store/**` before any end-to-end run.
