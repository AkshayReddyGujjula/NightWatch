"""Shared Track B browser-pipeline test helpers (plan §11.7)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from apps.contracts.base import CandidateId, sha256_hex
from apps.contracts.browser import BrowserFrame, BrowserReadyRequest, FramePhase
from apps.control_plane.routes import world_session_hash

RUN_ID = "run_browser_test"
IMAGE = b"\xff\xd8\xff\xe0nightwatch-browser-frame-bytes"
CAPTURED_AT = datetime(2026, 9, 19, 13, 5, tzinfo=UTC)


def make_frame(
    seq: int,
    *,
    candidate_id: CandidateId = "B",
    run_id: str = RUN_ID,
    phase: FramePhase = "SAMPLE",
    captured_monotonic_ns: int | None = None,
    image: bytes = IMAGE,
    **overrides: Any,
) -> BrowserFrame:
    """Build a strict ``BrowserFrame`` with real hashes over ``image``."""
    payload: dict[str, Any] = {
        "run_id": run_id,
        "candidate_id": candidate_id,
        "scenario_id": "S02",
        "frame_seq": seq,
        "sandbox_id": "sb-b111",
        "cua_session_id": "cua-b222",
        "snapshot_id": f"snap-{seq:04d}",
        "capture_id": f"cap-{seq:04d}",
        "phase": phase,
        "captured_monotonic_ns": (
            captured_monotonic_ns
            if captured_monotonic_ns is not None
            else 1_000_000_000 + seq * 500_000_000
        ),
        "captured_at_utc": CAPTURED_AT,
        "image_sha256": sha256_hex(image),
        "image_size_bytes": len(image),
        "image_mime": "image/jpeg",
    }
    payload.update(overrides)
    return BrowserFrame(**payload)


def ready_body(candidate: CandidateId, *, run_id: str = RUN_ID) -> BrowserReadyRequest:
    """Build a session-hash-bound readiness body for one candidate."""
    sandbox = f"sb-{candidate.lower()}111"
    session = f"cua-{candidate.lower()}222"
    return BrowserReadyRequest(
        run_id=run_id,
        sandbox_id=sandbox,
        cua_session_id=session,
        session_hash=world_session_hash(run_id, candidate, sandbox, session),
    )


class FakeNsClock:
    """Deterministic monotonic clock in nanoseconds for the sampler."""

    def __init__(self, start_ns: int = 1_000_000_000) -> None:
        self.now_ns = start_ns

    def __call__(self) -> int:
        return self.now_ns

    def advance_ns(self, delta_ns: int) -> None:
        self.now_ns += delta_ns


class FakeSecondsClock:
    """Deterministic monotonic clock in float seconds for the uploader budget."""

    def __init__(self, start_s: float = 1_000.0) -> None:
        self.now_s = start_s

    def __call__(self) -> float:
        return self.now_s

    def advance(self, seconds: float) -> None:
        self.now_s += seconds
