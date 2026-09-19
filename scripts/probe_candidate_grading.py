"""Run one real Candidate B world through CORE S03-S08 grading.

This is a Track B ephemeral evidence probe. It calls the same
``run_candidate_impl`` used by the deployed function, while constructing the
spec inside the Linux runner so the frozen SQLite seed hash is measured in the
same environment that executes the suite.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import modal

_REPO_ROOT = Path(__file__).resolve().parents[1]
if modal.is_local():
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    import modal_app  # noqa: F401

from services_b import RUNNER_IMAGE  # noqa: E402

app = modal.App("nightwatch-b-candidate-grading")
PROBE_IMAGE = RUNNER_IMAGE.add_local_file("modal/services_b.py", "/root/services_b.py")


@app.function(
    image=PROBE_IMAGE,
    secrets=[modal.Secret.from_name("nightwatch-evidence-ingest")],
    timeout=600,
)
async def grade_candidate_b() -> str:
    from services_b import run_candidate_impl

    from apps.contracts.incident import CandidateSpec
    from services.oracle import ScenarioSuite

    suite = ScenarioSuite()
    spec = CandidateSpec(
        candidate_id="B",
        kind="SAFE_HANDLER",
        rank=0,
        live_eligible=True,
        image_digest="im-track-b-real-payload",
        code_hash=suite.code_hash,
        base_commit_sha="35db0e1572e61a5f0e51c2f744452346388ef9c9",
        capsule_sha256="a" * 64,
        seed_hash=suite.seed_hash,
        provider_namespace=f"track-b-real-{uuid.uuid4().hex[:12]}",
    )
    try:
        return await run_candidate_impl(
            spec.model_dump_json(), app=app, scenario_suite=suite
        )
    finally:
        suite.close()


@app.local_entrypoint()
def main() -> None:
    evaluation = grade_candidate_b.remote()
    print("CANDIDATE_EVALUATION " + json.dumps(json.loads(evaluation), sort_keys=True))
