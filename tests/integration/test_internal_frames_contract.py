"""HTTP contract tests: POST /internal/frames and the browser barrier (plan §32.3)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.contracts.base import sha256_hex
from apps.contracts.browser import MAX_FRAME_BYTES
from apps.control_plane.app import create_app
from apps.control_plane.config import ControlSettings
from apps.control_plane.routes import world_session_hash

TOKEN = "test-frame-ingest-token"
RUN_ID = "run_contract_test"
IMAGE = b"nightwatch-contract-test-frame-bytes"
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "expected"

AUTH = {"Authorization": f"Bearer {TOKEN}"}


def make_client(*, timeout_seconds: float = 120.0) -> tuple[TestClient, FastAPI]:
    app = create_app(
        ControlSettings(frame_ingest_token=TOKEN),
        barrier_timeout_seconds=timeout_seconds,
    )
    app.state.frames.register_run(RUN_ID)
    return TestClient(app), app


def frame_metadata(seq: int, **overrides: Any) -> dict[str, Any]:
    payload = json.loads((FIXTURES / "internal_frames_metadata.json").read_text())
    payload.update(
        {
            "run_id": RUN_ID,
            "candidate_id": "B",
            "frame_seq": seq,
            "image_size_bytes": len(IMAGE),
            "image_sha256": sha256_hex(IMAGE),
            "image_mime": "image/jpeg",
        }
    )
    payload.update(overrides)
    return payload


def post_frame(
    client: TestClient,
    metadata: dict[str, Any],
    *,
    image: bytes = IMAGE,
    part_mime: str = "image/jpeg",
    headers: dict[str, str] | None = None,
) -> Any:
    return client.post(
        "/internal/frames",
        data={"metadata": json.dumps(metadata)},
        files={"image": ("frame.jpg", image, part_mime)},
        headers=AUTH if headers is None else headers,
    )


def ready_body(candidate: str, **overrides: Any) -> dict[str, Any]:
    sandbox = overrides.pop("sandbox_id", f"sb-{candidate.lower()}111")
    session = overrides.pop("cua_session_id", f"cua-{candidate.lower()}222")
    payload = {
        "run_id": RUN_ID,
        "sandbox_id": sandbox,
        "cua_session_id": session,
        "session_hash": world_session_hash(RUN_ID, candidate, sandbox, session),
    }
    payload.update(overrides)
    return payload


def post_ready(client: TestClient, candidate: str, **overrides: Any) -> Any:
    return client.post(
        f"/internal/worlds/{candidate}/browser-ready",
        json=ready_body(candidate, **overrides),
        headers=AUTH,
    )


# ---------------------------------------------------------------- frames


def test_health_needs_no_auth() -> None:
    client, _ = make_client()
    assert client.get("/health").status_code == 200


def test_frames_reject_missing_and_wrong_auth() -> None:
    client, _ = make_client()
    assert post_frame(client, frame_metadata(0), headers={}).status_code == 401
    response = post_frame(
        client, frame_metadata(0), headers={"Authorization": "Bearer not-the-token"}
    )
    assert response.status_code == 401


def test_frame_happy_path_acks_sequence() -> None:
    client, _ = make_client()
    response = post_frame(client, frame_metadata(3))
    assert response.status_code == 200
    assert response.json() == {
        "run_id": RUN_ID,
        "candidate_id": "B",
        "frame_seq": 3,
        "latest_seq": 3,
    }


def test_frame_sequence_must_strictly_increase() -> None:
    client, _ = make_client()
    assert post_frame(client, frame_metadata(3)).status_code == 200
    assert post_frame(client, frame_metadata(3)).status_code == 409
    assert post_frame(client, frame_metadata(2)).status_code == 409
    # Gaps are allowed: stale SAMPLE frames may be coalesced (plan §11.7).
    assert post_frame(client, frame_metadata(4)).status_code == 200


def test_frame_for_unknown_run_is_rejected() -> None:
    client, _ = make_client()
    response = post_frame(client, frame_metadata(0, run_id="run_never_registered"))
    assert response.status_code == 404


def test_frame_hash_and_size_are_verified() -> None:
    client, _ = make_client()
    assert post_frame(client, frame_metadata(0, image_sha256="a" * 64)).status_code == 422
    bad_size = frame_metadata(0, image_size_bytes=len(IMAGE) + 1)
    assert post_frame(client, bad_size).status_code == 422


def test_frame_oversize_bytes_hit_the_hard_cap() -> None:
    client, _ = make_client()
    oversize = b"x" * (MAX_FRAME_BYTES + 1)
    metadata = frame_metadata(0, image_size_bytes=MAX_FRAME_BYTES)
    assert post_frame(client, metadata, image=oversize).status_code == 413


def test_frame_part_mime_must_match_declared_mime() -> None:
    client, _ = make_client()
    assert post_frame(client, frame_metadata(0), part_mime="image/webp").status_code == 422


def test_frame_metadata_extra_field_rejected() -> None:
    client, _ = make_client()
    assert post_frame(client, frame_metadata(0, surprise=1)).status_code == 422


# --------------------------------------------------------------- barrier


def test_barrier_pending_until_all_expected_worlds_ready() -> None:
    client, _ = make_client()
    assert post_ready(client, "A").json()["status"] == "PENDING"
    assert post_ready(client, "B").json()["status"] == "PENDING"
    released = post_ready(client, "C").json()
    assert released["status"] == "RELEASED"
    assert released["generation"] == 1
    assert sorted(world["candidate_id"] for world in released["ready"]) == ["A", "B", "C"]

    readback = client.get(f"/internal/runs/{RUN_ID}/browser-barrier", headers=AUTH)
    assert readback.status_code == 200
    assert readback.json()["status"] == "RELEASED"
    assert readback.json()["released_at_utc"] is not None


def test_barrier_ready_is_idempotent_per_candidate() -> None:
    client, _ = make_client()
    post_ready(client, "A")
    post_ready(client, "B")
    again = post_ready(client, "A").json()
    assert again["status"] == "PENDING"
    assert sorted(world["candidate_id"] for world in again["ready"]) == ["A", "B"]


def test_barrier_rejects_session_hash_mismatch() -> None:
    client, _ = make_client()
    response = post_ready(client, "A", session_hash="b" * 64)
    assert response.status_code == 422


def test_barrier_rejects_unexpected_candidate() -> None:
    client, app = make_client()
    app.state.frames.expect(RUN_ID, ["A", "B"])
    assert post_ready(client, "C").status_code == 409


def test_barrier_times_out_typed() -> None:
    client, _ = make_client(timeout_seconds=0.05)
    post_ready(client, "A")
    time.sleep(0.1)
    state = client.get(f"/internal/runs/{RUN_ID}/browser-barrier", headers=AUTH).json()
    assert state["status"] == "TIMEOUT"
    assert state["timed_out_at_utc"] is not None
