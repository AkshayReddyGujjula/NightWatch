# NightWatch stage target

This folder is the deliberately vulnerable, isolated demo boundary. The trusted
NightWatch packages remain under `apps/` and `services/`.

- `1-DEMO.cmd` arms a fresh double-charge namespace, starts the ledger watcher,
  and opens the pre-filled checkout plus live repair dashboard in Chrome.
- `2-CYBERSECURITY.cmd` injects a **scripted, isolated** HTTP 503 failure into
  this demo target and starts the same Gemini and concurrent validation flow.
- `3-RESET.cmd` restores both vulnerabilities for a new run while preserving
  prior JSON receipts in `runtime/receipts/`.

The dashboard never loops stock footage. Candidate images appear only after a
real CUA screenshot is copied from that run's real Modal Sandbox. A missing or
failed source stays labelled.
