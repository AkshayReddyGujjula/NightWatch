"""Track A oracle/scenario preflight with raw, non-secret gate evidence."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.contracts.incident import CandidateSpec  # noqa: E402
from services.oracle import ScenarioSuite  # noqa: E402


async def main() -> int:
    suite = ScenarioSuite()
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        spec = CandidateSpec(
            candidate_id="B",
            kind="SAFE_HANDLER",
            rank=0,
            live_eligible=True,
            image_digest="local-trusted-preflight",
            code_hash=suite.code_hash,
            base_commit_sha=commit,
            capsule_sha256="c" * 64,
            seed_hash=suite.seed_hash,
            provider_namespace="gate-b",
        )
        results = await suite.execute_async(spec)
        controls = suite.oracle.run_negative_controls(spec.candidate_id)
        evidence_errors = suite.oracle.validate_evidence_set(spec, results)
        evaluation = suite.oracle.grade_candidate(spec, results)
        api_results = [result for result in results if result.scenario_id >= "S03"]
        ui_results = [result for result in results if result.scenario_id in {"S01", "S02"}]
        controls_green = {
            control.control_id: {
                "status": control.status,
                "failed_invariants": control.failed_invariants,
                "evidence_ids": control.evidence_ids,
            }
            for control in controls
        }
        output = {
            "gate": "TRACK_A_ORACLE_AND_API_SCENARIOS",
            "execution_scope": "trusted local ASGI stack with real SQLite/provider/store code",
            "modal_candidate_world_gate": "NOT_RUN_TRACK_B_RUNNER_NOT_WIRED",
            "candidate_id": spec.candidate_id,
            "seed_hash": suite.seed_hash,
            "code_hash": suite.code_hash,
            "scenario_registry_hash": suite.scenario_registry_hash,
            "oracle_code_hash": suite.oracle_hash,
            "api_scenarios_green": all(result.status == "PASS" for result in api_results),
            "browser_scenarios_labelled": all(
                result.status == "ERROR" and result.failure_reason == "ERROR_BROWSER_STACK"
                for result in ui_results
            ),
            "evidence_set_errors": evidence_errors,
            "scenario_results": [
                {
                    "scenario_id": result.scenario_id,
                    "status": result.status,
                    "failure_reason": result.failure_reason,
                    "namespace": result.app_facts.get("provider_namespace"),
                    "db_generation_sha256": result.app_facts.get(
                        "db_generation_sha256"
                    ),
                    "capture_count": result.app_facts.get("capture_count"),
                    "refund_count": result.app_facts.get("refund_count"),
                    "invariants": [
                        {
                            "id": invariant.invariant_id,
                            "status": invariant.status,
                            "evidence_ids": invariant.evidence_ids,
                        }
                        for invariant in result.invariants
                    ],
                }
                for result in results
            ],
            "negative_controls": controls_green,
            "candidate_evaluation": json.loads(evaluation.model_dump_json()),
        }
        print(json.dumps(output, indent=2, sort_keys=True))
        local_gate_green = (
            output["api_scenarios_green"]
            and output["browser_scenarios_labelled"]
            and not evidence_errors
            and controls_green["NC-01"]["failed_invariants"] == ["INV-02", "INV-05"]
            and controls_green["NC-02"]["failed_invariants"] == ["INV-01"]
        )
        return 0 if local_gate_green else 1
    finally:
        suite.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
