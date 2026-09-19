# Modal setup — Jazil's laptop

You are the owner of the Modal workspace that holds the hackathon credits, and you are the **only person who runs `modal deploy`** all day. Akshay uses his own token for `modal serve`/`modal run` only.

Do these steps in order. Nothing here needs the repo to be cloned first, but clone it anyway because you will need `.env.example`:

```bash
git clone https://github.com/AkshayReddyGujjula/NightWatch.git
cd NightWatch
```

Time: about 15 minutes. Total commands: 12.

---

## Step 1 — Install the Modal CLI

```bash
# install uv (skip if `uv --version` already works)
curl -LsSf https://astral.sh/uv/install.sh | sh

# install the Modal CLI as a tool
uv tool install modal

# if `modal` is not found, make sure ~/.local/bin is on PATH:
uv tool update-shell
# then close and reopen the terminal

modal --version
```

Expected: a version number (Akshay has `1.5.5`).

## Step 2 — Log in to the right workspace

```bash
modal token new
```

This opens a browser. **Pick the workspace that shows the $100 credit** — not a personal one. It writes `~/.modal.toml`.

Verify:

```bash
modal environment list
```

Expected: at least `main`. If the command name differs in your CLI version, `modal environment --help` shows the correct one — the point is only to prove auth works.

## Step 3 — Get the two vendor keys from Akshay (before creating secrets)

Ask him privately (Discord DM) for:

- `GOOGLE_API_KEY` — Google AI Studio key
- `TYPESAFE_API_KEY` — TypeSafe key

These two live in *your* workspace because every Modal secret is created here. Do not paste them into the repo, into a public channel, or into a screenshot.

## Step 4 — Generate the six internal tokens and save them

```bash
cat > ~/nightwatch-tokens.txt <<EOF
NIGHTWATCH_OPERATOR_TOKEN=$(openssl rand -hex 32)
CONTROL_EVENT_TOKEN=$(openssl rand -hex 32)
LIVE_INTERNAL_TOKEN=$(openssl rand -hex 32)
PROVIDER_SIGNING_SECRET=$(openssl rand -hex 32)
EVALUATOR_TOKEN=$(openssl rand -hex 32)
FRAME_INGEST_TOKEN=$(openssl rand -hex 32)
EOF

cat ~/nightwatch-tokens.txt
```

Copy that file's contents somewhere you can paste from (password manager or a private note). You will send these values to Akshay in Step 7. Delete the file from your home directory once they are stored somewhere safe.

## Step 5 — Create the six secrets

One command per secret. The names must match exactly — the code looks them up by name.

```bash
set -a; source ~/nightwatch-tokens.txt; set +a

modal secret create nightwatch-gemini \
  GOOGLE_API_KEY='<paste the AI Studio key>'

modal secret create nightwatch-typesafe \
  TYPESAFE_API_KEY='<paste the TypeSafe key>' \
  TYPESAFE_MODEL='jev-1.13.0'

modal secret create nightwatch-control \
  NIGHTWATCH_OPERATOR_TOKEN="$NIGHTWATCH_OPERATOR_TOKEN" \
  CONTROL_EVENT_TOKEN="$CONTROL_EVENT_TOKEN"

modal secret create nightwatch-live-internal \
  LIVE_INTERNAL_TOKEN="$LIVE_INTERNAL_TOKEN"

modal secret create nightwatch-provider \
  PROVIDER_SIGNING_SECRET="$PROVIDER_SIGNING_SECRET" \
  EVALUATOR_TOKEN="$EVALUATOR_TOKEN"

modal secret create nightwatch-evidence-ingest \
  FRAME_INGEST_TOKEN="$FRAME_INGEST_TOKEN"
```

Why six and not one: each function gets only the credentials it actually needs. Never reuse one token for two purposes.

| Secret | Used by | Why |
| --- | --- | --- |
| `nightwatch-gemini` | incident orchestrator | Gemini diagnosis + patch proposal |
| `nightwatch-typesafe` | candidate runner | Jev action choices (must never enter a candidate sandbox) |
| `nightwatch-control` | control plane, orchestrator | operator API + internal event writes |
| `nightwatch-live-internal` | live store | router mode changes |
| `nightwatch-provider` | mock payment provider | signed ledger reads, refunds |
| `nightwatch-evidence-ingest` | candidate runner only | frame/evidence upload, scoped per run |

Leave `GEMINI_MODEL` out for now — it gets added at the preflight once we know exactly which model answers a live structured-output call.

## Step 6 — Create the three environments and copy the secrets

```bash
modal environment create nightwatch-a
modal environment create nightwatch-b
modal environment create nightwatch-demo
modal environment list
```

If those commands are not available in your CLI version, use the **environment dropdown in the dashboard header** (next to `Starter`) and create them there.

**Secrets are environment-scoped**, so now copy them in. In the dashboard: open the target environment → Secrets → **Copy from another environment** → pick the source. Copy only what each environment needs:

| Environment | Who uses it | Secrets to copy in |
| --- | --- | --- |
| `nightwatch-a` | Track A dev | `nightwatch-gemini`, `nightwatch-control` |
| `nightwatch-b` | Track B dev | `nightwatch-typesafe`, `nightwatch-evidence-ingest` |
| `nightwatch-demo` | the integrated app (only you deploy it) | all six |

## Step 7 — Send Akshay what he needs

Send him privately:

1. **The Modal token** — open `~/.modal.toml` and copy `token_id` and `token_secret`. He runs:
   ```bash
   modal token set --token-id '<id>' --token-secret '<secret>'
   ```
2. **The six internal tokens** from Step 4, so his local `.env` matches your workspace.

Treat the token like a password. It grants access to your workspace and your credits.

## Step 8 — Smoke test (proves billing and the runtime actually work)

```bash
cat > /tmp/nw_smoke.py <<'PY'
import modal

app = modal.App("nightwatch-smoke")

@app.function()
def hello() -> str:
    return "function ok"

@app.local_entrypoint()
def main() -> None:
    print(hello.remote())
    with modal.Sandbox.create(app=app, image=modal.Image.debian_slim()) as sb:
        print(sb.exec("bash", "-lc", "echo sandbox ok").stdout.read().decode().strip())
PY

modal run /tmp/nw_smoke.py
```

Expected: `function ok` then `sandbox ok`.

If it fails with a billing or quota error: the dashboard banner said "$0 of $30/mo in free credits — add a payment method to unlock the rest". In that case add a payment method, or find a Modal mentor at the event before touching anything else. Nothing in the build works until this smoke passes.

## Step 9 — Set up your own `.env`

```bash
cp .env.example .env
```

Fill in on your side: `GOOGLE_API_KEY`, `TYPESAFE_API_KEY`, the six tokens, and `MODAL_ENVIRONMENT=nightwatch-a`.

`.env` is gitignored — verified — and `.env.example` is the only one that may ever be committed. The repo is public.

---

## Checklist

- [ ] `modal --version` works
- [ ] `modal token new` completed against the workspace with the $100 credit
- [ ] `modal environment list` works
- [ ] Six secrets created with the exact names above
- [ ] Three environments created; secrets copied into each
- [ ] Token + six internal tokens sent to Akshay privately
- [ ] Smoke test prints `function ok` and `sandbox ok`
- [ ] `.env` filled in locally, never committed

Report back with the exact command that failed if something breaks — not the error text alone.
