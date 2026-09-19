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

from services_a import app  # noqa: F401  (sys.path shim lives in modal_app.py)

import modal
from apps.contracts.base import ScenarioId
from apps.contracts.evaluation import InvariantId
from apps.contracts.incident import CandidateSpec
from services.worlds.interface import CandidatePayload
from services.worlds.modal_world import ModalWorld
from services.worlds.runner import run_candidate_world

_REGISTRY_PATH = "/root/fixtures/scenarios.json"

RUNNER_IMAGE = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("pydantic==2.13.5", "httpx==0.28.1")
    .add_local_python_source("apps", "infra", "services")
    # add_local_python_source ships only .py files; the desktop image definition
    # needs its non-Python assets beside the package inside the container.
    .add_local_file("infra/start_desktop_world.sh", "/root/infra/start_desktop_world.sh")
    .add_local_file("infra/cua_capabilities.json", "/root/infra/cua_capabilities.json")
    .add_local_file("fixtures/scenarios.json", _REGISTRY_PATH)
)

# Reduced mode until the scenario executor + grader are wired (Track A's
# services/oracle.py): the world boots with a labelled stub server and the
# runner returns an ERROR evaluation recording the missing link. The live
# candidate payload (apps/live_store + scoped provider token) replaces this the
# moment the provider is reachable from a world.
_STUB_PAYLOAD = CandidatePayload(
    files={},
    start_command="python3 -m http.server 8080 --bind 127.0.0.1",
    ready_path="/",
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


@app.function(
    image=RUNNER_IMAGE,
    secrets=[modal.Secret.from_name("nightwatch-evidence-ingest")],
    max_containers=3,
    timeout=600,
)
async def run_candidate(spec_json: str) -> str:
    """One candidate world; returns strict ``CandidateEvaluation`` JSON.

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
    )
    run = await asyncio.to_thread(
        run_candidate_world,
        spec,
        world,
        expected_scenario_ids=scenario_ids,
        expected_invariant_ids=invariant_ids,
    )
    print(
        json.dumps(
            {
                "event": "candidate_world_finished",
                "candidate_id": spec.candidate_id,
                "sandbox_id": run.lifecycle.sandbox_id if run.lifecycle else None,
                "verdict": run.evaluation.verdict,
                "failures": run.failures,
            }
        )
    )
    return run.evaluation.model_dump_json()
