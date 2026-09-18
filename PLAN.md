# NightWatch — Agentic incident first responder

## One-line idea

NightWatch is an AI incident first responder that uses **Jev to investigate and experiment with a broken service in a browser**, **Gemini to diagnose the cause and write a temporary repair**, and independent checks to decide whether that repair can be deployed until an engineer takes over.

> **Pitch:** When a bad merge, configuration change, dependency failure, or other supported incident brings a customer journey down, NightWatch does not wait for an engineer to wake up. Jev reproduces the failure and tests possible recovery paths in isolated environments. Gemini learns from those experiments and writes the smallest viable repair. NightWatch verifies the result, applies a reversible temporary mitigation when policy allows it, and hands the engineer a complete evidence trail.

## Product vision and boundaries

The long-term product is an AI SRE teammate for incidents that harm real users. Its job is to reduce time to containment and give engineers a head start on the permanent fix. It can investigate service outages, bad deployments, configuration mistakes, broken dependencies, and suspected attacks through incident-specific playbooks. The common loop is **observe → reproduce → hypothesise → experiment → repair → verify → contain → monitor → hand off**.

NightWatch is not a promise that one agent can safely fix every outage or cyberattack in seconds. A supported incident must have a measurable failure, a reproducible or testable environment, and an allowed response. If evidence is insufficient, the candidates fail checks, or the action is outside policy, NightWatch escalates with its investigation rather than improvising in production.

There are two forms of intervention:

1. **Prepared mitigation:** a known reversible action such as reverting a deployment, disabling a feature flag, routing around a failing dependency, or applying a narrowly scoped rate limit. This can be fast enough for automatic containment when its playbook and checks are pre-approved.
2. **Generated temporary patch:** Gemini writes a small code change after Jev and other tests narrow the cause. A patch needs stronger tests and stricter authorization than a prepared switch. In the hackathon demo, it may deploy automatically to our own simulated production service. A real deployment policy would depend on the customer and incident risk.

The engineer receives the original symptoms, evidence, experiments, code diff, deployed mitigation, monitoring state, expiry or rollback conditions, and remaining work. Temporary containment does not imply that prior customer harm has been reversed.

## Why Jev and Gemini belong together

**Jev is the active browser investigator, not merely a final smoke test.** It operates the affected app and web-based operational controls, records precisely where a workflow fails, explores candidate configurations and versions in isolated environments, and tries nearby workflows to challenge a proposed repair. Its findings change what Gemini investigates and codes next.

**Gemini is the diagnosis and coding agent.** It reads the incident record, Jev observations, logs, deployment history, relevant code and tests. It generates evidence-backed hypotheses, requests bounded experiments, and writes the temporary patch. If Jev shows that a proposed fix is incomplete, Gemini revises its diagnosis and patch.

Neither agent independently declares an incident fixed. Jev's browser `DONE` state is an observation, not proof. Deterministic application checks, relevant state assertions, and policy rules authorize action. Jev's public implementation is a browser agent operating on observed web controls; Modal supplies the isolated environments where deployments and patches are tested.

## Reference incident: bad PR merge breaks checkout

This is the **one complete incident** to build for the hackathon. It demonstrates the general product without spreading the build across unrelated failure types.

### Incident setup

- A small storefront has a working checkout journey, deployment history, a feature flag, application logs and a mock payment/order state.
- The healthy version is deployed first. Jev completes checkout and records the baseline.
- A deliberately faulty PR is merged and deployed. The storefront still loads, but payment submission fails under a specific condition such as a retry or coupon. The incident begins at a known timestamp.
- Monitoring triggers on the failure. Jev reproduces it from the user's side and identifies the failing step.

The bug should be **real code**, not a dashboard animation. The candidate interventions must change actual behaviour. The underlying cause should be explainable from a small diff and visible in a log or trace.

### Investigation and repair loop

1. **Detect and confirm.** A failed journey or alert creates an `Incident`. Jev repeats the affected checkout path. The system records the failed control, visible error, screenshot/trace if available, backend error and deployed version.
2. **Gather context.** NightWatch supplies Gemini with the incident timeline, recent PR/deploy diff, logs and relevant code. Conduct context is added if event access exposes a useful integration.
3. **Form hypotheses.** Gemini returns structured hypotheses with evidence and requested experiments. For example: revert the deploy, disable the new checkout path, or alter the retry handler. Hypotheses are not treated as facts.
4. **Create counterfactual worlds.** Modal starts isolated environments from the same known fixture. Each world has exactly one candidate change so results are comparable. External payments are mocked; no real customer data or charges are used.
5. **Let Jev experiment.** Jev runs the same checkout and a nearby edge case against each world. It reports the observed steps, failures and recoveries to Gemini. A candidate that makes the page load but still blocks payment must visibly fail.
6. **Generate a patch.** Using those observations, Gemini writes a minimal patch to the implicated code. The first patch may deliberately fail an edge case; the loop then shows Gemini revising it in response to Jev's evidence.
7. **Verify independently.** Build and unit/integration checks run in the isolated world. Jev completes key browser journeys. Deterministic checks confirm the expected order and payment state. A candidate must reproduce the old failure on the broken baseline and remove it after the change.
8. **Contain.** The policy engine chooses the lowest-risk passing intervention. In the demo it applies a temporary repair to the demo's simulated production environment, attaches a time limit and continuously reruns health and Jev checks. Failure triggers rollback/escalation.
9. **Hand off.** NightWatch produces an engineer-facing incident receipt and a patch diff for review. It says what is still unknown and what needs a permanent fix.

The decisive demo moment is **Jev disproving a plausible Gemini hypothesis or patch**. That proves this is a genuine two-agent investigation loop rather than a pre-scripted success path.

## Architecture

```text
Alert / failed customer journey
             |
             v
       Incident collector <---- logs, recent deploys, code diff
             |
             v
       Pydantic control plane ---- Logfire trace
             |
             +----> Jev browser investigator <----> live/staging web app
             |                   |
             |                   v
             +<---- structured observations
             |
             +----> Gemini diagnosis + patch agent
             |                   |
             +<---- hypotheses / experiment requests / patch
             |
             +----> Modal candidate environments
             |                   |
             +<---- test results + Jev journey evidence
             |
             v
   Deterministic verifier + action policy
             |
             +----> temporary demo deployment + monitoring
             |
             +----> engineer incident receipt / escalation
```

### Technology responsibilities

| Technology | Required job | Demo evidence |
| --- | --- | --- |
| **Jev Ultrafast** | Reproduce the outage, operate browser-based experiments, and challenge candidate repairs through realistic journeys. | Visible browser run and structured step-by-step observations that influence Gemini's next action. |
| **Gemini** | Diagnose from the diff/logs/Jev evidence, request experiments, and write or revise a bounded code patch. | Hypothesis changes after a failed Jev experiment; actual code diff. |
| **Pydantic / Pydantic AI** | Validate every agent boundary and allow only known experiment and mitigation types. | Rejected malformed/unauthorized proposal; typed incident and result objects. |
| **Pydantic Logfire** | Trace the incident, agent calls, browser runs, sandbox tests, decision and timing. | A single drill-down incident timeline. |
| **Modal Sandboxes** | Run candidate app versions and patches in isolated, comparable environments. | Candidate A and B are tested against the same fixture without affecting the demo service. |
| **Conduct** | If accessible, relate implicated code/configuration to the affected business workflow and dependencies. | A real Conduct-derived context item, not a decorative logo. Keep optional until API/access is verified. |
| **Our verifier and policy code** | Check build/tests, journey outcomes, application state, allowed actions, scope, expiry and rollback. | A candidate fails for a concrete reason; only a passing action is applied. |

**Jev integration check before building around it:** run its smallest example with the team's key. The public repository's example configuration calls for a TypeSafe key and a separate text-model key. Confirm what the issued key covers. Keep the demo application on standard HTML controls supported by Jev, and verify its outcome independently.

### Suggested typed objects

- `Incident`: incident ID, start time, service, affected journey, symptoms, deployed version, evidence links.
- `JevObservation`: environment ID, journey, completed steps, failed step, visible state, trace reference, elapsed time.
- `Hypothesis`: suspected cause, supporting and contradicting evidence, confidence, requested experiment.
- `Experiment`: base version, one candidate change, sanitized fixture, allowed browser goal, timeout.
- `PatchCandidate`: diff reference, changed files, rationale, rollback action, expected effect.
- `VerificationResult`: build/tests, Jev result, backend/state assertions, risks and evidence.
- `RepairDecision`: selected action, policy basis, scope, lease expiry, revoke conditions or escalation reason.

The orchestrator should be a small state machine, not an unconstrained conversation. A model response cannot become a shell command or production deployment merely because it is plausible.

## Live demo script

The operator should need only a small number of reliable clicks. Keep a reset command and a recorded backup run in case a live external service is slow.

1. **Opening, 20 seconds:** “Our store is healthy. Jev can complete checkout.” Show a successful baseline run.
2. **Trigger, 20 seconds:** Deploy the bad merge. A customer-visible checkout attempt fails while the service remains partly reachable.
3. **Detection, 30 seconds:** NightWatch opens an incident; Jev repeats the journey and pinpoints the failure. Show Jev's trace alongside the backend error.
4. **Joint investigation, 45 seconds:** Gemini reads the evidence and requests two or three experiments. Show the structured hypotheses, not a wall of model text.
5. **Counterfactuals, 60 seconds:** Modal tests alternatives; Jev drives checkout in each world. One apparently sensible action fails a second journey. The result is sent back to Gemini.
6. **Patch iteration, 60 seconds:** Gemini produces a minimal patch. Show its diff. Jev tests it; if the planned first patch fails, Gemini revises and reruns it. Keep this segment short and observable.
7. **Containment, 30 seconds:** Apply the passing, temporary change to the demo service. Jev verifies that checkout works. Show lease expiry and rollback trigger.
8. **Handoff, 30 seconds:** Open the incident receipt: cause hypothesis, evidence, experiments, rejected candidate, applied change, what customers experienced, and what the engineer should inspect next.

Target a **3–5 minute presentation** and a shorter fallback if the event imposes a tighter limit. The event page currently lists evening live demos but does not publish a judging rubric or demo-duration requirement; confirm both with organisers.

### Screen layout

- **Left:** Jev browser view with the current journey and failing step.
- **Centre:** incident timeline and Gemini's current hypothesis/experiment request.
- **Right:** Modal candidates, test results, selected temporary repair and lease countdown.

The audience should always know: *What broke? What is Jev trying? What did Gemini learn? Why is the selected action safer?*

## Build priorities for a one-day hack

### Before the event, if rules permit preparation

- Confirm event rules on pre-existing code and disclose any prepared components required by those rules.
- Verify Jev credentials and a simple browser run. Do not commit API keys or traces containing credentials.
- Confirm Gemini, Modal, Pydantic/Logfire and Conduct access separately.
- Agree on the incident, app interfaces, data contracts and division of work.

### During the event

| Priority | Deliverable | Stop/go test |
| --- | --- | --- |
| **P0** | Storefront with healthy and broken versions; Jev can reproduce the break. | A judge can see the real failure in the browser. |
| **P1** | Gemini receives real evidence and requests one experiment; one Modal world tests it. | Jev's observation changes Gemini's next step. |
| **P2** | Gemini generates a patch; tests and Jev verify it; temporary demo deployment recovers checkout. | End-to-end loop works without manually editing the result. |
| **P3** | Two candidate worlds, rejected fix, Logfire timeline and polished handoff receipt. | The safety and reasoning are obvious in a short live demo. |
| **P4** | Conduct integration and optional second incident playbook. | Add only if it is real and does not jeopardise P0–P3. |

For a team of four: one person owns **storefront/fault injection**, one **Jev**, one **Gemini/Pydantic orchestration**, and one **Modal/verifier/dashboard**. Everyone should help test the integrated demo. Establish the shared typed objects and service endpoints before parallel work begins.

### Non-negotiable fallbacks

- If Jev is unreliable on a complex page, simplify the demo UI to standard controls; do not replace its role with a fake animation.
- If Modal startup is slow, pre-warm candidate environments and show accurate measured timings.
- If generated patches are unreliable, show a prepared mitigation followed by a Gemini-generated patch tested in isolation. State clearly which action was actually deployed.
- If Conduct access is unavailable, use a small local code-to-workflow map and say Conduct integration is a next step; do not claim it ran.
- If a production-like actuation step is risky or flaky, apply changes only to the team's demo deployment and be explicit about that boundary.

## Safety and credibility rules

- Use synthetic users, mock payments and isolated test data. Never handle real customer funds, production secrets or third-party infrastructure in the demo.
- Jev may explore only allowlisted app/admin URLs. A browser action cannot itself authorize a deployment.
- Gemini may produce hypotheses, experiment requests and patches. It gets no ambient credentials or unrestricted production shell access.
- Require a reproducible baseline failure and a measurable pass condition. A candidate that merely hides the error message does not pass.
- Prefer a known rollback or flag over a generated patch when both restore the service. Code changes carry greater risk.
- Every temporary action has a scope, expiry, monitoring checks and rollback mechanism.
- If security compromise is suspected, preserve evidence and follow a separate security playbook. A generic code patch is not an adequate response to an unknown attacker.
- Report actual measured detection, experiment and recovery times. “Within seconds” is a goal for supported, prepared actions, not a universal guarantee.
- Distinguish **service restored**, **root cause fixed**, and **previous customer harm remediated** in every receipt.

## Engineer-facing incident receipt

```text
NIGHTWATCH INCIDENT #001
Service: checkout
First impact: 03:07:14
Detected by: alert + Jev checkout failure
Customer symptom: Pay action fails after coupon and retry
Recent change: deployment <commit/reference>

Investigation:
  Jev reproduced the failure on the broken version.
  Gemini suspected the new retry handler based on trace + diff.
  Modal candidate A restored page load but Jev still could not pay.
  Modal candidate B passed checkout, retry, and backend assertions.

Temporary action: <version switch / scoped patch>
Lease: expires <time>; revoke on <condition>
Recovery proof: Jev journey passed + backend state checks passed
Open questions: <unknowns>
Engineer next steps: inspect diff, review affected transactions,
                     develop and deploy permanent fix.
```

## Judge pitch and answers

### Thirty-second pitch

“Software incidents happen faster than engineers can investigate them. NightWatch is an AI first responder. Jev goes into the broken service, reproduces the customer failure and tests recovery options in isolated worlds. Gemini uses those results and the recent code changes to diagnose and write a temporary repair. The system only deploys a candidate that passes independent checks, then monitors it and hands engineers the full evidence trail. In our demo, a bad merge breaks checkout; NightWatch finds it, rejects an incomplete fix and restores the service before an engineer would even open the incident.”

### Likely judge challenges

**Is this just a rollback bot?** No. Rollback is one possible response. The distinctive part is the Jev–Gemini evidence loop: reproduce the customer failure, explore counterfactuals, learn from failed experiments, produce a targeted repair, and verify recovery.

**Why Jev rather than scripted end-to-end tests?** Jev can operate a changing web interface and explore the actual user journey, including the step and visible state at failure. Deterministic tests still verify backend truth. The two are complementary.

**Does Jev really “find the bug”?** It supplies behavioural evidence and tests hypotheses; Gemini correlates that with logs and code. Neither one alone proves root cause.

**Why allow an LLM to patch a service?** The patch is generated in an isolated environment. A separate verifier and policy engine decide whether it is deployable. Unknown or high-risk incidents escalate.

**Can it fix cyberattacks?** The product can support narrowly defined security containment playbooks, but this demo proves bad-deploy recovery. Unknown attacks require evidence preservation and security-team involvement.

**Can it really act in seconds?** Prepared mitigations may be fast; a generated patch and full verification take longer. Show measured end-to-end time and make no universal timing promise.

## Definition of a successful hackathon build

The project is ready to present only if all of these are true:

1. Jev visibly reproduces a real failure caused by the bad version.
2. Gemini receives Jev's actual observation and changes its hypothesis, experiment or patch based on it.
3. At least one candidate is tested in a real isolated environment, and a failed candidate is honestly shown as failed.
4. The final patch or mitigation changes real application behaviour and passes both a browser journey and independent state checks.
5. NightWatch applies the repair only to the demo environment under a clear temporary policy.
6. The engineer receipt accurately records what happened, what was done, what is uncertain and what remains to fix.

If the team achieves that loop cleanly, the pitch can claim a credible working first responder rather than an ambitious concept video.

## Source notes and assumptions

- Event schedule and listed partners: https://luma.com/ldn-hack
- Jev capabilities, setup and stated limits: https://github.com/browser-use/jev-ultrafast
- Gemini model availability: https://ai.google.dev/gemini-api/docs/models
- Modal sandbox capabilities: https://modal.com/docs/guide/sandboxes
- Pydantic Logfire: https://pydantic.dev/logfire
- Conduct's public description: https://conduct.ai/blog/series-a

Exact hackathon judging criteria, demo time, permitted pre-work, issued credits and Conduct API access need confirmation from the organisers. The architecture above is a plan, not a claim that those integrations have already been implemented.
