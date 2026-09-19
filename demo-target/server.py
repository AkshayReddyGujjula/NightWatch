"""Stage-safe NightWatch demo coordinator.

The deliberately vulnerable target state lives here, outside the trusted
NightWatch packages.  It watches the deployed append-only payment ledger,
records real Gemini output, launches three real Modal/CUA/Jev browser probes,
and preserves every completed run as a receipt under ``runtime/receipts``.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RUNTIME = HERE / "runtime"
FRAMES = RUNTIME / "frames"
RECEIPTS = RUNTIME / "receipts"
STATE_PATH = RUNTIME / "state.json"
STORE_URL = "https://jxzxl07-nightwatch-demo--nightwatch-live-store-asgi.modal.run"
PROVIDER_URL = "https://jxzxl07-nightwatch-demo--nightwatch-provider-asgi.modal.run"
SERVER_URL = "http://127.0.0.1:8765"


def _env() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _initial_state() -> dict[str, Any]:
    return {
        "run_id": None,
        "incident_type": None,
        "state": "READY",
        "headline": "Ready for a fresh demo",
        "updated_at": _now(),
        "security": {"armed": True, "health": 200, "label": "SCRIPTED_DEMO_TARGET"},
        "showcase": None,
        "gemini": None,
        "candidates": {},
        "winner": None,
        "fixed_checkout_url": None,
        "receipt_path": None,
        "degraded_reasons": [],
    }


class DemoFix(BaseModel):
    candidate_id: Literal["A", "B", "C"]
    name: str = Field(min_length=1, max_length=80)
    strategy: str = Field(min_length=1, max_length=400)
    expected_result: str = Field(min_length=1, max_length=300)
    risk: str = Field(min_length=1, max_length=250)


class DemoDiagnosis(BaseModel):
    incident_summary: str = Field(min_length=1, max_length=500)
    root_cause: str = Field(min_length=1, max_length=700)
    evidence: list[str] = Field(min_length=1, max_length=6)
    severity: Literal["medium", "high", "critical"]
    fixes: list[DemoFix] = Field(min_length=3, max_length=3)


app = FastAPI(title="NightWatch demo target coordinator")
_state: dict[str, Any] = _initial_state()
_state_lock = asyncio.Lock()
_pipeline_task: asyncio.Task[None] | None = None


def _persist() -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(_state, indent=2), encoding="utf-8")


async def _update(**values: Any) -> None:
    async with _state_lock:
        _state.update(values)
        _state["updated_at"] = _now()
        _persist()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _arm_double_charge() -> dict[str, Any]:
    token = _env().get("LIVE_INTERNAL_TOKEN", "")
    if not token:
        raise RuntimeError("LIVE_INTERNAL_TOKEN is missing")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{STORE_URL}/internal/demo/arm-double-charge", headers=_headers(token)
        )
        response.raise_for_status()
        return response.json()


async def _set_router(mode: str, *, setup: dict[str, Any] | None = None) -> dict[str, Any]:
    from apps.live_store.router import handler_hash_for

    token = _env().get("LIVE_INTERNAL_TOKEN", "")
    async with httpx.AsyncClient(timeout=30) as client:
        for attempt in range(3):
            current_response = await client.get(
                f"{STORE_URL}/internal/router", headers=_headers(token)
            )
            current_response.raise_for_status()
            current = current_response.json()
            body: dict[str, Any] = {
                "mode": mode,
                "expected_generation": current["generation"],
            }
            if mode == "SAFE":
                body.update(
                    {
                        "lease_id": f"lease-demo-{uuid.uuid4().hex[:10]}",
                        "lease_expires_at": (
                            datetime.now(UTC) + timedelta(minutes=30)
                        ).isoformat(),
                        "handler_sha256": handler_hash_for("SAFE"),
                    }
                )
            response = await client.put(
                f"{STORE_URL}/internal/router", headers=_headers(token), json=body
            )
            if response.status_code != 409 or attempt == 2:
                response.raise_for_status()
                return response.json()
            await asyncio.sleep(0.2)
    raise RuntimeError("router update exhausted retries")


async def _pipeline_guard(run_id: str, pipeline: Any) -> None:
    try:
        await pipeline
    except Exception as exc:  # noqa: BLE001 - never hide a stage failure
        if _state.get("run_id") == run_id:
            await _update(
                state="ESCALATED",
                headline="NightWatch stopped safely after an orchestration failure",
                degraded_reasons=[
                    *list(_state.get("degraded_reasons") or []),
                    f"PIPELINE_ERROR:{type(exc).__name__}:{exc}",
                ],
            )


async def _diagnose(kind: str, evidence: dict[str, Any]) -> DemoDiagnosis:
    values = _env()
    key = values.get("GOOGLE_API_KEY", "")
    model = values.get("GEMINI_MODEL", "")
    if not key or not model:
        raise RuntimeError("Gemini key/model is missing")
    prompt = (
        "You are NightWatch's incident diagnostician. Use only the supplied trusted demo "
        "evidence. Identify the concrete fault and return exactly three fixes with candidate "
        "ids A, B and C, in that order. A is rollback, B is the prepared safe handler, C is a "
        "bounded generated patch. Do not claim a fix was applied or tested. For a security "
        "demo, state clearly that the injected target failure is scripted and isolated.\n\n"
        + json.dumps({"incident_type": kind, "trusted_evidence": evidence})
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": DemoDiagnosis.model_json_schema(),
        },
    }
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(url, params={"key": key}, json=body)
    response.raise_for_status()
    payload = response.json()
    raw = payload["candidates"][0]["content"]["parts"][0]["text"]
    diagnosis = DemoDiagnosis.model_validate_json(raw)
    if [fix.candidate_id for fix in diagnosis.fixes] != ["A", "B", "C"]:
        raise ValueError("Gemini did not return ordered A/B/C fixes")
    return diagnosis


def _candidate_template(candidate_id: str) -> dict[str, Any]:
    names = {"A": "Rollback", "B": "Prepared safe handler", "C": "Gemini patch"}
    return {
        "candidate_id": candidate_id,
        "name": names[candidate_id],
        "status": "QUEUED",
        "sandbox_id": None,
        "frame_seq": None,
        "jev_action": None,
        "browser_verdict": None,
        "label": "REAL_MODAL_CUA_JEV_BROWSER_VALIDATION",
    }


async def _run_candidate(candidate_id: str, run_id: str) -> int:
    # Modal rate-limits simultaneous ephemeral app creation. A two-second
    # launch offset avoids that burst while the long-running sandbox sessions
    # still overlap, which is the concurrency the dashboard demonstrates.
    await asyncio.sleep({"A": 0, "B": 2, "C": 4}[candidate_id])
    log_dir = RUNTIME / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{run_id}-{candidate_id}.log"
    command = [
        "uv",
        "run",
        "modal",
        "run",
        "-e",
        "nightwatch-demo",
        "scripts/probe_browser_type.py",
        "--candidate-id",
        candidate_id,
        "--run-id",
        run_id,
        "--demo-server-url",
        SERVER_URL,
    ]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    with log_path.open("wb") as log:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        return await process.wait()


async def _run_race(run_id: str) -> dict[str, int]:
    await _update(state="RACING", headline="Three real Modal/CUA/Jev browser worlds are live")
    results = await asyncio.gather(*(_run_candidate(cid, run_id) for cid in ("A", "B", "C")))
    return dict(zip(("A", "B", "C"), results, strict=True))


async def _finish_repair(run_id: str, process_codes: dict[str, int]) -> None:
    # A/C remain evidence options. The prepared safe handler is selected only
    # after an actual reversible activation and a fresh browser checkout is armed.
    if process_codes.get("B") != 0:
        await _update(
            state="ESCALATED",
            headline="Safe candidate B failed live browser validation; no fix activated",
            degraded_reasons=[
                *list(_state.get("degraded_reasons") or []),
                f"CANDIDATE_B_EXIT:{process_codes.get('B')}",
            ],
        )
        return
    async with _state_lock:
        for candidate_id, code in process_codes.items():
            candidate = _state.get("candidates", {}).get(candidate_id)
            if code != 0 and candidate and candidate.get("status") != "FAILED":
                candidate.update(
                    status="FAILED",
                    browser_verdict="INFRA_FAIL",
                    jev_action="Modal launcher ended before a validated frame",
                )
        _persist()
    setup = await _arm_double_charge()
    await _set_router("SAFE_HOLD", setup=setup)
    readback = await _set_router("SAFE", setup=setup)
    receipt = {
        "run_id": run_id,
        "incident_type": _state["incident_type"],
        "detected_evidence": _state.get("showcase"),
        "gemini": _state.get("gemini"),
        "candidate_process_exit_codes": process_codes,
        "winner": "B",
        "activation_readback": readback,
        "fixed_checkout_url": setup["checkout_x_url"],
        "fixed_namespace": setup["namespace"],
        "fixed_intent_id": setup["intent_id"],
        "security_label": _state.get("security"),
        "created_at": _now(),
    }
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    receipt_path = RECEIPTS / f"{run_id}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    await _update(
        state="FIXED",
        headline="Candidate B activated under a 30-minute lease",
        winner="B",
        fixed_checkout_url=setup["checkout_x_url"],
        receipt_path=str(receipt_path),
        security={"armed": False, "health": 200, "label": "SCRIPTED_DEMO_TARGET"},
    )


async def _payment_pipeline(run_id: str, setup: dict[str, Any]) -> None:
    token = _env().get("EVALUATOR_TOKEN", "")
    while _state.get("run_id") == run_id:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{PROVIDER_URL}/internal/ledger/{setup['namespace']}",
                headers=_headers(token),
            )
        if response.status_code == 200 and len(response.json().get("captures", [])) >= 2:
            ledger = response.json()
            break
        await asyncio.sleep(0.4)
    else:
        return
    captures = ledger["captures"]
    evidence = {
        "namespace": ledger["namespace"],
        "operation_id": setup["operation_id"],
        "capture_ids": [row["capture_id"] for row in captures],
        "idempotency_keys": [row["idempotency_key"] for row in captures],
        "ledger_digest": ledger["digest"],
        "symptom": "one £79.99 order produced two £79.99 captures while the store said PAID",
    }
    await _update(
        state="DETECTED",
        headline="Duplicate capture incident detected",
        showcase=evidence,
    )
    await _set_router("SAFE_HOLD")
    try:
        diagnosis = await _diagnose("DOUBLE_CHARGE", evidence)
        await _update(state="DIAGNOSED", gemini=diagnosis.model_dump())
    except Exception as exc:  # noqa: BLE001 - explicitly labelled degradation
        await _update(degraded_reasons=[f"GEMINI_ERROR:{type(exc).__name__}:{exc}"])
    codes = await _run_race(run_id)
    await _finish_repair(run_id, codes)


async def _cyber_pipeline(run_id: str) -> None:
    evidence = {
        "scripted": True,
        "target": "demo-target health endpoint",
        "observed_health_status": 503,
        "symptom": "isolated demo target refuses health checks and checkout traffic",
    }
    await _update(
        state="DETECTED",
        headline="SECURITY INCIDENT — SCRIPTED target crash",
        showcase=evidence,
    )
    try:
        diagnosis = await _diagnose("SCRIPTED_SECURITY_CRASH", evidence)
        await _update(state="DIAGNOSED", gemini=diagnosis.model_dump())
    except Exception as exc:  # noqa: BLE001
        await _update(degraded_reasons=[f"GEMINI_ERROR:{type(exc).__name__}:{exc}"])
    codes = await _run_race(run_id)
    await _finish_repair(run_id, codes)


@app.on_event("startup")
async def startup() -> None:
    global _state
    RUNTIME.mkdir(parents=True, exist_ok=True)
    FRAMES.mkdir(parents=True, exist_ok=True)
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    if STATE_PATH.exists():
        try:
            _state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except ValueError:
            _state = _initial_state()
    _persist()


@app.get("/")
async def dashboard() -> FileResponse:
    return FileResponse(HERE / "dashboard.html", headers={"Cache-Control": "no-store"})


@app.get("/api/state")
async def state() -> Response:
    return Response(
        json.dumps(_state), media_type="application/json", headers={"Cache-Control": "no-store"}
    )


@app.get("/api/frames/{candidate_id}")
async def frame(candidate_id: str) -> FileResponse:
    path = FRAMES / f"{candidate_id}.png"
    if not path.is_file():
        raise HTTPException(404, "no real frame received yet")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.post("/api/candidates/{candidate_id}/frame")
async def candidate_frame(
    candidate_id: str,
    request: Request,
    metadata: Annotated[str, Form()],
    image: Annotated[UploadFile, File()],
) -> dict[str, bool]:
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "local demo updates only")
    details = json.loads(metadata)
    payload = await image.read()
    (FRAMES / f"{candidate_id}.png").write_bytes(payload)
    async with _state_lock:
        candidate = _state.setdefault("candidates", {}).setdefault(
            candidate_id, _candidate_template(candidate_id)
        )
        candidate.update(details)
        candidate["status"] = "LIVE"
        _state["updated_at"] = _now()
        _persist()
    return {"accepted": True}


@app.post("/api/candidates/{candidate_id}/status")
async def candidate_status(candidate_id: str, request: Request) -> dict[str, bool]:
    if request.client is None or request.client.host not in {"127.0.0.1", "::1"}:
        raise HTTPException(403, "local demo updates only")
    details = await request.json()
    async with _state_lock:
        candidate = _state.setdefault("candidates", {}).setdefault(
            candidate_id, _candidate_template(candidate_id)
        )
        candidate.update(details)
        _state["updated_at"] = _now()
        _persist()
    return {"accepted": True}


@app.post("/api/arm/demo")
async def arm_demo() -> dict[str, Any]:
    global _pipeline_task
    if _pipeline_task is not None and not _pipeline_task.done():
        raise HTTPException(409, "a demo pipeline is already running")
    setup = await _arm_double_charge()
    run_id = f"payment-{datetime.now(UTC).strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"
    await _update(
        run_id=run_id,
        incident_type="DOUBLE_CHARGE",
        state="ARMED",
        headline="Vulnerable checkout armed — waiting for the real payment",
        showcase={"namespace": setup["namespace"], "intent_id": setup["intent_id"]},
        gemini=None,
        candidates={cid: _candidate_template(cid) for cid in ("A", "B", "C")},
        winner=None,
        fixed_checkout_url=None,
        receipt_path=None,
        degraded_reasons=[],
    )
    _pipeline_task = asyncio.create_task(
        _pipeline_guard(run_id, _payment_pipeline(run_id, setup))
    )
    return {"run_id": run_id, "checkout_url": setup["checkout_x_url"], "dashboard_url": SERVER_URL}


@app.post("/api/arm/cyber")
async def arm_cyber() -> dict[str, Any]:
    global _pipeline_task
    if _pipeline_task is not None and not _pipeline_task.done():
        raise HTTPException(409, "a demo pipeline is already running")
    run_id = f"security-{datetime.now(UTC).strftime('%H%M%S')}-{uuid.uuid4().hex[:6]}"
    await _update(
        run_id=run_id,
        incident_type="SCRIPTED_SECURITY_CRASH",
        state="ARMED",
        headline="Injecting SCRIPTED isolated target crash",
        security={"armed": True, "health": 503, "label": "SCRIPTED_DEMO_TARGET"},
        showcase=None,
        gemini=None,
        candidates={cid: _candidate_template(cid) for cid in ("A", "B", "C")},
        winner=None,
        fixed_checkout_url=None,
        receipt_path=None,
        degraded_reasons=[],
    )
    _pipeline_task = asyncio.create_task(_pipeline_guard(run_id, _cyber_pipeline(run_id)))
    return {"run_id": run_id, "dashboard_url": SERVER_URL}


@app.post("/api/reset")
async def reset() -> dict[str, Any]:
    global _state
    if _pipeline_task is not None and not _pipeline_task.done():
        raise HTTPException(409, "wait for the active run before resetting")
    token = _env().get("LIVE_INTERNAL_TOKEN", "")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(f"{STORE_URL}/internal/reset", headers=_headers(token))
        response.raise_for_status()
    setup = await _arm_double_charge()
    async with _state_lock:
        _state = _initial_state()
        _state.update(
            {
                "state": "RESET_COMPLETE",
                "headline": "Both demo vulnerabilities restored for a fresh run",
                "showcase": {
                    "payment": "DOUBLE_CHARGE_ARMED",
                    "security": "SCRIPTED_CRASH_ARMED",
                    "checkout_url": setup["checkout_x_url"],
                },
            }
        )
        _persist()
    return {"reset": True, "checkout_url": setup["checkout_x_url"], "receipts_preserved": True}


@app.get("/target/health")
async def target_health() -> Response:
    status = int(_state.get("security", {}).get("health", 200))
    return Response(
        json.dumps({"status": "ok" if status == 200 else "crashed", "scripted": True}),
        status_code=status,
        media_type="application/json",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
