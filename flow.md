# Nightwatch — Project Flow & Roadmap

**{Tech: Europe} Agentic AI Hack x Google DeepMind — 19 Sep 2026**

## One-line pitch

Nightwatch sits in front of a live service. The instant something goes
wrong — an attack, a bad deploy, anything — it diagnoses the real cause
in the actual codebase, races multiple AI-generated fixes against each
other in parallel sandboxes (each one tested by a fast browser-driving
agent), ships the one that actually works, and hands engineers a full
incident report before they've even woken up.

## The core idea in one paragraph

Most "AI incident response" demos either (a) just detect and alert, or
(b) generate a single unverified fix and hope. Nightwatch does neither:
it generates **multiple genuinely different fixes**, **actually tests
each one** by driving a real browser through both the attack and a
normal user flow, and only ships the one that's *proven* to work without
breaking anything else. Detection is fast and cheap (Jev). Understanding,
generating, and judging are slow and careful (Gemini). Nothing gets
deployed on a guess.

---

## Architecture overview

```
[Live traffic] --> [Nightwatch Middleware, on Modal]
                         |
                         |-- Rule check (ownership/permission mismatch -> IDOR)
                         |
                         `-- JEV #1 (inline, <100ms)
                                 typed: {malicious, attack_type, confidence}
                         |
                    flagged? --no--> request proceeds normally
                         |
                        yes
                         v
              [Nightwatch Orchestrator]
                         |
              regression from a recent deploy?
                 |                        |
                yes                       no
                 |                        |
     [INSTANT ROLLBACK PATH]      [FULL DIAGNOSIS PATH]
     git revert -> redeploy              |
     -> health check -> report           v
                              [GEMINI - diagnosis]
                              explores codebase, reads logs/request,
                              finds root cause, explains it
                                          |
                                          v
                          [GEMINI - generates 3 patch candidates]
                          minimal-diff / defensive / structural
                          each = Pydantic PatchCandidate
                                          |
                                          v
                 [MODAL - 3 concurrent sandboxes, one per patch]
                 each sandbox: apply patch, boot patched app,
                 headless browser attached
                                          |
                          +---------------+---------------+
                          v                                v
              JEV #2 drives exploit-replay        JEV #2 drives legit
              (click/fill/assert loop)            user-flow check
                          |                                |
                          +---------------+----------------+
                                          v
                     Pydantic SandboxResult per candidate:
                     {exploit_blocked, flow_still_works, diff_size}
                                          v
                          [GEMINI - picks the winner]
                priority: exploit blocked > flow still works > smallest diff
                          (if none pass -> quarantine + escalate to human)
                                          v
                    [SAFETY GATE - deterministic rule check]
                touches auth/payments/data-deletion? -> hold for human
                                          v
                        [MODAL - deploy winning patch]
                                          v
              [VERIFY] replay original attack against live patched
                        service -> confirm blocked + confirm healthy
                                          v
                    [GEMINI - writes incident report]
                root cause, candidates tried, winner + why, diff,
                verification proof, full timeline with latencies
```

---

## Tech stack — what each piece does and why

### Gemini (reasoning core)
Used for everything that requires actually *understanding* something:
exploring the codebase with tools (search/grep/read file), diagnosing
root cause, generating multiple structurally different patch candidates,
making the final judgment call between candidates, writing the incident
report. Runs in function-calling mode so every output is a tool call or
a structured object, not free text.

### Jev (TypeSafe AI — "System One Model")
Not a text generator. Given a shared state + a typed question, it
returns a structured, calibrated decision (a choice, score, or
probability) in a single fast pass — no token-by-token generation, which
is what makes it viable to run inline on every request. Two distinct
jobs in Nightwatch, never overlapping with Gemini's job:

- **Jev #1 — front-door triage.** Sees one request/response in
  isolation. No code awareness, no memory beyond what's passed in.
  Decides: `{malicious: bool, attack_type: str, confidence: float}`.
  This is what makes real-time inline defense viable at all — a
  generative model is structurally too slow to sit in this path.
- **Jev #2 — sandbox browser driver.** Inside each sandbox, given the
  current page state (DOM/accessibility-tree snapshot, not a full
  screenshot), decides the next browser action:
  `{action_type: click|fill|assert|done, target_element, value,
  confidence}`. Looped step-by-step via Playwright until it returns
  `done` or hits a step budget. Run twice per sandbox: once replaying
  the original exploit (should now fail), once walking a legitimate
  user flow (should still succeed). This replaces what would otherwise
  need a slow agentic browser loop, at a speed that makes racing three
  of them concurrently and live on stage possible.

**Mental model for the pitch:** *"Jev notices. Gemini understands."*
Jev never looks at source code. Gemini never sits inline on live
traffic.

### Modal (compute & execution)
Hosts everything that needs to actually run:
- The live target/demo service (the intentionally-vulnerable app)
- The Nightwatch middleware sitting in front of it
- The three concurrent sandboxes (isolated environments running the
  patched app + a headless browser each)
- The final redeploy of the winning patch

This is genuinely load-bearing — the concurrent sandbox race is only
possible because Modal can spin up isolated environments fast and in
parallel.

### Pydantic AI (structured contracts)
Every handoff between agents is a validated schema, not free text:
- `TriageDecision` (Jev #1 output)
- `PatchCandidate(diff, strategy, rationale)` (Gemini output)
- `BrowserAction` (Jev #2 output, per step)
- `SandboxResult(exploit_blocked, flow_still_works, diff_size,
  new_errors)` (per candidate, after both browser runs)
- `SafetyCheck(safe_to_autodeploy, reason)` (deterministic gate output)
- `IncidentReport(root_cause, candidates_tried, winner, diff,
  verification, timeline)`

This is what makes every claim in the demo auditable on screen instead
of "trust us."

---

## Detection layer — how Nightwatch actually knows something's wrong

Two layers, because a pure uptime check misses attacks that don't crash
anything (e.g. IDOR — nothing breaks, someone just reads data they
shouldn't):

1. **Health-check polling** (every 1-2s) — catches hangs/crashes/timeouts
   (ReDoS) and post-deploy regressions.
2. **Inline request inspection** — every request through the middleware
   gets a rule check (ownership mismatch) + a Jev #1 classification.
   Catches attacks that never cause downtime at all.

---

## Demo scenarios (3, locked)

Keep to three. Depth on three beats shallow coverage of more.

### 1. SQL injection (attack)
Malicious payload in a request param. Jev #1 flags it inline on the way
in. Diagnosis finds the unsanitized query. Patches: parameterize the
query (minimal), add input validation layer (defensive), replace the
raw-SQL call with an ORM method (structural). Visually clean
before/after: malicious query blocked, legitimate queries unaffected.

### 2. IDOR / broken access control (attack)
Request for `/api/resource/:id` with no ownership check — changing the
ID returns another user's data. No crash, no downtime — this is the
scenario that proves Nightwatch catches what a pure uptime monitor
can't. Rule check + Jev #1 flag the ownership mismatch. Diagnosis finds
the missing authorization check. Patches: add ownership check
(minimal), add role-based access middleware (defensive), refactor
resource access through a scoped repository pattern (structural).

### 3. Bad merge / regression (non-attack — speed contrast)
A genuinely broken deploy (e.g. missing import, null pointer). Health
check fails right after a deploy event. Jev #1's triage (or a simple
correlation rule) classifies this as a regression, not an attack, and
routes straight to the **instant rollback path** — `git revert` ->
redeploy -> verify -> report, in seconds, no diagnosis/patch-race needed.
This is the deliberate speed contrast against scenarios 1 and 2: it
shows Nightwatch has judgment about which incidents need heavy
machinery and which don't.

*(Backup option if time allows a 4th: ReDoS — catastrophic regex
backtracking, causes a visible hang, caught by the health-check layer.
Only add this if scenarios 1-3 are fully solid and rehearsed with time
to spare.)*

---

## Safety gate (before any auto-deploy)

Deterministic rule check, not Jev, not Gemini: does the winning diff
touch auth, payments, or data-deletion code? If yes -> hold for human
approval instead of auto-deploying, and say so in the report. This is
the maturity signal in the pitch — a real deployment would let a team
tune the autonomy threshold; today's demo has it turned up for
demonstration purposes.

## No-winner fallback

If all three candidates fail verification: don't guess. Quarantine the
vulnerable endpoint, escalate to a human, and the report explains what
was tried and why nothing passed. This is a feature, not a failure
state — say so explicitly.

---

## Demo script (target: under 3 minutes for scenario 1, room for more)

1. Dashboard idle, service healthy, latency meters at zero.
2. Fire the SQLi attack live. Jev #1 flags it in milliseconds — show
   the number on screen.
3. Gemini's diagnosis streams live — narrate it finding the vulnerable
   query.
4. **Centerpiece**: three sandboxes light up simultaneously, each with
   a live browser viewport, Jev #2 clicking/filling/asserting through
   exploit-replay and legit-flow checks in real time. Narrate as it
   happens.
5. Results land per candidate, winner highlighted.
6. Safety gate shown explicitly approving the winner.
7. Deploy fires. Verifier replays the original attack — now blocked.
   Total time elapsed shown prominently.
8. Incident report renders — scroll to the timeline table.
9. Second beat: trigger the bad-merge scenario, show the rollback
   complete in ~2 seconds. This contrast lands the whole pitch — not
   every incident needs the same machinery.

**Answer ready for "how is this different from existing tools":**
autonomous multi-candidate patch generation, raced concurrently, each
one *actually verified via real browser interaction* — not a single
LLM guess applied blind, and not sampled/after-the-fact detection but
inline inspection of every request at a speed only a purpose-built fast
model makes possible.

---

## Build roadmap (~7 real hours, budget for friction)

| Time | Task |
|---|---|
| 0:00-0:45 | Repo scaffold. Confirm API access: Jev (waitlist status!), Gemini, Modal. Trivial "hello" call to each working. |
| 0:45-1:30 | Build the intentionally-vulnerable demo app (SQLi + IDOR endpoints). Deploy to Modal. |
| 1:30-2:15 | Middleware: rule check + Jev #1 inline classification. Confirm it correctly flags both attack types. |
| 2:15-3:00 | Test Jev #2's browser-driving loop **in isolation** first (highest-uncertainty piece) — can it reliably pick the right element to click from page state? Have a hardcoded-Playwright-script fallback ready if not. |
| 3:00-4:00 | Gemini diagnosis agent — codebase search/read tools, root-cause reasoning on scenario 1. |
| 4:00-4:45 | Gemini patch generation — 3 distinct strategies, Pydantic-validated. |
| 4:45-5:45 | Modal concurrent sandboxing — apply patch, boot app, attach browser, run Jev #2's two check loops, return `SandboxResult`. |
| 5:45-6:15 | Winner selection logic + safety gate + deploy + final verify. |
| 6:15-6:45 | Rollback path (scenario 3) — should be fast to build, mostly git + redeploy + a report call. |
| 6:45-7:30 | IDOR scenario (reuses the whole pipeline from scenario 1, new vulnerable endpoint + new patch prompts). |
| 7:30-8:15 | Frontend: live timeline, sandbox-race visualization, report render. |
| 8:15-8:45 | Full run-throughs, fix breakage. **Record a full successful run as backup.** |
| 8:45-9:00 | Lock scope, rehearse pitch. |

**Protect above everything else:** the rollback path and the sandbox
race visualization. If behind schedule, cut the IDOR scenario or the
safety-gate sophistication before touching either of those.

## Known risks

- **Jev access is gated behind a waitlist** — confirm this works before
  building anything around it. Have a Groq-hosted small model or
  Gemini Flash-Lite as a drop-in fallback for both Jev roles if access
  doesn't come through.
- **Jev #2's click-target selection is the single highest-uncertainty
  component** — test it alone, early.
- **Live agent demos fail more often than not** — record a full
  successful run tonight/this morning as a fallback to cut to if the
  live version glitches.
- Don't over-build the "realism" of the vulnerable demo app — keep it
  as small and clean as possible; all engineering time should go into
  the pipeline, not the target app's fidelity.
