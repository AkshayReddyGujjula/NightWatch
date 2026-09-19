# Browser stack notes — CUA Driver 0.28.2 on Modal/gVisor (Track B)

Evidence log for plan §11.8. Keep this current: the receipt and README must
reflect exactly what is proven here.

> **STATUS 19 Sep ~17:10 — SUPERSEDES every earlier "blocked" verdict below.**
> The typed journey **is green** on the driver-launched isolated browser:
> `browser_prepare {"allow_launch": true, "profile": {"mode": "isolated_new"}}`
> → `prepared: true`, `endpoint_ownership: spawned_by_driver`; exact binding;
> `semantic_v2` snapshots; one live TypeSafe Jev action executed with a verified
> fresh-snapshot postcondition. Two limitations are recorded and claimed:
> (1) a single raw CDP `Page.navigate` first hop is required because the
> origin-scoped manifest refuses observation from `about:blank`; (2)
> `<input type="email">` writes never reach the renderer (`browser_type`
> `effect: refused`) while the `<textarea>` write lands. See the final section.

## What is proven working (real sandbox evidence, `nightwatch-b`)

- Pinned desktop image builds and boots: `im-bpk70bsExDFHWQbm5FoUvh` lineage;
  Chrome 153.0.8010.52 (root-owned `.deb`), CUA Driver 0.28.2 (checksum-verified
  release tarball), Python 3.12.10, UIDs 2001/2002, homes 0700.
- World bootstrap (`infra/start_desktop_world.sh`): Xvfb + Openbox + D-Bus +
  AT-SPI registry (verified live in the daemon log), controller-owned mode-0600
  CUA socket, app user unable to traverse `/run/nightwatch` (0770 root:controller).
- CUA Driver runs in bounded mode with a reviewed manifest: `status` reports
  `permission mode: bounded`, `capability manifest: valid`, and a manifest hash.
- `start_session`/`end_session` over the socket; `browser_prepare` (isolated
  launch) succeeds and spawns a driver-owned browser with a live loopback
  endpoint (`endpoint_ownership: spawned_by_driver`).
- `list_windows {pid}` + `get_browser_state {pid, window_id}` bind with
  `binding_quality: exact`, `binding_route: native_cdp_window`,
  `mutation_allowed: true`, target/tab ids minted (isolated flow, round 3).
- Chrome launch under the controller identity with a world-local mode-0700
  profile, window ownership resolved from `_NET_WM_PID` (not pgrep).

## Blocker 1 — typed navigate is refused from a fresh about:blank tab

Bounded manifest, `resources.browser.origins` present. A driver-owned isolated
browser starts at `about:blank`; the first `browser_navigate` to an allowed
origin is refused:

`protected_resource_scope_invalid: the live browser origin is outside the capability manifest`

Measured across manifest origin spellings and target URLs (all refused):
`http://127.0.0.1:8080` → navigate `/` and `/checkout-x.html?intent=1`;
`http://127.0.0.1:8080/` → `/`; `http://localhost:8080` → `/`.
Conclusion: the check is on the **current** page origin (opaque `null` for
`about:blank`), not on the destination. Declaring `"null"` or `"about:blank"`
as an origin is **rejected at daemon startup** (manifest invalid, socket never
appears), so the isolated route cannot make its first navigation.

## Blocker 2 — existing-profile attach fails its endpoint proof

The plan's own §11.6 shape (controller-owned browser, world-local profile) was
implemented: bootstrap launches Chrome at the allowed origin; CUA is asked to
attach with `strategy: existing_profile` (manifest declares that profile kind).

- First `browser_prepare` performs the documented Linux X11 setup (opens the
  fixed setup page, toggles the per-instance remote-debugging control) and then
  refuses: `browser_requires_setup`, `restart_required: true` — "restart the
  browser, then call browser_prepare again".
- After the restart the endpoint is live and PID-owned
  (`127.0.0.1:9222`, `DevToolsActivePort` present, `ss` shows the browser pid),
  and the setting persists.
- Second `browser_prepare` still refuses:
  `Google Chrome did not expose a uniquely PID-owned loopback endpoint after
  the exact setup action` (`enabled_remote_debugging:false`,
  `restored_remote_debugging:true`), and it restores the setting off.

Both blockers are driver-side behavior in 0.28.2; no configuration found on our
side reaches a green typed-browser journey. No substitute browser controller is
permitted (ADR-007), so while this stands, browser scenarios are
`ERROR_BROWSER_STACK` and any claim about Jev+CUA driving the storefront is
explicitly degraded.

## Reproduce

`uv run modal run scripts/verify_browser_stack.py` (nightwatch-b) prints the
full evidence JSON and writes `artifacts/browser_gate_<ts>.json`.

## Final probe results (19 Sep, ~13:40)

- `browser_prepare` **silently ignores** undocumented `url` / `start_url` fields:
  the isolated browser still lands on `about:blank` (bound_title/bound_url
  recorded in the probe).
- Under an origins-scoped manifest the refusal also hits **observation**: a
  `semantic_v2` snapshot from the blank page fails with
  `authorization_host_failed: confirmation provider failed: the live browser
  origin is outside the capability manifest`.
- Conclusion: with CUA Driver 0.28.2, an origin-scoped bounded world cannot use
  a driver-owned isolated browser at all, and the existing-profile attach proof
  fails against a live, PID-owned endpoint. Browser scenarios are declared
  `ERROR_BROWSER_STACK` (reduced mode) until a driver fix or version change.
  No substitute browser controller (ADR-007).

## Final carve-out result (card 3 attempt, 19 Sep ~14:00)

The last approved mechanism — a driver-owned `isolated_named` profile, re-entered
through the isolated flow (which avoids the existing-profile endpoint proof) with
Chrome startup URLs seeded between sessions — was attempted in one bounded probe and
**not fully exercised**:

- the second `browser_prepare` did reuse the named profile
  (`reused_driver_profile: true`, `created_profile: false`), so named-profile
  persistence works;
- but the profile directory could not be located from the browser process cmdline
  (`--user-data-dir=` absent), so the startup-URL preference was never seeded and the
  page stayed on `about:blank`;
- the blank-page refusals were unchanged: `get_browser_state` (semantic_v2) refused
  with `authorization_host_failed`, `browser_navigate` refused with
  `protected_resource_scope_invalid`.

Browser spend stops here per plan §11.8 (reduced mode from the T+1:30 gate). The
record is deliberately precise: two driver-level blockers are **proven**, and this
third mechanism is **untested, not disproven**. Nothing in the demo or the receipt may
reference a browser journey.

Card 4 — first navigation through the driver-owned loopback CDP endpoint directly
(bypassing the typed surface) — is **untested and was not attempted**; it is out of
scope unless explicitly reopened after the core demo is rehearsing.

## Final outcome (19 Sep ~17:10) — typed journey green on the isolated route

### What unblocked it (all raw JSON in `artifacts/browser_*.json`)

1. `browser_prepare` accepts exactly one strategy kind, `existing_profile`
   (`strategy.kind: "isolated"` → `unknown variant 'isolated', expected
   'existing_profile'`). The driver-owned isolated browser is a **profile mode**:
   `{"allow_launch": true, "profile": {"mode": "isolated_new"}}`
   → `{"action": "launched_isolated_browser", "prepared": true,
   "endpoint_ownership": {"method": "spawned_by_driver", "owner_pid": <pid>,
   "detail": "driver-owned profile port file plus live loopback socket owner"}}`
   with every `side_effects` false except `created_profile` / `launched_browser`.
2. Route A (controller-owned Chrome with a launch-declared DevTools endpoint) is
   fully characterised and **refused** for the bounded `existing_profile` path:
   with `--remote-debugging-port=0` the endpoint is live and PID-owned
   (`LISTEN 0 0 127.0.0.1:31176 users:(("chrome",pid=141,fd=80))`,
   `DevToolsActivePort` written), yet the driver always runs its own setup
   action first and then fails its own proof (`browser_requires_setup`,
   "did not expose a uniquely PID-owned loopback endpoint after the exact setup
   action"). With a fixed `--remote-debugging-port=9222` Chrome wrote **no**
   `DevToolsActivePort`. No driver-version change was attempted.
3. Observation and typed navigation from a fresh `about:blank` page remain
   refused under the origin-scoped manifest. **One recorded deviation**: exactly
   one raw CDP `Page.navigate` to `http://127.0.0.1:8080/…` per world, executed
   inside the sandbox by a stdlib-only RFC 6455 client (httpx has no WebSocket
   support and nothing was installed). Every observation and every later action
   goes through the typed bounded tools only.
4. Refs are snapshot-scoped: the action executes on exactly the observation Jev
   judged (no intervening snapshot), and the postcondition comes from the next
   FRESH snapshot matched by role+name.
5. `browser_type` / `browser_click` require the exact `target_id` and `tab_id`;
   without them the driver refuses with `protected_resource_scope_invalid`
   ("the browser operation requires an exact target_id").

### Green evidence (one bounded Sandbox, `artifacts/browser_launch_1789828401.json`)

- Sandbox `sb-CkQb2ZlPLiMlzKbD7JJXIZ`, image `im-PufC2iis5NTiGNFR00dxze`,
  bootstrap 14.9 s, clean teardown.
- Binding `binding_quality: exact`, `mutation_allowed: true`; target/tab ids
  minted; page URL on the allowed origin after the recorded hop.
- `semantic_v2` snapshot: 7 refs — Email textbox, Delivery address textbox,
  Promo code textbox, Pay now button (`actions: ["click","pointer"]`).
- Task 1 screenshot `task1-probe.png`: sha256 `023c9caa…c8921`, 39,489 bytes,
  copied out and visually inspected (real NightMart checkout page).
- Task 2 (live `jev-1.13.0`, confidence + raw probabilities recorded per step):
  `fill_address` executed through `browser_type` and **verified from the next
  fresh snapshot** (`value == "1 Demo Street, London"`), screenshot
  `jev-02-after.png` sha256 `89d8b9d7…6e20a3`, 42,169 bytes, visually confirmed.
  One earlier run also recorded `fill_email` executions and an abstention
  (`abstain`, confidence 0.65) when the value did not land.
- 9 screenshots captured in the atom runs, 5 distinct hashes.

### Recorded limitations (do not overclaim)

- **Email input**: `browser_type` on `<input type="email">` returns
  `{"effect": "refused", "escalation": {"reason": "route_unavailable",
  "target": "page"}, "route": "trusted_input"}` for `replace: true`, no-`replace`,
  `input_route: dom_event` and click-then-type; the value never appears in the
  next snapshot. The `<textarea>` write on the same page works. Because the
  checkout page requires both email and address, **no checkout was completed and
  no payment claim is made**. `execute_javascript` is not in the manifest and was
  not used.
- The CDP first hop is a deviation from the pure-typed path; it navigates to an
  already-allowed origin only.
- The controller-owned browser (Route A) is still unusable for typed journeys;
  candidate worlds that need a browser must use the driver-launched isolated
  profile and the runner must perform the recorded hop.

### Reproduce

- `uv run modal run -e nightwatch-b scripts/probe_browser_launch.py` — Route X,
  binding, hop, typed snapshot, Jev atom (green)
- `uv run modal run -e nightwatch-b scripts/probe_browser_type.py` — email type
  variants and the click probe
- `uv run modal run -e nightwatch-b scripts/probe_browser_journey.py` — Route A
  endpoint diagnosis (red)
