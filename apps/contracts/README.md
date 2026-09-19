# Frozen boundary contracts (Track A)

Plan §7 and §16.1. Every external or model boundary is a strict Pydantic model:
`extra="forbid"`, `strict=True`, `frozen=True`. JSON call sites validate with
`model_validate_json(..., strict=True)`.

## Files

| File | Contents |
| --- | --- |
| `base.py` | `StrictModel`, `Hash256`, `GitSha40`, `UtcDatetime` / `IsoUtcDatetime`, id aliases, `canonical_sha256` |
| `browser.py` | observation, Jev decision, `BrowserFrame`, barrier models |
| `incident.py` | events, capsule, `GeminiDiagnosis` + advisory triage (§10.4), `PatchProposal`, `CandidateSpec` |
| `payment.py` | store rows, provider ledger rows, public store API (api.js names), router state/update, scoped tokens |
| `evaluation.py` | S01–S08 registry models, invariant results, scenario/candidate evaluation, stage events |
| `lease.py` | `RepairLease`, `RepairReceipt` |

Frozen examples live in `fixtures/expected/**` and `fixtures/scenarios.json`;
guards are `tests/unit/test_contract_browser.py`,
`tests/unit/test_contract_domain.py` and
`tests/integration/test_internal_frames_contract.py`.

## `POST /internal/frames` (unblocks Track B)

Multipart, scoped runner bearer auth (`FRAME_INGEST_TOKEN`):

- part `metadata` — strict `BrowserFrame` JSON
  (example: `fixtures/expected/internal_frames_metadata.json`);
- part `image` — binary, must satisfy `image_size_bytes <= 358400` (350 KB),
  `sha256(image) == image_sha256`, and part content-type == `image_mime`.

Statuses: `200` ack · `401` auth · `404` unknown run · `409` sequence
regression (`frame_seq` must strictly increase per run/candidate; gaps are
allowed because stale `SAMPLE` frames may be coalesced) · `413` over the hard
cap · `422` metadata, hash, size or MIME mismatch.

## Barrier endpoints

- `POST /internal/worlds/{candidate_id}/browser-ready` — registers one world;
  idempotent per candidate.
- `GET /internal/runs/{run_id}/browser-barrier` — returns
  `BrowserBarrierState`; releases generation `+1` when every expected candidate
  is ready, otherwise `PENDING`, or `TIMEOUT` after `timeout_seconds`.

## Freeze decisions (please object via `CONTRACT_CHANGE.md`)

1. Barrier release carries **no signature field**; release authenticity is the
   scoped runner bearer token plus generation monotonicity.
2. `session_hash = sha256("{run_id}|{candidate_id}|{sandbox_id}|{cua_session_id}")`
   (`routes.world_session_hash`), enforced on every ready post.
3. Barrier default timeout is **120 s**; `TIMEOUT` is a typed state, not an
   HTTP error.
4. `ObservedControl.purpose` vocabulary:
   `submit · email · address · voucher · quantity · sku · other`.
5. Action IDs match `^[a-z][a-z0-9_]{0,63}$`; reserved IDs are `reobserve`,
   `abstain`, `done_unverified` (pilot shape `click__a17` already validates).

## Regenerating schemas

```bash
uv run python scripts/gen_schemas.py
```

Committed under `apps/contracts/schemas/`; regenerated whenever a contract
definition changes.
