"""Authenticated public control API and committed SSE event stream."""

from __future__ import annotations

import asyncio
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from apps.contracts.base import CandidateId
from apps.contracts.control import (
    EvaluationResults,
    IncidentSnapshot,
    SafeStopRequest,
    WorldHealth,
)
from apps.contracts.lease import RepairReceipt
from apps.control_plane.orchestration import orchestrate_incident
from services.control_store import ControlStore

router = APIRouter(prefix="/api")


async def require_operator(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = request.app.state.settings.nightwatch_operator_token
    if not expected:
        raise HTTPException(status_code=503, detail="operator token is not configured")
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not supplied:
        raise HTTPException(status_code=401, detail="missing operator bearer token")
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="invalid operator bearer token")


def _store(request: Request) -> ControlStore:
    return request.app.state.control_store


def _not_found(label: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{label} not found")


async def _contain(request: Request, incident_id: str) -> IncidentSnapshot:
    store = _store(request)
    try:
        readback = await request.app.state.containment.ensure_safe_hold()
    except Exception as exc:
        reason = f"CONTAINMENT_FAILED: {type(exc).__name__}: {exc}"
        store.append_event(
            incident_id,
            "ESCALATED",
            {"reason": reason[:500]},
            state="ESCALATED",
            containment_verified=False,
            degraded_reason=reason[:512],
        )
        return store.get_snapshot(incident_id)

    store.append_event(
        incident_id,
        "SAFE_HOLD_SET",
        {
            "router_mode": readback.mode,
            "router_generation": str(readback.generation),
            "handler_sha256": readback.handler_hash,
            "readback": "verified",
        },
        state="SAFE_HOLD",
        containment_verified=True,
    )
    return store.get_snapshot(incident_id)


@router.post(
    "/incidents/{incident_id}/run",
    response_model=IncidentSnapshot,
    dependencies=[Depends(require_operator)],
)
async def run_incident(incident_id: str, request: Request) -> IncidentSnapshot:
    """Create one run, then contain and read back before orchestration."""
    snapshot, created = _store(request).begin_run(incident_id)
    if not created:
        return snapshot
    request.app.state.frames.register_run(snapshot.run_id)
    contained = await _contain(request, incident_id)
    if contained.state != "SAFE_HOLD" or not contained.containment_verified:
        return contained
    try:
        return await orchestrate_incident(request.app.state.orchestrator, contained)
    except Exception as exc:  # noqa: BLE001 - injected seams must also fail closed
        reason = f"ORCHESTRATION_ERROR:{type(exc).__name__}:{exc}"
        _store(request).append_event(
            incident_id,
            "ESCALATED",
            {"reason": reason[:500]},
            state="ESCALATED",
            degraded_reason=reason[:512],
        )
        return _store(request).get_snapshot(incident_id)


@router.post(
    "/incidents/{incident_id}/safe-stop",
    response_model=IncidentSnapshot,
    dependencies=[Depends(require_operator)],
)
async def safe_stop(
    incident_id: str, body: SafeStopRequest, request: Request
) -> IncidentSnapshot:
    store = _store(request)
    try:
        store.get_snapshot(incident_id)
    except KeyError as exc:
        raise _not_found("incident") from exc
    store.append_event(
        incident_id,
        "SAFE_STOP_REQUESTED",
        {"reason": body.reason},
    )
    return await _contain(request, incident_id)


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentSnapshot,
    dependencies=[Depends(require_operator)],
)
async def get_incident(incident_id: str, request: Request) -> IncidentSnapshot:
    try:
        return _store(request).get_snapshot(incident_id)
    except KeyError as exc:
        raise _not_found("incident") from exc


@router.get(
    "/incidents/{incident_id}/receipt",
    response_model=RepairReceipt,
    dependencies=[Depends(require_operator)],
)
async def get_receipt(incident_id: str, request: Request) -> RepairReceipt:
    try:
        return _store(request).get_receipt(incident_id)
    except KeyError as exc:
        raise _not_found("receipt") from exc


@router.get(
    "/runs/{run_id}/evaluations",
    response_model=EvaluationResults,
    dependencies=[Depends(require_operator)],
)
async def get_evaluations(run_id: str, request: Request) -> EvaluationResults:
    try:
        return _store(request).get_evaluations(run_id)
    except KeyError as exc:
        raise _not_found("evaluation results") from exc


@router.get(
    "/runs/{run_id}/frames/{candidate_id}/latest",
    dependencies=[Depends(require_operator)],
)
async def get_latest_frame(
    run_id: str,
    candidate_id: CandidateId,
    request: Request,
    after: Annotated[int | None, Query(ge=0)] = None,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> Response:
    """Return the newest trusted frame bytes without ever crossing run slots."""
    slot = request.app.state.frames.latest(run_id, candidate_id)
    if slot is None:
        raise _not_found("frame")
    frame, image = slot
    headers = {
        "Cache-Control": "no-store",
        "ETag": frame.image_sha256,
        "X-Frame-Seq": str(frame.frame_seq),
    }
    supplied_etag = (if_none_match or "").strip().removeprefix("W/").strip('"')
    if supplied_etag == frame.image_sha256 or (
        after is not None and frame.frame_seq <= after
    ):
        return Response(status_code=304, headers=headers)
    if not image:
        raise HTTPException(
            status_code=503,
            detail="frame metadata exists but image bytes are unavailable",
        )
    return Response(content=image, media_type=frame.image_mime, headers=headers)


@router.get(
    "/worlds/{world_id}/health",
    response_model=WorldHealth,
    dependencies=[Depends(require_operator)],
)
async def get_world_health(world_id: str, request: Request) -> WorldHealth:
    try:
        return _store(request).get_world_health(world_id)
    except KeyError as exc:
        raise _not_found("world") from exc


@router.get(
    "/incidents/{incident_id}/events",
    dependencies=[Depends(require_operator)],
)
async def incident_events(
    incident_id: str,
    request: Request,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    store = _store(request)
    try:
        # Validate both the incident and cursor before sending HTTP 200.
        store.list_events_after(incident_id, last_event_id)
    except KeyError as exc:
        raise _not_found("incident") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def stream():  # type: ignore[no-untyped-def]
        cursor = last_event_id
        idle_ticks = 0
        while not await request.is_disconnected():
            events = store.list_events_after(incident_id, cursor)
            if events:
                idle_ticks = 0
                for event in events:
                    # The DB transaction committed before list_events_after can
                    # return this row. SSE id and payload share the same model.
                    yield f"id: {event.event_id}\ndata: {event.model_dump_json()}\n\n"
                    cursor = event.event_id
            else:
                idle_ticks += 1
                if idle_ticks >= 60:  # 15 s keepalive at the 250 ms poll rate.
                    idle_ticks = 0
                    yield ": keepalive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )
