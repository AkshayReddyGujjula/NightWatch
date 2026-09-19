"""Map smoke for the candidate race (plan §12.1) — dev App in `nightwatch-b`.

The single `nightwatch` App resolves every function's secret references at load
time; `nightwatch-b` holds only Track B's names (CONTRACT_CHANGE 2026-09-19), and
ephemeral runs of the shared App in `nightwatch-demo` warm Track A's ASGI
containers against the production volumes. This script therefore binds the same
`run_candidate_impl` to a temporary dev App with only
`nightwatch-evidence-ingest`; the runner code path and the map flags
(`order_outputs=True`, `return_exceptions=True`) are identical to production.

Usage (from the repository root):

    uv run modal run -e nightwatch-b scripts/smoke_map_race.py

Evidence: one `candidate_world_finished` JSON log line per candidate carrying the
sandbox id and UTC lifecycle timestamps, plus one strict `CandidateEvaluation`
JSON per candidate in input order (ERROR until `services/oracle.py` wires the
scenario executor).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import modal

_REPO_ROOT = Path(__file__).resolve().parents[1]

if modal.is_local():
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    import modal_app  # noqa: F401  (wiring + sys.path shim for local imports)

from services_b import RUNNER_IMAGE  # noqa: E402

from apps.contracts.incident import CandidateSpec  # noqa: E402

app = modal.App("nightwatch-b-map-smoke")

# services_b is not the defining module of this function, so mount it for the
# in-container import (its own image already carries the shared-app module).
SMOKE_IMAGE = RUNNER_IMAGE.add_local_file("modal/services_b.py", "/root/services_b.py")

_HASH = "a" * 64
_GIT = "b" * 40
_KIND_RANK = {"A": ("ROLLBACK", 1), "B": ("SAFE_HANDLER", 0), "C": ("GEMINI_PATCH", 2)}


def make_spec(candidate_id: str) -> CandidateSpec:
    kind, rank = _KIND_RANK[candidate_id]
    return CandidateSpec(
        candidate_id=candidate_id,
        kind=kind,
        rank=rank,
        live_eligible=candidate_id == "B",
        image_digest="im-map-smoke",
        code_hash=_HASH,
        base_commit_sha=_GIT,
        capsule_sha256=_HASH,
        seed_hash=_HASH,
        provider_namespace=f"ns-{candidate_id}",
    )


@app.function(
    image=SMOKE_IMAGE,
    secrets=[modal.Secret.from_name("nightwatch-evidence-ingest")],
    max_containers=3,
    timeout=600,
)
async def run_candidate_smoke(spec_json: str) -> str:
    from services_b import run_candidate_impl

    return await run_candidate_impl(spec_json, app=app)


@app.local_entrypoint()
def main() -> None:
    asyncio.run(_run())


async def _run() -> None:
    specs = [make_spec(candidate_id) for candidate_id in ("A", "B", "C")]
    inputs = [spec.model_dump_json() for spec in specs]
    print(f"RACE_INPUTS={len(inputs)}")
    index = 0
    async for item in run_candidate_smoke.map.aio(
        inputs, order_outputs=True, return_exceptions=True
    ):
        if isinstance(item, BaseException):
            print(f"CALL_EXCEPTION[{index}] {type(item).__name__}: {item}")
        else:
            payload = json.loads(item)
            print(
                "EVALUATION "
                + json.dumps(
                    {
                        "candidate_id": payload.get("candidate_id"),
                        "verdict": payload.get("verdict"),
                        "sandbox_id": payload.get("sandbox_id"),
                        "function_call_id": payload.get("function_call_id"),
                    }
                )
            )
        index += 1
