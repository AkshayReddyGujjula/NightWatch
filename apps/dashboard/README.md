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
`control_asgi`; live endpoints must send `Cache-Control: no-store`, and SSE
reconnect uses `Last-Event-ID` once Track A's event route lands.

## Rules

- No fake data, ever. Panels without data show explicit labelled empty states.
- Every number must be traceable to a committed event or evidence id.
- The browser area shows the labelled blocker panel — never a static image
  posing as a live session.
- Reduced mode is the committed position: `demo_mode` and `degraded_reasons`
  name the browser-stack failure explicitly.
