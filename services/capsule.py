"""Frozen incident capsule assembly (plan §6).

The capsule is the only evidence Gemini and candidate creation may consume. All
hashes are computed here from the material the caller supplies, and
``capsule_sha256`` covers the canonical JSON of every other field.
"""

from __future__ import annotations

from datetime import UTC, datetime

from apps.contracts.base import canonical_sha256, sha256_hex
from apps.contracts.incident import CapsuleRowSet, IncidentCapsule, LogLine
from apps.contracts.payment import CaptureRow, FaultKind, RefundRow

__all__ = ["build_capsule"]


def build_capsule(
    *,
    incident_id: str,
    run_id: str,
    namespace: str,
    harmed_intent_id: str,
    harmed_order_id: str,
    harmed_operation_id: str,
    ledger_captures: list[CaptureRow],
    ledger_refunds: list[RefundRow],
    store_rows: CapsuleRowSet,
    recent_logs: list[LogLine],
    current_release_hash: str,
    previous_release_hash: str,
    safe_handler_hash: str,
    buggy_module_path: str,
    buggy_module_source: str,
    bounded_diff: str,
    seed_bytes: bytes,
    scenario_registry_bytes: bytes,
    oracle_source: str,
    image_digest: str,
    fault: FaultKind | None,
    expected_symptom: str,
    started_at_utc: datetime | None = None,
    started_monotonic_ns: int = 0,
    exclusions: list[str] | None = None,
    unavailable_evidence: list[str] | None = None,
) -> IncidentCapsule:
    capsule = IncidentCapsule(
        incident_id=incident_id,
        run_id=run_id,
        started_at_utc=started_at_utc or datetime.now(UTC),
        started_monotonic_ns=started_monotonic_ns,
        original_namespace=namespace,
        harmed_intent_id=harmed_intent_id,
        harmed_order_id=harmed_order_id,
        harmed_operation_id=harmed_operation_id,
        ledger_captures=ledger_captures,
        ledger_refunds=ledger_refunds,
        store_rows=store_rows,
        recent_logs=recent_logs,
        current_release_hash=current_release_hash,
        previous_release_hash=previous_release_hash,
        safe_handler_hash=safe_handler_hash,
        buggy_module_path=buggy_module_path,
        buggy_module_sha256=sha256_hex(buggy_module_source.encode("utf-8")),
        bounded_diff=bounded_diff,
        seed_hash=sha256_hex(seed_bytes),
        scenario_registry_hash=sha256_hex(scenario_registry_bytes),
        oracle_code_hash=sha256_hex(oracle_source.encode("utf-8")),
        image_digest=image_digest,
        fault=fault,
        expected_symptom=expected_symptom,
        capsule_sha256="0" * 64,
        exclusions=exclusions or [],
        unavailable_evidence=unavailable_evidence or [],
    )
    digest = canonical_sha256(capsule.model_dump(mode="json", exclude={"capsule_sha256"}))
    return capsule.model_copy(update={"capsule_sha256": digest})
