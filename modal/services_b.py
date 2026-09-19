"""Track B — `run_candidate` bound to the single nightwatch Modal App (plan §12.1).

Each invocation creates exactly one Modal Sandbox through
:class:`services.worlds.modal_world.ModalWorld` and returns a strict
``CandidateEvaluation`` JSON string for ``services.scheduler.race``. The runner
container holds only runner-scoped credentials; nothing is ever passed into the
Sandbox (the world's scoped provider token arrives with the scenario executor).

Import mechanics (recorded in ``CONTRACT_CHANGE.md``): the repository directory
``modal/`` cannot be imported as ``modal.services_a`` — the installed ``modal``
SDK is a regular package and always shadows the namespace portion (verified
live), so ``modal_app.py`` puts this directory on ``sys.path`` and both service
modules import each other by top-level module name. Paths and the one-App shape
are unchanged; no second ``modal.App`` may exist.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime

from services_a import app  # noqa: F401  (sys.path shim lives in modal_app.py)

import modal
from apps.contracts.base import ScenarioId
from apps.contracts.evaluation import CandidateEvaluation, InvariantId
from apps.contracts.incident import CandidateSpec
from services.worlds.interface import CandidatePayload, WorldLifecycle
from services.worlds.modal_world import ModalWorld
from services.worlds.runner import run_candidate_world

_REGISTRY_PATH = "/root/fixtures/scenarios.json"

RUNNER_IMAGE = (
    modal.Image.debian_slim(python_version="3.12")
    # fastapi is not used by the runner: the frozen seam makes services_b import
    # services_a, whose module body imports FastAPI. Import-graph cost only.
    .pip_install("pydantic==2.13.5", "httpx==0.28.1", "fastapi==0.141.1")
    .add_local_python_source("apps", "infra", "services")
    # add_local_python_source ships only .py files; the desktop image definition
    # needs its non-Python assets beside the package inside the container.
    .add_local_file("infra/start_desktop_world.sh", "/root/infra/start_desktop_world.sh")
    .add_local_file("infra/cua_capabilities.json", "/root/infra/cua_capabilities.json")
    .add_local_file("fixtures/scenarios.json", _REGISTRY_PATH)
    # services_b imports the shared app from services_a; Modal auto-mounts the
    # defining module of a function but not its transitive imports, so the
    # shared-app module must be mounted explicitly for `from services_a import app`.
    .add_local_file("modal/services_a.py", "/root/services_a.py")
)

# Candidate worlds boot with the browser stack enabled: one controller-owned
# Chrome with a world-local profile, one bounded CUA daemon and one named CUA
# session per Sandbox. Until the S01/S02 journey driver is wired (Track A's
# scenario executor + services/jev), a booted world is real browser-isolation
# evidence only — it is not a claim that a browser journey ran. The payload is a
# plain static file server with no candidate code; the scenario executor injects
# the world-scoped provider token when it lands.
_STUB_PAYLOAD = CandidatePayload(
    files={},
    start_command="python3 -m http.server 8080 --bind 127.0.0.1",
    ready_path="/",
    browser_enabled=True,
)


def _expected_ids() -> tuple[list[ScenarioId], list[InvariantId]]:
    """Scenario/invariant ids from the frozen registry, for the ERROR shell."""
    with open(_REGISTRY_PATH, encoding="utf-8") as handle:
        registry = json.load(handle)
    scenario_ids: list[ScenarioId] = [
        scenario["scenario_id"] for scenario in registry["scenarios"]
    ]
    invariant_ids: list[InvariantId] = sorted(
        {invariant for scenario in registry["scenarios"] for invariant in scenario["invariants"]}
    )
    return scenario_ids, invariant_ids


def _iso(value: datetime | None) -> str | None:
    """UTC wall-clock instant for cross-container lifecycle evidence (plan §12.3)."""
    return value.isoformat() if value is not None else None


def _lifecycle_evidence(lifecycle: WorldLifecycle | None) -> dict[str, object]:
    """Sandbox id + cross-container timestamps for the candidate evidence log."""
    if lifecycle is None:
        return {
            "sandbox_id": None,
            "created_at_utc": None,
            "ready_at_utc": None,
            "finished_at_utc": None,
            "startup_span_ms": None,
            "terminated": None,
        }
    span = lifecycle.startup_span_ns
    return {
        "sandbox_id": lifecycle.sandbox_id,
        "created_at_utc": _iso(lifecycle.created_at_utc),
        "ready_at_utc": _iso(lifecycle.ready_at_utc),
        "finished_at_utc": _iso(lifecycle.finished_at_utc),
        "startup_span_ms": round(span / 1_000_000, 1) if span is not None else None,
        "terminated": lifecycle.terminated,
    }


@app.function(
    image=RUNNER_IMAGE,
    secrets=[modal.Secret.from_name("nightwatch-evidence-ingest")],
    max_containers=8,
    timeout=600,
)
async def run_candidate(spec_json: str) -> str:
    """One candidate world bound to the shared app; returns strict evaluation JSON."""
    return await run_candidate_impl(spec_json, app=app)


async def run_candidate_impl(spec_json: str, *, app: modal.App) -> str:
    """The runner body, importable so dev harnesses reuse this exact code path.

    A crashed or unevaluable world becomes this candidate's own ERROR
    evaluation (see ``services.worlds.runner``); it can never contaminate
    another candidate's verdict and is never a pass.
    """
    spec = CandidateSpec.model_validate_json(spec_json, strict=True)
    scenario_ids, invariant_ids = _expected_ids()
    world = ModalWorld(
        app=app,
        payload=_STUB_PAYLOAD,
        environment=os.environ.get("MODAL_ENVIRONMENT", ""),
        # Sandbox lifetime must stay below the function timeout (600 s) so a
        # killed function can never leave a live Sandbox behind.
        timeout_s=540,
        idle_timeout_s=240,
    )
    run = await asyncio.to_thread(
        run_candidate_world,
        spec,
        world,
        expected_scenario_ids=scenario_ids,
        expected_invariant_ids=invariant_ids,
    )
    # Plan §12.3 evidence: attach the real Modal function call id and sandbox id
    # to the evaluation (ERROR never becomes eligible; ids are measured facts).
    function_call_id: str | None = None
    if not modal.is_local():
        function_call_id = modal.current_function_call_id()
    lifecycle = run.lifecycle
    evidence = json.loads(run.evaluation.model_dump_json())
    if evidence.get("sandbox_id") is None and lifecycle is not None:
        evidence["sandbox_id"] = lifecycle.sandbox_id
    if evidence.get("function_call_id") is None and function_call_id is not None:
        evidence["function_call_id"] = function_call_id
    evaluation = CandidateEvaluation.model_validate_json(json.dumps(evidence), strict=True)
    # Per-world isolation facts measured inside this Sandbox (plan §12.2): the
    # browser, CUA daemon and the app/controller OS-user split this world owns.
    world_facts = world.world_evidence
    print(
        json.dumps(
            {
                "event": "candidate_world_finished",
                "candidate_id": spec.candidate_id,
                "provider_namespace": spec.provider_namespace,
                "function_call_id": function_call_id,
                "verdict": evaluation.verdict,
                "failures": run.failures,
                **_lifecycle_evidence(lifecycle),
                "world": {
                    "app_uid": world_facts.get("app_uid"),
                    "controller_uid": world_facts.get("controller_uid"),
                    "app_home_mode": world_facts.get("app_home_mode"),
                    "controller_home_mode": world_facts.get("controller_home_mode"),
                    "run_dir_mode": world_facts.get("run_dir_mode"),
                    "cua_socket_mode": world_facts.get("cua_socket_mode"),
                    "cua_manifest_sha256": world_facts.get("cua_manifest_sha256"),
                    "cua_driver_version": world_facts.get("cua_driver_version"),
                    "cua_driver_pid": world_facts.get("cua_driver_pid"),
                    "chrome_pid": world_facts.get("chrome_pid"),
                    "chrome_profile": world_facts.get("chrome_profile"),
                    "chrome_profile_mode": world_facts.get("chrome_profile_mode"),
                    "browser_version": world_facts.get("browser_version"),
                    "browser_window_id": world_facts.get("browser_window_id"),
                    "browser_devtools_port": world_facts.get("browser_devtools_port"),
                },
            }
        )
    )
    return evaluation.model_dump_json()
