# NightWatch dashboard (Track B)

Read-only projection of committed control-plane evidence. It is not an
orchestrator: a disconnected dashboard can never create a lease or cancel
verification.

## Commands

```bash
npm ci                 # once
npm run gen:types      # frozen codegen: apps/contracts/schemas/** -> src/generated/
npm run dev            # local dev server
npm run lint           # eslint
npm run build          # tsc --noEmit && vite build -> dist/
```

`src/generated/` is produced by `scripts/gen-types.mjs` only — there is no
hand-written client schema anywhere (plan §16.1). The built `dist/` is served by
`control_asgi`; live endpoints must send `Cache-Control: no-store`.

## Data plumbing (`src/api/`)

- `routes.ts` — every control-API path in one place (plan §9.1); response types
  are the generated modules, never hand-written shapes.
- `client.ts` — typed `ControlApi` (operator-token auth, no-store reads). When
  Track A's routes land this is the only file that changes: `getReceipt` is
  already typed against the frozen `RepairReceipt` schema, and
  `getEvaluationResults` returns an explicitly-unavailable read model until the
  contract owner freezes the committed-results source.
- `sse.ts` + `sseParser.ts` — fetch-based SSE subscriber (the operator token
  rules out `EventSource`): `Last-Event-ID` replay, bounded reconnect backoff,
  malformed frames reported to the UI, never rendered.
- `matrix.ts` — scenario-matrix read model. Negative-control semantics are
  explicit: a control must FAIL for its intended invariants, and a control that
  passes is a red flag, not a green cell.

## Rules

- No fake data, ever. Panels without data show explicit labelled empty states.
- Every number must be traceable to a committed event or evidence id.
- The browser area shows the labelled blocker panel — never a static image
  posing as a live session.
- Reduced mode is the committed position: `demo_mode` and `degraded_reasons`
  name the browser-stack failure explicitly.
