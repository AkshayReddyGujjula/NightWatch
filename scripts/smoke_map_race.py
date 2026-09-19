"""Map smoke for the candidate race (plan §12.1) — dev App in `nightwatch-b`.

The single `nightwatch` App resolves every function's secret references at load
time; `nightwatch-b` holds only Track B's names (CONTRACT_CHANGE 2026-09-19), and
ephemeral runs of the shared App in `nightwatch-demo` warm Track A's ASGI
containers against the production volumes. This script therefore binds the same
`run_candidate_impl` to a temporary dev App with only
`nightwatch-evidence-ingest`; the runner code path and the map flags
(`order_outputs=True`, `return_exceptions=True`) are identical to production.

Six concurrent worlds are requested (plan §12.1 "when extra worlds are added,
raise max_containers to match"). The frozen `CandidateId` contract is currently
`Literal["A", "B", "C"]` and `CandidateSpec` fixes kind/rank per id, so the six
inputs are two waves of the three frozen slots with distinct provider
namespaces (`ns-*-w1` / `ns-*-w2`) — the contract change that admits `C1..CN`
is filed in `CONTRACT_CHANGE.md`. Every world is still a distinct Sandbox with
its own Chrome profile, CUA daemon and app/controller split; overlap and
termination are measured, never requested.

Usage (from the repository root):

    uv run modal run -e nightwatch-b scripts/smoke_map_race.py

Evidence: one `candidate_world_finished` JSON log line per candidate carrying the
sandbox id, the world's measured browser/CUA/isolation facts and UTC lifecycle
timestamps, one strict `CandidateEvaluation` JSON per candidate in input order
(ERROR until `services/oracle.py` wires the scenario executor), a measured
maximum-overlap computation, and a post-run termination probe per sandbox id.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from datetime import datetime
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

# Two waves of the three frozen slots: six distinct Sandboxes, six distinct
# provider namespaces, six distinct CUA sessions. Order is the wave label.
WAVES = ("w1", "w2")
SLOTS = ("A", "B", "C")


def make_spec(candidate_id: str, wave: str) -> CandidateSpec:
    kind, rank = _KIND_RANK[candidate_id]
    return CandidateSpec(
        candidate_id=candidate_id,
        kind=kind,
        rank=rank,
        live_eligible=candidate_id == "B" and wave == "w1",
        image_digest="im-map-smoke",
        code_hash=_HASH,
        base_commit_sha=_GIT,
        capsule_sha256=_HASH,
        seed_hash=_HASH,
        provider_namespace=f"ns-{candidate_id}-{wave}",
    )


@app.function(
    image=SMOKE_IMAGE,
    secrets=[modal.Secret.from_name("nightwatch-evidence-ingest")],
    max_containers=8,
    timeout=600,
)
async def run_candidate_smoke(spec_json: str) -> str:
    from services_b import run_candidate_impl

    return await run_candidate_impl(spec_json, app=app)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def max_overlap(windows: list[tuple[datetime, datetime]]) -> dict[str, object]:
    """Measured maximum concurrency from real UTC lifecycle windows (plan §12.3).

    Boundary convention: a window end at instant T is processed before a window
    start at the same instant, so two windows that merely touch (one ends as the
    other begins) do not count as concurrent. Because Modal containers start and
    finish on distinct requests, exact ties are not expected; the convention is
    recorded so the number is reproducible.
    """
    events: list[tuple[datetime, int]] = []
    for start, end in windows:
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda item: (item[0], -item[1]))
    current = 0
    peak = 0
    peak_at: datetime | None = None
    for at, delta in events:
        current += delta
        if current > peak:
            peak = current
            peak_at = at
    first = min((start for start, _ in windows), default=None)
    last = max((end for _, end in windows), default=None)
    return {
        "peak": peak,
        "peak_at_utc": peak_at.isoformat() if peak_at else None,
        "window_start_utc": first.isoformat() if first else None,
        "window_end_utc": last.isoformat() if last else None,
        "wall_span_s": round((last - first).total_seconds(), 3) if first and last else None,
        "worlds_measured": len(windows),
    }


def termination_probe(sandbox_id: str) -> dict[str, object]:
    """Ask Modal for each sandbox's exit state after the map drained."""
    try:
        sandbox = modal.Sandbox.from_id(sandbox_id)
    except Exception as error:  # noqa: BLE001 - recorded, never faked
        return {"sandbox_id": sandbox_id, "error": f"{type(error).__name__}: {error}"}
    for _ in range(12):
        try:
            code = sandbox.poll()
        except Exception as error:  # noqa: BLE001 - recorded, never faked
            return {"sandbox_id": sandbox_id, "error": f"{type(error).__name__}: {error}"}
        if code is not None:
            return {"sandbox_id": sandbox_id, "terminated": True, "exit_code": code}
        time.sleep(0.5)
    return {"sandbox_id": sandbox_id, "terminated": False, "exit_code": None}


@app.local_entrypoint()
def main() -> None:
    asyncio.run(_run())


async def _run() -> None:
    specs = [make_spec(slot, wave) for wave in WAVES for slot in SLOTS]
    inputs = [spec.model_dump_json() for spec in specs]
    print(f"RACE_INPUTS={len(inputs)} MAX_CONTAINERS=8")
    index = 0
    results: list[dict[str, object]] = []
    async for item in run_candidate_smoke.map.aio(
        inputs, order_outputs=True, return_exceptions=True
    ):
        wave = WAVES[index // len(SLOTS)] if index < len(inputs) else "?"
        if isinstance(item, BaseException):
            print(f"CALL_EXCEPTION[{index}] {type(item).__name__}: {item}")
        else:
            payload = json.loads(item)
            print(
                "EVALUATION "
                + json.dumps(
                    {
                        "candidate_id": payload.get("candidate_id"),
                        "wave": wave,
                        "verdict": payload.get("verdict"),
                        "sandbox_id": payload.get("sandbox_id"),
                        "function_call_id": payload.get("function_call_id"),
                        "started_at_utc": payload.get("started_at_utc"),
                        "finished_at_utc": payload.get("finished_at_utc"),
                    }
                )
            )
            results.append(payload)
        index += 1

    windows: list[tuple[datetime, datetime]] = []
    sandbox_ids: list[str] = []
    excluded_windows = 0
    for payload in results:
        start = _parse_time(payload.get("started_at_utc"))
        end = _parse_time(payload.get("finished_at_utc"))
        if start and end and end >= start:
            windows.append((start, end))
        else:
            excluded_windows += 1
        sandbox_id = payload.get("sandbox_id")
        if isinstance(sandbox_id, str) and sandbox_id:
            sandbox_ids.append(sandbox_id)
    overlap = max_overlap(windows)
    overlap["excluded_windows"] = excluded_windows
    print("MAX_OVERLAP " + json.dumps(overlap))
    print("SANDBOX_IDS " + json.dumps(sandbox_ids))

    termination = [termination_probe(sandbox_id) for sandbox_id in sandbox_ids]
    print("TERMINATION " + json.dumps(termination, default=str))
