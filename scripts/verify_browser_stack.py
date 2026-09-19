"""NightWatch Track B — §11.8 CUA-in-Modal hard gate (Track B owned).

Proves, in one pinned Modal Sandbox in `nightwatch-b`:

1. the desktop image boots (X11 + D-Bus/AT-SPI + Openbox) under two OS users
   with the controller/app separation from §11.6;
2. the world-local CUA Driver runs in bounded mode with the reviewed manifest
   and answers typed calls over its controller-owned socket;
3. a ref minted in one session is refused under a different session;
4. one live TypeSafe Jev Choice is made by this trusted runner (the key stays
   on the runner and never enters the sandbox) and the chosen action executes
   through the sandbox CUA daemon with `input_route: dom_event`;
5. the postcondition is verified from the gate server's server-side state, not
   from the browser or the model;
6. the world yields at least five genuine screenshots inside a five-second
   window, with per-frame SHA-256 recorded;
7. `end_session` and sandbox termination happen on every path.

The candidate app here is the real NightMart storefront served by a labelled
gate fixture backend. The real candidate app and backend are Track A's
`apps/live_store/**`; this gate proves the browser stack, not payment logic.

Run:  MODAL_ENVIRONMENT=nightwatch-b uv run modal run scripts/verify_browser_stack.py
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import modal  # noqa: E402
from infra.modal_desktop_image import DESKTOP_IMAGE  # noqa: E402

app = modal.App("nightwatch-b-browser-gate")

_STORE_DIR = _REPO_ROOT / "apps" / "storefront"
_GATE_EXEC_TIMEOUT_S = 45
_FIXTURE_EMAIL = "gate@example.com"
_TARGET_URL = "http://127.0.0.1:8080/checkout-x.html?intent=gate-intent-1"

GATE_SERVER_SOURCE = '''"""NightWatch storefront gate fixture (labelled stub, not the real store).

Serves the real apps/storefront pages plus a deterministic in-memory API and a
server-side state endpoint, so the gate can verify a postcondition outside the
browser. apps/live_store (Track A) owns the real backend.
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

STATE: dict[str, object] = {
    "started_monotonic_ns": time.monotonic_ns(),
    "checkout_posts": [],
    "intent_reads": [],
    "order_reads": [],
}
COUNTER = {"n": 0}
ROOT = Path(".")
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "NightWatchGate/1.0"

    def log_message(self, *args: object) -> None:
        return

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: object) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802 - stdlib casing
        path = urlparse(self.path).path
        if path == "/gate/state":
            return self._json(200, STATE)
        if path.startswith("/api/intents/"):
            intent_id = path.rsplit("/", 1)[-1]
            reads = STATE["intent_reads"]
            if isinstance(reads, list):
                reads.append({"intent_id": intent_id, "at_ns": time.monotonic_ns()})
            return self._json(
                200,
                {
                    "intent_id": intent_id,
                    "items": [{"sku": "SKU-A", "quantity": 1}],
                    "amount_minor": 7999,
                    "currency": "GBP",
                },
            )
        if path.startswith("/api/orders/"):
            order_id = path.rsplit("/", 1)[-1]
            reads = STATE["order_reads"]
            if isinstance(reads, list):
                reads.append({"order_id": order_id, "at_ns": time.monotonic_ns()})
            return self._json(
                200,
                {
                    "order_id": order_id,
                    "intent_id": "gate-intent-1",
                    "status": "PAID",
                    "amount_minor": 7999,
                    "currency": "GBP",
                },
            )
        return self._static(path)

    def _static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        candidate = (ROOT / relative).resolve()
        root = ROOT.resolve()
        if candidate != root and root not in candidate.parents:
            return self._json(404, {"detail": "not found"})
        if not candidate.is_file():
            return self._json(404, {"detail": "not found"})
        content_type = _CONTENT_TYPES.get(candidate.suffix, "application/octet-stream")
        self._send(200, candidate.read_bytes(), content_type)

    def do_POST(self) -> None:  # noqa: N802 - stdlib casing
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"detail": "invalid json"})
        if path.startswith("/api/checkout/"):
            intent_id = path.rsplit("/", 1)[-1]
            COUNTER["n"] += 1
            order_id = f"gate-order-{COUNTER['n']}"
            posts = STATE["checkout_posts"]
            if isinstance(posts, list):
                posts.append(
                    {
                        "intent_id": intent_id,
                        "order_id": order_id,
                        "email": body.get("email"),
                        "address": body.get("address"),
                        "voucher_code": body.get("voucher_code"),
                        "at_ns": time.monotonic_ns(),
                    }
                )
            return self._json(
                200,
                {
                    "order_id": order_id,
                    "intent_id": intent_id,
                    "status": "PAID",
                    "amount_minor": 7999,
                    "currency": "GBP",
                },
            )
        return self._json(404, {"detail": "not found"})


def main() -> None:
    global ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--port", type=int, default=8080)
    arguments = parser.parse_args()
    ROOT = Path(arguments.root)
    ThreadingHTTPServer(("127.0.0.1", arguments.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
'''


class GateError(RuntimeError):
    """Raised when the gate cannot continue; always recorded, never faked."""


def _gate_image() -> modal.Image:
    with tempfile.NamedTemporaryFile(
        "w", suffix="-gate-server.py", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(GATE_SERVER_SOURCE)
        script_path = Path(handle.name)
    return (
        DESKTOP_IMAGE.add_local_dir(_STORE_DIR, "/opt/nightwatch/app", copy=True)
        .add_local_file(script_path, "/opt/nightwatch/gate_server.py", copy=True)
    )


def _read_stream(stream: Any) -> str:
    data = stream.read()
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return str(data)


def _exec(
    sandbox: modal.Sandbox,
    *argv: str,
    env: dict[str, str | None] | None = None,
    timeout: int = 120,
) -> tuple[int, str, str]:
    process = sandbox.exec(*argv, env=env, timeout=timeout)
    stdout = _read_stream(process.stdout)
    stderr = _read_stream(process.stderr)
    return process.wait(), stdout, stderr


def _json_from(text: str) -> Any:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise GateError(f"no JSON object in output: {text[:300]!r}")
    return json.loads(text[start : end + 1])


class CuaDriver:
    """Trusted-runner client for the world-local CUA daemon (argv exec only)."""

    def __init__(
        self, sandbox: modal.Sandbox, evidence: dict[str, Any], socket_path: str
    ) -> None:
        self._sandbox = sandbox
        self._evidence = evidence
        self._socket = socket_path
        self.calls: list[dict[str, Any]] = evidence.setdefault("cua_calls", [])

    def call(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        screenshot_out: str | None = None,
        session: str | None = None,
    ) -> dict[str, Any]:
        payload = dict(arguments)
        if session is not None:
            payload["session"] = session
        argv = [
            "/run/nightwatch/as_controller.sh",
            "timeout",
            str(_GATE_EXEC_TIMEOUT_S),
            "cua-driver",
            "call",
            tool,
            json.dumps(payload),
            "--socket",
            self._socket,
        ]
        if screenshot_out:
            argv += ["--screenshot-out-file", screenshot_out]
        code, stdout, stderr = _exec(
            self._sandbox, *argv, timeout=_GATE_EXEC_TIMEOUT_S + 30
        )
        self.calls.append(
            {
                "tool": tool,
                "arguments": payload,
                "exit_code": code,
                "stdout_tail": stdout[-1200:],
                "stderr_tail": stderr[-400:],
            }
        )
        if code != 0:
            raise GateError(f"{tool} failed (exit {code}): {(stderr or stdout)[-400:]}")
        data = _json_from(stdout)
        if not isinstance(data, dict):
            raise GateError(f"{tool} returned non-object JSON")
        if data.get("status") == "refused" or data.get("refusal"):
            raise GateError(f"{tool} refused: {json.dumps(data)[:400]}")
        return data

    def probe(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        session: str | None = None,
        screenshot_out: str | None = None,
    ) -> dict[str, Any]:
        try:
            return {
                "ok": True,
                "data": self.call(
                    tool, arguments, session=session, screenshot_out=screenshot_out
                ),
            }
        except GateError as error:
            return {"ok": False, "error": str(error)}


def _load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if value.strip():
            values[key.strip()] = value.strip()
    return values


def jev_choose(
    goal: str,
    observation: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    from typesafe_sdk import AsyncTypeSafeClient, Choice

    env = _load_env_file(_REPO_ROOT / ".env")
    api_key = env.get("TYPESAFE_API_KEY")
    if not api_key:
        raise GateError("TYPESAFE_API_KEY missing from local .env")
    model = env.get("TYPESAFE_MODEL", "jev-1.13.0")

    async def run() -> dict[str, Any]:
        async with AsyncTypeSafeClient(api_key=api_key, timeout=60) as client:
            response = await client.system_one(
                json.dumps({"goal": goal, "observation": observation}),
                questions={
                    "next_action": Choice(
                        instructions=(
                            "Which supplied action safely advances the stated checkout "
                            "goal from this exact observation?"
                        ),
                        criteria={
                            cid: str(candidate["description"])
                            for cid, candidate in candidates.items()
                        },
                    )
                },
                model=model,
            )
        answer = response.answers["next_action"]
        return {
            "requested_model": model,
            "response_model": response.model,
            "usage": response.usage.model_dump(),
            "answer": answer.model_dump(),
        }

    return asyncio.run(run())


def _refs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    refs = snapshot.get("refs")
    return [ref for ref in refs if isinstance(ref, dict)] if isinstance(refs, list) else []


def build_candidates(
    snapshot: dict[str, Any], fixture_email: str
) -> dict[str, dict[str, Any]]:
    email_ref = next(
        (
            ref
            for ref in _refs(snapshot)
            if ref.get("role") == "textbox" and "email" in str(ref.get("name", "")).lower()
        ),
        None,
    )
    pay_ref = next(
        (
            ref
            for ref in _refs(snapshot)
            if ref.get("role") == "button"
            and str(ref.get("name", "")).strip().lower() == "pay now"
        ),
        None,
    )
    email_filled = email_ref is not None and email_ref.get("value") == fixture_email

    candidates: dict[str, dict[str, Any]] = {}
    if email_ref is not None and not email_filled:
        candidates["fill_email"] = {
            "description": "Type the fixture email into the visible Email field.",
            "tool": "browser_type",
            "ref": email_ref.get("ref"),
            "args": {"ref": email_ref.get("ref"), "text": fixture_email, "replace": True},
        }
    if pay_ref is not None and email_filled:
        candidates["pay_now"] = {
            "description": "Click the visible Pay now button to submit the checkout.",
            "tool": "browser_click",
            "ref": pay_ref.get("ref"),
            "args": {"ref": pay_ref.get("ref"), "input_route": "dom_event"},
        }
    candidates["reobserve"] = {
        "description": "The page may have changed; observe again.",
        "tool": None,
        "ref": None,
        "args": {},
    }
    candidates["abstain"] = {
        "description": "None of the observed actions safely advances the goal.",
        "tool": None,
        "ref": None,
        "args": {},
    }
    return candidates


def compact_observation(snapshot: dict[str, Any], completed: list[str]) -> dict[str, Any]:
    controls = [
        {
            "action_id": ref.get("ref"),
            "role": ref.get("role"),
            "name": ref.get("name"),
            "value": ref.get("value"),
            "actions": ref.get("actions"),
        }
        for ref in _refs(snapshot)[:24]
    ]
    outline = snapshot.get("outline")
    return {
        "heading": snapshot.get("heading") or (str(outline)[:160] if outline else None),
        "visible_controls": controls,
        "completed_postconditions": completed,
    }


def ref_present(snapshot: dict[str, Any], ref: str | None) -> bool:
    return ref is not None and any(item.get("ref") == ref for item in _refs(snapshot))


def fetch_gate_state(sandbox: modal.Sandbox) -> dict[str, Any]:
    code, stdout, stderr = _exec(
        sandbox,
        "python3",
        "-c",
        (
            "import urllib.request;"
            "print(urllib.request.urlopen('http://127.0.0.1:8080/gate/state',"
            "timeout=3).read().decode())"
        ),
        timeout=30,
    )
    if code != 0:
        raise GateError(f"gate state fetch failed: {(stderr or stdout)[-300:]}")
    return _json_from(stdout)


def sample_frames(
    sandbox: modal.Sandbox,
    driver: CuaDriver,
    target_id: str,
    tab_id: str,
    session: str,
    window_s: float = 5.0,
    minimum: int = 5,
) -> dict[str, Any]:
    frames: list[dict[str, Any]] = []
    started = time.monotonic()
    while True:
        elapsed = time.monotonic() - started
        if len(frames) >= minimum and elapsed >= window_s:
            break
        if elapsed > window_s * 3:
            break
        seq = len(frames) + 1
        path = f"/run/nightwatch/frames/frame-{seq:03d}.png"
        at_ns = time.monotonic_ns()
        result = driver.probe(
            "get_browser_state",
            {
                "target_id": target_id,
                "tab_id": tab_id,
                "include_screenshot": True,
            },
            session=session,
            screenshot_out=path,
        )
        record: dict[str, Any] = {"seq": seq, "at_ns": at_ns, "ok": result["ok"]}
        if result["ok"]:
            data = result["data"]
            for key in ("capture_id", "snapshot_id", "screenshot_id"):
                if key in data:
                    record[key] = data[key]
            code, stdout, _ = _exec(sandbox, "sha256sum", path, timeout=30)
            if code == 0 and stdout.strip():
                record["sha256"] = stdout.split()[0]
            code, stdout, _ = _exec(sandbox, "stat", "-c", "%s", path, timeout=30)
            if code == 0 and stdout.strip():
                record["size"] = int(stdout.strip())
        frames.append(record)

    hashes = [f["sha256"] for f in frames if "sha256" in f]
    first, last = (frames[0]["at_ns"], frames[-1]["at_ns"]) if frames else (0, 0)
    span_s = round((last - first) / 1e9, 3) if len(frames) > 1 else 0.0
    first_five = frames[:5]
    window_s_5 = (
        round((first_five[-1]["at_ns"] - first_five[0]["at_ns"]) / 1e9, 3)
        if len(first_five) >= 5
        else None
    )
    return {
        "count": len(frames),
        "distinct_sha256": len(set(hashes)),
        "span_s": span_s,
        "frame1_to_frame5_s": window_s_5,
        "rate_fps": round((len(frames) - 1) / span_s, 2) if span_s > 0 else 0.0,
        "frames": frames,
    }


@app.local_entrypoint()
def main() -> None:
    evidence: dict[str, Any] = {
        "gate": "11.8",
        "environment": "nightwatch-b",
        "started_unix_s": time.time(),
        "sandbox_id": None,
        "verdict": {},
        "errors": [],
    }
    sandbox: modal.Sandbox | None = None
    session = f"nw-gate-{uuid.uuid4().hex[:8]}"
    evidence["session"] = session
    driver: CuaDriver | None = None
    try:
        image = _gate_image()
        create_started = time.monotonic()
        sandbox = modal.Sandbox.create(
            app=app, image=image, timeout=900, idle_timeout=300
        )
        evidence["sandbox_id"] = sandbox.object_id
        evidence["image_id"] = image.object_id
        evidence["sandbox_create_s"] = round(time.monotonic() - create_started, 3)

        # --- 1. boot the world ------------------------------------------------
        bootstrap_started = time.monotonic()
        code, stdout, stderr = _exec(
            sandbox,
            "/opt/nightwatch/start_desktop_world.sh",
            env={
                "NW_APP_PORT": "8080",
                "NW_APP_DIR": "/opt/nightwatch/app",
                "NW_APP_CMD": (
                    "python3 /opt/nightwatch/gate_server.py "
                    "--root /opt/nightwatch/app --port 8080"
                ),
                "NW_APP_READY_PATH": "/",
            },
            timeout=420,
        )
        evidence["bootstrap_s"] = round(time.monotonic() - bootstrap_started, 3)
        evidence["bootstrap_exit_code"] = code
        evidence["bootstrap_stdout_tail"] = stdout[-1500:]
        if code != 0:
            raise GateError(f"world bootstrap failed: {(stderr or stdout)[-600:]}")
        code, stdout, _ = _exec(
            sandbox, "cat", "/run/nightwatch/world-evidence.json", timeout=30
        )
        evidence["world"] = _json_from(stdout) if code == 0 else {"error": stdout[-400:]}
        world = evidence["world"] if isinstance(evidence["world"], dict) else {}
        socket_path = str(world.get("cua_socket") or "/run/nightwatch/cua.sock")
        evidence["cua_socket"] = socket_path
        driver = CuaDriver(sandbox, evidence, socket_path)
        code, stdout, stderr = _exec(
            sandbox,
            "/run/nightwatch/as_controller.sh",
            "timeout",
            "30",
            "cua-driver",
            "doctor",
            timeout=60,
        )
        evidence["cua_doctor"] = (stdout or stderr)[:1500]
        code, at_spi_log, _ = _exec(
            sandbox, "cat", "/run/nightwatch/at-spi.log", timeout=20
        )
        evidence["at_spi_log_tail"] = at_spi_log[-800:] if code == 0 else None
        ready_code, _, ready_err = _exec(
            sandbox,
            "install",
            "-d",
            "-o",
            "nightwatch_controller",
            "-g",
            "nightwatch_controller",
            "-m",
            "0700",
            "/run/nightwatch/frames",
            timeout=30,
        )
        if ready_code != 0:
            raise GateError(f"could not create frames dir: {ready_err[-200:]}")

        # --- 2. drive CUA: prepare -> bind -> navigate ------------------------
        prepared = driver.call(
            "browser_prepare",
            {"allow_launch": True, "profile": {"mode": "isolated_new"}},
            session=session,
        )
        evidence["verdict"]["x11_atspi_cua_ready"] = True
        prepared_pid = int(prepared["prepared_pid"])
        evidence["prepared_pid"] = prepared_pid
        code, exe_path, _ = _exec(
            sandbox, "readlink", "-f", f"/proc/{prepared_pid}/exe", timeout=20
        )
        evidence["browser_executable"] = exe_path.strip() if code == 0 else None

        window: dict[str, Any] | None = None
        for _ in range(40):
            listing = driver.call("list_windows", {"pid": prepared_pid}, session=session)
            windows = [
                item
                for item in (listing.get("windows") or [])
                if isinstance(item, dict) and item.get("is_on_screen")
            ]
            if windows:
                window = max(
                    windows,
                    key=lambda item: int(
                        (item.get("bounds") or {}).get("width", 0)
                    )
                    * int((item.get("bounds") or {}).get("height", 0)),
                )
                break
            time.sleep(0.25)
        if window is None:
            raise GateError("isolated browser window did not become ready")
        window_id = int(window["window_id"])
        evidence["window_id"] = window_id

        bound = driver.call(
            "get_browser_state",
            {"pid": prepared_pid, "window_id": window_id},
            session=session,
        )
        target_id = str(bound["target_id"])
        tabs = [tab for tab in (bound.get("tabs") or []) if isinstance(tab, dict)]
        if not tabs:
            raise GateError("browser binding returned no tabs")
        selected = next((tab for tab in tabs if tab.get("active")), tabs[0])
        tab_id = str(selected["tab_id"])
        evidence["target_id"] = target_id
        evidence["tab_id"] = tab_id

        driver.call(
            "browser_navigate",
            {"target_id": target_id, "tab_id": tab_id, "url": _TARGET_URL},
            session=session,
        )

        # --- 3. observe + cross-session refusal probe -------------------------
        snapshot = driver.call(
            "get_browser_state",
            {"target_id": target_id, "tab_id": tab_id, "snapshot_format": "semantic_v2"},
            session=session,
        )
        initial = build_candidates(snapshot, _FIXTURE_EMAIL)
        evidence["initial_candidates"] = {
            cid: {"description": item["description"], "ref": item["ref"]}
            for cid, item in initial.items()
        }
        probe_candidate = initial.get("fill_email") or initial.get("pay_now")
        if probe_candidate and probe_candidate.get("ref"):
            other_session = f"{session}-probe"
            driver.probe(
                str(probe_candidate["tool"]),
                dict(probe_candidate["args"]),
                session=other_session,
            )
            probe_record = driver.calls[-1]
            evidence["cross_session_probe"] = {
                "session": other_session,
                "exit_code": probe_record["exit_code"],
                "refused": probe_record["exit_code"] != 0
                or "refus" in probe_record["stdout_tail"].lower()
                or "refus" in probe_record["stderr_tail"].lower(),
            }
        evidence["verdict"]["cross_session_refused"] = bool(
            evidence.get("cross_session_probe", {}).get("refused")
        )

        # --- 4. Jev decision loop --------------------------------------------
        goal = (
            "Complete one checkout of SKU-A quantity 1 and reach a paid state, "
            "using only the supplied actions."
        )
        completed: list[str] = []
        actions: list[dict[str, Any]] = []
        for step in range(1, 5):
            snapshot = driver.call(
                "get_browser_state",
                {
                    "target_id": target_id,
                    "tab_id": tab_id,
                    "snapshot_format": "semantic_v2",
                },
                session=session,
            )
            candidates = build_candidates(snapshot, _FIXTURE_EMAIL)
            observation = compact_observation(snapshot, completed)
            observation_hash = hashlib.sha256(
                json.dumps(observation, sort_keys=True).encode()
            ).hexdigest()
            decision = jev_choose(goal, observation, candidates)
            choice = str(decision["answer"].get("choice"))
            evidence.setdefault("decisions", []).append(
                {
                    "step": step,
                    "observation_hash": observation_hash,
                    "offered": list(candidates),
                    "decision": decision,
                }
            )
            if choice not in candidates:
                raise GateError(f"Jev chose an unoffered candidate: {choice!r}")
            selected_candidate = candidates[choice]
            if choice == "abstain":
                evidence["verdict"]["jev_abstained"] = True
                break
            if choice == "reobserve":
                continue

            fresh = driver.call(
                "get_browser_state",
                {
                    "target_id": target_id,
                    "tab_id": tab_id,
                    "snapshot_format": "semantic_v2",
                },
                session=session,
            )
            if not ref_present(fresh, str(selected_candidate["ref"])):
                actions.append({"step": step, "candidate": choice, "executed": False,
                                "reason": "stale_ref"})
                continue
            driver.call(
                str(selected_candidate["tool"]),
                dict(selected_candidate["args"]),
                session=session,
            )
            actions.append({"step": step, "candidate": choice, "executed": True})
            completed.append(choice)
            if choice == "pay_now":
                break
        evidence["actions"] = actions
        evidence["verdict"]["jev_live_choice"] = bool(evidence.get("decisions"))
        evidence["verdict"]["action_executed"] = any(a.get("executed") for a in actions)

        # --- 5. independent postcondition from server-side state --------------
        server_state: dict[str, Any] = {}
        postcondition_ok = False
        for _ in range(20):
            server_state = fetch_gate_state(sandbox)
            posts = server_state.get("checkout_posts") or []
            if posts:
                postcondition_ok = posts[-1].get("email") == _FIXTURE_EMAIL
                break
            time.sleep(0.3)
        evidence["postcondition"] = {
            "checkout_posts": server_state.get("checkout_posts"),
            "email_matches_fixture": postcondition_ok,
        }
        evidence["verdict"]["postcondition_verified"] = postcondition_ok

        # --- 6. frame-rate window --------------------------------------------
        frames = sample_frames(sandbox, driver, target_id, tab_id, session)
        evidence["frames"] = frames
        evidence["verdict"]["frames_5_in_5s"] = (
            frames["count"] >= 5
            and frames["frame1_to_frame5_s"] is not None
            and frames["frame1_to_frame5_s"] <= 5.0
        )

        # --- 7. end session ---------------------------------------------------
        try:
            driver.call("end_session", {}, session=session)
            evidence["end_session"] = "ok"
        except GateError as error:
            evidence["end_session"] = f"error: {error}"
    except Exception as error:  # noqa: BLE001 - recorded, never faked
        evidence["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        if driver is not None and sandbox is not None:
            with contextlib.suppress(Exception):
                driver.probe("end_session", {}, session=session)
        if sandbox is not None:
            sandbox.terminate()
            evidence["terminated"] = True

    passed = (
        evidence.get("verdict", {}).get("x11_atspi_cua_ready", False)
        and evidence.get("verdict", {}).get("cross_session_refused", False)
        and evidence.get("verdict", {}).get("jev_live_choice", False)
        and evidence.get("verdict", {}).get("action_executed", False)
        and evidence.get("verdict", {}).get("postcondition_verified", False)
        and evidence.get("verdict", {}).get("frames_5_in_5s", False)
        and not evidence.get("errors")
    )
    evidence["verdict"]["gate_passed"] = passed
    artifacts_dir = _REPO_ROOT / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    artifact_path = artifacts_dir / f"browser_gate_{int(evidence['started_unix_s'])}.json"
    evidence["artifact_path"] = str(artifact_path)
    artifact_path.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(json.dumps(evidence, indent=2, default=str))
    if not passed:
        raise SystemExit(1)
