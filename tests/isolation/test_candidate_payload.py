"""Candidate payloads contain real app bytes and fail closed when inputs are absent."""

from __future__ import annotations

import pytest

from apps.contracts.incident import CandidateSpec
from services.oracle import live_store_code_hash
from services.worlds.payload import CandidatePayloadUnavailable, build_candidate_payload

_HASH = "a" * 64
_GIT_SHA = "b" * 40


def _spec(candidate_id: str) -> CandidateSpec:
    kind, rank = {
        "A": ("ROLLBACK", 1),
        "B": ("SAFE_HANDLER", 0),
        "C": ("GEMINI_PATCH", 2),
    }[candidate_id]
    return CandidateSpec(
        candidate_id=candidate_id,
        kind=kind,
        rank=rank,
        live_eligible=candidate_id == "B",
        image_digest="im-candidate-test",
        code_hash=live_store_code_hash() if candidate_id == "B" else _HASH,
        base_commit_sha=_GIT_SHA,
        capsule_sha256=_HASH,
        seed_hash=_HASH,
        provider_namespace=f"payload-{candidate_id.lower()}",
    )


def test_candidate_b_payload_contains_storefront_and_safe_bootstrap() -> None:
    payload = build_candidate_payload(_spec("B"))

    assert payload.ready_path == "/health"
    assert payload.browser_enabled
    assert payload.code_hash == live_store_code_hash()
    assert "candidate_boot:app" in payload.start_command
    assert "/opt/nightwatch/app/apps/live_store/app.py" in payload.files
    assert "/opt/nightwatch/app/apps/storefront/checkout-x.html" in payload.files
    bootstrap = payload.files["/opt/nightwatch/app/candidate_boot.py"]
    assert 'mode="SAFE"' in bootstrap
    assert "candidate-b-evaluation" in bootstrap


@pytest.mark.parametrize("candidate_id", ["A", "C"])
def test_unavailable_candidate_bytes_fail_closed(candidate_id: str) -> None:
    with pytest.raises(CandidatePayloadUnavailable):
        build_candidate_payload(_spec(candidate_id))
