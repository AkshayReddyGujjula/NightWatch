# NightMart storefront (Track B)

The synthetic NightMart storefront served by `live_store_asgi` (plan §5.0).
Plain HTML/CSS/JS, no build step, no framework, no automation dependencies.

## Pages

| File | Role |
| --- | --- |
| `index.html` | Catalogue: one product (`SKU-A`, £79.99), quantity control, starts an intent |
| `checkout-x.html` | **UI X** — "Pay now", always-visible promo field, email before address |
| `checkout-y.html` | **UI Y** — "Confirm order", address before email, voucher hidden behind an "Add voucher" control |
| `status.html` | Order status / receipt, server-truth status with a raw-response drawer |
| `routes.json` | Canonical relative paths (internal to this folder; mounted paths confirmed at contract freeze) |

## Deliberate variant differences (plan §11.5)

The two checkout variants differ only in HTML structure and wording: field
order, submit label, and whether the voucher control is visible or revealed.
They share `assets/storefront.js`, `assets/api.js` and `assets/styles.css`
unchanged, and both are driven through **semantic accessible names** — there
are no variant-specific selectors anywhere, and none may be added. That is the
point: Jev + CUA must act on what the page says, not on which template it is.

## Backend contract (same for both variants)

All field names live in exactly one file: `assets/api.js`.

- `POST /api/intents` — start an intent
- `GET /api/intents/{id}` — frozen amounts for the checkout summary
- `POST /api/checkout/{intent_id}` — submit the checkout
- `GET /api/orders/{order_id}` — status/receipt truth

Contract-freeze note: these shapes follow `Final-nightwatch-plan.md` §9.2.
At the T+0:20 freeze, reconcile them against `apps/contracts/**` and
`apps/live_store/**` and edit `api.js` only. When the server returns an
`amount_minor`, it overrides the local display fixture.

Money display never invents a result: `PENDING_CONFIRMATION`, `SAFE_HOLD` and
`QUARANTINED` render as truthful pending/review states, never as success.

## Local preview (no backend)

```pwsh
uv run python -m http.server 8123 -b 127.0.0.1 --directory apps/storefront
# then open http://127.0.0.1:8123/checkout-x.html and /checkout-y.html
```

Pages render fully without the API; calls fail visibly with an error banner.

## Ownership

Track B (`apps/storefront/**`). Serve/mount wiring belongs to Track A's
`live_store_asgi`; mount path and URL scheme are confirmed at the freeze.
