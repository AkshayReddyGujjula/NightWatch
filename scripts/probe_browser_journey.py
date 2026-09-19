"""Track B â€” browser unblock probe: Route A diagnosis, Route B CDP first hop, typed journey.

Plan Â§11.8. Runs in `nightwatch-b` against the pinned desktop image and records
RAW evidence only:

* Route A diagnosis: the controller-owned Chrome is launched with the loopback
  DevTools endpoint declared at startup (`--remote-debugging-port=0`); this probe
  records `/proc/<pid>/cmdline`, the profile's `DevToolsActivePort`, the listener
  owner from `ss -ltnp` and the live `/json/version` response before calling
  `browser_prepare`, so the exact refusal is attributable.
* Route B (one-hop, recorded honestly): if the typed existing-profile attach is
  still refused, the driver launches its own isolated browser, and the probe
  sends exactly ONE raw CDP `Page.navigate` to the allowed origin so the live
  page origin satisfies the origin-scoped bounded manifest; every later action
  goes through the typed CUA tools.
* Task 1 evidence: raw `browser_prepare` + `get_browser_state(semantic_v2)`,
  binding quality/mutation, URL on the allowed origin, non-empty semantic refs,
  at least one screenshot with sha256 + byte size.
* Task 2 evidence: one live TypeSafe Jev Choice over bounded action IDs, the
  executed typed action, a FRESH snapshot postcondition and >= 3 screenshots
  with distinct hashes.

Run:  uv run modal run -e nightwatch-b scripts/probe_browser_journey.py
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import modal  # noqa: E402
from infra.modal_desktop_image import DESKTOP_IMAGE  # noqa: E402

app = modal.App("nightwatch-b-browser-probe")

_STORE_DIR = _REPO_ROOT / "apps" / "storefront"
_EXEC_TIMEOUT_S = 45
_FIXTURE_EMAIL = "probe@example.com"
_TARGET_URL = "http://127.0.0.1:8080/checkout-x.html?intent=probe-intent-1"
_ALLOWED_ORIGIN = "http://127.0.0.1:8080"

GATE_SERVER_SOURCE = '''"""NightWatch storefront probe fixture (labelled stub, not the store)."""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

STATE: dict[str, object] = {"checkout_posts": [], "intent_reads": [], "order_reads": []}
COUNTER = {"n": 0}
ROOT = Path(".")
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "NightWatchProbe/1.0"

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
                    "intent_id": "probe-intent-1",
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
            order_id = f"probe-order-{COUNTER['n']}"
            posts = STATE["checkout_posts"]
            if isinstance(posts, list):
                posts.append(
                    {
                        "intent_id": intent_id,
                        "order_id": order_id,
                        "email": body.get("email"),
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


class ProbeError(RuntimeError):
    """Recorded, never faked."""


def _probe_image() -> modal.Image:
    with tempfile.NamedTemporaryFile(
        "w", suffix="-probe-server.py", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(GATE_SERVER_SOURCE)
        script_path = Path(handle.name)
    return (
        DESKTOP_IMAGE.add_local_dir(_STORE_DIR, "/opt/nightwatch/app", copy=True)
        .add_local_file(script_path, "/opt/nightwatch/probe_server.py", copy=True)
    )


def _read_stream(stream: Any) -> str:
    data = stream.read()
    return data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)


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
        raise ProbeError(f"no JSON object in output: {text[:300]!r}")
    return json.loads(text[start : end + 1])


class CuaDriver:
    """Raw typed-call client; refusals are recorded, never raised away."""

    def __init__(self, sandbox: modal.Sandbox, evidence: dict[str, Any], socket_path: str):
        self._sandbox = sandbox
        self._socket = socket_path
        self.calls: list[dict[str, Any]] = evidence.setdefault("cua_calls", [])

    def probe(
        self,
        tool: str,
        arguments: dict[str, Any],
        *,
        session: str | None = None,
        screenshot_out: str | None = None,
    ) -> dict[str, Any]:
        payload = dict(arguments)
        if session is not None:
            payload["session"] = session
        argv = [
            "/run/nightwatch/as_controller.sh",
            "timeout",
            str(_EXEC_TIMEOUT_S),
            "cua-driver",
            "call",
            tool,
            json.dumps(payload),
            "--socket",
            self._socket,
        ]
        if screenshot_out:
            argv += ["--screenshot-out-file", screenshot_out]
        code, stdout, stderr = _exec(self._sandbox, *argv, timeout=_EXEC_TIMEOUT_S + 30)
        record = {
            "tool": tool,
            "arguments": payload,
            "exit_code": code,
            "stdout_tail": stdout[-4000:],
            "stderr_tail": stderr[-800:],
        }
        self.calls.append(record)
        try:
            data = _json_from(stdout)
        except ProbeError:
            return {"ok": False, "error": f"no JSON (exit {code})", "raw": stdout[-800:]}
        refused = bool(data.get("refusal")) or data.get("status") == "refused"
        return {
            "ok": code == 0 and not refused,
            "refused": refused,
            "data": data,
            "exit_code": code,
        }

    def call(self, tool: str, arguments: dict[str, Any], *, session: str | None = None,
             screenshot_out: str | None = None) -> dict[str, Any]:
        result = self.probe(tool, arguments, session=session, screenshot_out=screenshot_out)
        if not result["ok"]:
            raise ProbeError(f"{tool} failed: {json.dumps(result)[:600]}")
        return result["data"]


# ------------------------------------------------------------------ raw CDP hop


def _sandbox_json(sandbox: modal.Sandbox, url: str, timeout: int = 20) -> dict[str, Any]:
    """HTTP JSON read executed INSIDE the sandbox (loopback is unreachable locally)."""
    code, stdout, stderr = _exec(
        sandbox, "curl", "-fsS", "--max-time", "5", url, timeout=timeout
    )
    if code != 0:
        return {"error": (stderr or stdout)[-300:]}
    return _json_from(stdout)


def _run_in_sandbox(
    sandbox: modal.Sandbox, name: str, source: str, *argv: str, timeout: int = 60
) -> dict[str, Any]:
    """Write a self-contained script into the sandbox and run it, returning JSON."""
    remote = f"/tmp/{name}.py"
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    code, _, stderr = _exec(
        sandbox,
        "bash",
        "-lc",
        f"printf %s {encoded} | base64 -d > {remote}",
        timeout=60,
    )
    if code != 0:
        return {"error": f"could not write {remote}: {stderr[-200:]}"}
    code, stdout, stderr = _exec(
        sandbox, "python3", remote, *argv, timeout=timeout
    )
    if code != 0:
        return {"error": (stderr or stdout)[-400:]}
    try:
        return _json_from(stdout)
    except ProbeError:
        return {"error": f"no JSON: {stdout[-300:]}"}


CDP_HOP_SOURCE = '''"""One recorded Page.navigate over the driver-owned loopback CDP endpoint."""
import json
import os
import socket
import sys
import time
import urllib.request
from urllib.parse import urlparse


def http_json(url, timeout=5.0):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", "replace"))


def ws_connect(url, timeout=10.0):
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 80
    path = parsed.path + (("?" + parsed.query) if parsed.query else "")
    sock = socket.create_connection((host, port), timeout=timeout)
    key = os.urandom(16).hex()
    request = (
        "GET " + path + " HTTP/1.1\\r\\nHost: " + host + ":" + str(port) + "\\r\\n"
        "Upgrade: websocket\\r\\nConnection: Upgrade\\r\\n"
        "Sec-WebSocket-Key: " + key + "\\r\\nSec-WebSocket-Version: 13\\r\\n\\r\\n"
    )
    sock.sendall(request.encode())
    response = b""
    while b"\\r\\n\\r\\n" not in response:
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError("handshake closed")
        response += chunk
    if b"101" not in response.split(b"\\r\\n", 1)[0]:
        raise RuntimeError("handshake failed: " + repr(response[:160]))
    return sock


def ws_send_text(sock, payload):
    import base64
    data = payload.encode()
    header = bytearray([0x81])
    mask = os.urandom(4)
    length = len(data)
    if length < 126:
        header.append(0x80 | length)
    elif length < 65536:
        header.append(0x80 | 126)
        header += length.to_bytes(2, "big")
    else:
        header.append(0x80 | 127)
        header += length.to_bytes(8, "big")
    header += mask
    masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
    sock.sendall(bytes(header) + masked)


def ws_recv_text(sock, timeout):
    sock.settimeout(timeout)
    try:
        header = sock.recv(2)
    except TimeoutError:
        return None
    if len(header) < 2:
        raise RuntimeError("closed")
    opcode = header[0] & 0x0F
    length = header[1] & 0x7F
    if length == 126:
        length = int.from_bytes(sock.recv(2), "big")
    elif length == 127:
        length = int.from_bytes(sock.recv(8), "big")
    mask = sock.recv(4) if header[1] & 0x80 else b""
    payload = b""
    while len(payload) < length:
        chunk = sock.recv(length - len(payload))
        if not chunk:
            raise RuntimeError("closed mid-frame")
        payload += chunk
    if mask:
        payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    if opcode == 0x8:
        raise RuntimeError("close frame")
    if opcode == 0x9:
        return ""
    if opcode in (0x1, 0x2):
        return payload.decode("utf-8", "replace")
    return ""


def main():
    port = int(sys.argv[1])
    target = sys.argv[2]
    record = {"endpoint_port": port, "target_url": target}
    try:
        listing = http_json("http://127.0.0.1:%d/json/list" % port)
        record["targets_before"] = [
            {"type": item.get("type"), "url": item.get("url")}
            for item in listing
            if isinstance(item, dict)
        ]
        page = next(
            (item for item in listing if isinstance(item, dict) and item.get("type") == "page"),
            None,
        )
        if page is None or not page.get("webSocketDebuggerUrl"):
            record["error"] = "no page target with a websocket url"
            print(json.dumps(record))
            return
        sock = ws_connect(page["webSocketDebuggerUrl"])
        try:
            ws_send_text(
                sock,
                json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": target}}),
            )
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                message = ws_recv_text(sock, 2.0)
                if message is None:
                    break
                if not message:
                    continue
                record["last_message"] = message[:400]
                try:
                    parsed = json.loads(message)
                except ValueError:
                    continue
                if isinstance(parsed, dict) and parsed.get("id") == 1:
                    record["navigate_response"] = parsed
                    break
        finally:
            try:
                sock.close()
            except Exception:
                pass
        time.sleep(0.5)
        after = http_json("http://127.0.0.1:%d/json/list" % port)
        record["targets_after"] = [
            {"type": item.get("type"), "url": item.get("url")}
            for item in after
            if isinstance(item, dict)
        ]
        record["navigated"] = any(
            isinstance(item, dict)
            and item.get("type") == "page"
            and str(item.get("url", "")).startswith("http://127.0.0.1:8080")
            for item in after
        )
    except Exception as error:
        record["error"] = "%s: %s" % (type(error).__name__, error)
    print(json.dumps(record))


main()
'''


def cdp_page_navigate(sandbox: modal.Sandbox, port: int, target_url: str) -> dict[str, Any]:
    """ONE recorded Page.navigate executed inside the sandbox (loopback is local there)."""
    return _run_in_sandbox(
        sandbox, "nw_cdp_hop", CDP_HOP_SOURCE, str(port), target_url, timeout=60
    )


# ------------------------------------------------------------------- helpers


def _pick(payload: Any, key: str) -> Any:
    if not isinstance(payload, dict):
        return None
    if key in payload:
        return payload[key]
    for value in payload.values():
        if isinstance(value, dict) and key in value:
            return value[key]
    return None


def _find_url(payload: Any, schemes: tuple[str, ...]) -> str | None:
    if isinstance(payload, str):
        return payload if payload.startswith(schemes) else None
    if isinstance(payload, dict):
        for value in payload.values():
            found = _find_url(value, schemes)
            if found:
                return found
    if isinstance(payload, list):
        for item in payload:
            found = _find_url(item, schemes)
            if found:
                return found
    return None


def _refs(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    refs = snapshot.get("refs")
    return [ref for ref in refs if isinstance(ref, dict)] if isinstance(refs, list) else []


def _browser_identity(sandbox: modal.Sandbox) -> dict[str, Any]:
    code, text, _ = _exec(sandbox, "cat", "/run/nightwatch/browser.json", timeout=20)
    return _json_from(text) if code == 0 else {}


def _endpoint_diagnostics(sandbox: modal.Sandbox, pid: int | None) -> dict[str, Any]:
    evidence: dict[str, Any] = {}
    profile = "/run/nightwatch/chrome-profile"
    if pid:
        code, text, _ = _exec(sandbox, "cat", f"/proc/{pid}/cmdline", timeout=20)
        if code == 0:
            cmdline = text.replace("\x00", " ").strip()
            evidence["cmdline"] = cmdline
            match = re.search(r"--user-data-dir=(\S+)", cmdline)
            if match:
                profile = match.group(1)
    code, text, _ = _exec(sandbox, "cat", f"{profile}/DevToolsActivePort", timeout=20)
    active = text.strip() if code == 0 else None
    evidence["devtools_active_port_file"] = active
    evidence["profile"] = profile
    port = active.splitlines()[0].strip() if active else None
    evidence["devtools_port"] = port
    if pid:
        code, text, _ = _exec(
            sandbox, "bash", "-lc", f"ls -ln /proc/{pid}/fd 2>/dev/null | head -n 40", timeout=20
        )
        if code == 0:
            evidence["fd_listing"] = text.strip().splitlines()
    code, text, _ = _exec(sandbox, "ss", "-ltnp", timeout=20)
    if code == 0:
        lines = text.splitlines()
        evidence["ss_listen_all"] = [line.strip() for line in lines[1:12]]
        if port:
            evidence["ss_listen_port"] = [
                line.strip() for line in lines if f":{port}" in line
            ][:6]
    if port:
        version = _sandbox_json(sandbox, f"http://127.0.0.1:{port}/json/version")
        evidence["json_version"] = version
    return evidence


STRINGS_FILTER = (
    "DevToolsActivePort|remote-debugging|uniquely PID-owned|endpoint_ownership|"
    "existing_profile|requires_setup|spawned_by_driver"
)


def _driver_strings(sandbox: modal.Sandbox) -> dict[str, Any]:
    """Grep the pinned driver binary for its own endpoint/proof vocabulary."""
    binary = "/opt/cua-driver/0.28.2/cua-driver"
    code, stdout, stderr = _exec(
        sandbox,
        "bash",
        "-lc",
        f"strings -a {binary} 2>/dev/null | grep -E -i '{STRINGS_FILTER}' | sort -u | head -n 80",
        timeout=90,
    )
    if code != 0:
        return {"error": (stderr or stdout)[-300:]}
    return {"lines": stdout.strip().splitlines()[:80]}


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
    goal: str, observation: dict[str, Any], candidates: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    from typesafe_sdk import AsyncTypeSafeClient, Choice

    env = _load_env_file(_REPO_ROOT / ".env")
    api_key = env.get("TYPESAFE_API_KEY")
    if not api_key:
        raise ProbeError("TYPESAFE_API_KEY missing from local .env")
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


def frame_record(sandbox: modal.Sandbox, path: str, at_ns: int) -> dict[str, Any]:
    record: dict[str, Any] = {"at_ns": at_ns, "path": path}
    code, stdout, _ = _exec(sandbox, "sha256sum", path, timeout=30)
    if code == 0 and stdout.strip():
        record["sha256"] = stdout.split()[0]
    code, stdout, _ = _exec(sandbox, "stat", "-c", "%s", path, timeout=30)
    if code == 0 and stdout.strip():
        record["size"] = int(stdout.strip())
    return record


def fetch_state(sandbox: modal.Sandbox) -> dict[str, Any]:
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
        raise ProbeError(f"state fetch failed: {(stderr or stdout)[-300:]}")
    return _json_from(stdout)


@app.local_entrypoint()
def main() -> None:
    evidence: dict[str, Any] = {
        "probe": "browser_journey",
        "environment": "nightwatch-b",
        "started_unix_s": time.time(),
        "sandbox_id": None,
        "route_a_diagnostics": {},
        "verdict": {},
        "errors": [],
    }
    sandbox: modal.Sandbox | None = None
    session = f"nw-probe-{uuid.uuid4().hex[:8]}"
    evidence["session"] = session
    driver: CuaDriver | None = None
    try:
        image = _probe_image()
        create_started = time.monotonic()
        sandbox = modal.Sandbox.create(app=app, image=image, timeout=900, idle_timeout=300)
        evidence["sandbox_id"] = sandbox.object_id
        evidence["image_id"] = image.object_id
        evidence["sandbox_create_s"] = round(time.monotonic() - create_started, 3)

        bootstrap_started = time.monotonic()
        code, stdout, stderr = _exec(
            sandbox,
            "/opt/nightwatch/start_desktop_world.sh",
            env={
                "NW_APP_PORT": "8080",
                "NW_APP_DIR": "/opt/nightwatch/app",
                "NW_APP_CMD": (
                    "python3 /opt/nightwatch/probe_server.py "
                    "--root /opt/nightwatch/app --port 8080"
                ),
                "NW_APP_READY_PATH": "/",
                "NW_BROWSER_DEBUG_PORT": "9222",
            },
            timeout=420,
        )
        evidence["bootstrap_s"] = round(time.monotonic() - bootstrap_started, 3)
        evidence["bootstrap_exit_code"] = code
        if code != 0:
            raise ProbeError(f"world bootstrap failed: {(stderr or stdout)[-600:]}")
        code, text, _ = _exec(sandbox, "cat", "/run/nightwatch/world-evidence.json", timeout=30)
        evidence["world"] = _json_from(text)
        socket_path = str(evidence["world"].get("cua_socket") or "/run/nightwatch/cua.sock")
        driver = CuaDriver(sandbox, evidence, socket_path)
        code, _, _ = _exec(
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
        if code != 0:
            raise ProbeError("could not create frames dir")
        identity = _browser_identity(sandbox)
        chrome_pid = int(identity.get("pid") or 0)
        window_id = int(identity.get("window_id") or 0)
        evidence["browser_json"] = identity
        evidence["route_a_diagnostics"] = _endpoint_diagnostics(sandbox, chrome_pid or None)
        evidence["driver_strings"] = _driver_strings(sandbox)
        if not chrome_pid or not window_id:
            raise ProbeError("browser.json has no pid/window_id")

        # --- Route A: controller-owned browser + declared DevTools endpoint ---
        route_a = driver.probe(
            "browser_prepare",
            {
                "pid": chrome_pid,
                "window_id": window_id,
                "strategy": {"kind": "existing_profile"},
            },
            session=session,
        )
        evidence["route_a_prepare"] = route_a
        use_route_a = route_a["ok"]
        if not use_route_a and "restart" in json.dumps(route_a).lower():
            code, out, err = _exec(sandbox, "/run/nightwatch/launch_browser.sh", timeout=180)
            evidence["route_a_restart_exit_code"] = code
            if code != 0:
                raise ProbeError(f"browser restart failed: {(err or out)[-400:]}")
            identity = _browser_identity(sandbox)
            chrome_pid = int(identity.get("pid") or 0)
            window_id = int(identity.get("window_id") or 0)
            evidence["browser_json_after_restart"] = identity
            route_a2 = driver.probe(
                "browser_prepare",
                {
                    "pid": chrome_pid,
                    "window_id": window_id,
                    "strategy": {"kind": "existing_profile"},
                },
                session=session,
            )
            evidence["route_a_prepare_after_restart"] = route_a2
            use_route_a = route_a2["ok"]
        evidence["route_a_prepare_ok"] = use_route_a

        # --- Route C: driver-launched Chrome via launch_app, then attach ------
        route_c_prepared: dict[str, Any] | None = None
        launched_pid = 0
        launched_window = 0
        if not use_route_a:
            launch_attempts: list[dict[str, Any]] = []
            for shape in (
                {"executable": "/opt/google/chrome/chrome"},
                {"app": "/opt/google/chrome/chrome"},
                {"path": "/opt/google/chrome/chrome"},
            ):
                attempt = driver.probe("launch_app", shape, session=session)
                launch_attempts.append({"arguments": shape, "result": attempt})
                if attempt["ok"]:
                    launched_pid = int(_pick(attempt["data"], "pid") or 0)
                    launched_window = int(_pick(attempt["data"], "window_id") or 0)
                    break
            evidence["route_c_launch_app"] = launch_attempts
            if launched_pid:
                if not launched_window:
                    listing = driver.probe("list_windows", {"pid": launched_pid}, session=session)
                    evidence["route_c_list_windows"] = listing
                    windows = (listing.get("data") or {}).get("windows") or []
                    if windows:
                        launched_window = int(windows[0].get("window_id") or 0)
                if launched_window:
                    route_c = driver.probe(
                        "browser_prepare",
                        {
                            "pid": launched_pid,
                            "window_id": launched_window,
                            "strategy": {"kind": "existing_profile"},
                        },
                        session=session,
                    )
                    evidence["route_c_prepare"] = route_c
                    if route_c["ok"]:
                        route_c_prepared = route_c["data"]

        bind_pid = launched_pid if route_c_prepared else chrome_pid
        bind_window = launched_window if route_c_prepared else window_id
        prepared_raw = route_a["data"] if use_route_a else (route_c_prepared or {})
        side_effects = _pick(prepared_raw, "side_effects")
        evidence["prepare_endpoint_ownership"] = _pick(prepared_raw, "endpoint_ownership")
        evidence["prepare_side_effects"] = side_effects
        evidence["verdict"]["prepare_ready"] = bool(
            use_route_a or route_c_prepared is not None
        )

        # Bind the browser (driver-launched browser needs its own pid/window).
        bound: dict[str, Any] | None = None
        bind_attempts: list[dict[str, Any]] = []
        for pid_value, window_value in ((bind_pid, bind_window), (chrome_pid, window_id)):
            listing = driver.probe("list_windows", {"pid": pid_value}, session=session)
            bind_attempts.append({"pid": pid_value, "listing": listing})
            windows = (listing.get("data") or {}).get("windows") or []
            if not windows:
                continue
            chosen_window = window_value or int(windows[0].get("window_id") or 0)
            bound = driver.call(
                "get_browser_state",
                {"pid": pid_value, "window_id": chosen_window},
                session=session,
            )
            bound_pid = pid_value
            break
        evidence["bind_attempts"] = bind_attempts
        if bound is None:
            raise ProbeError("no browser window could be bound")
        evidence["binding"] = {
            key: bound.get(key)
            for key in (
                "binding_quality",
                "binding_route",
                "endpoint_access_class",
                "endpoint_transport",
                "mode",
                "mutation_allowed",
                "native_title",
                "native_url",
                "url",
            )
        }
        target_id = str(bound["target_id"])
        tabs = [tab for tab in (bound.get("tabs") or []) if isinstance(tab, dict)]
        if not tabs:
            raise ProbeError("binding returned no tabs")
        selected = next((tab for tab in tabs if tab.get("active")), tabs[0])
        tab_id = str(selected["tab_id"])
        evidence["target_id"] = target_id
        evidence["tab_id"] = tab_id
        evidence["bound_pid"] = bound_pid

        # One-hop deviation: a single raw CDP Page.navigate to the allowed origin
        # when the bound page is not already on it; every later action is typed.
        current_url = str(bound.get("url") or selected.get("url") or "")
        if not current_url.startswith(_ALLOWED_ORIGIN):
            debug_url = _find_url(prepared_raw, ("ws://",))
            port: int | None = None
            if debug_url:
                port = urlparse(debug_url).port
            if port is None:
                diag = _endpoint_diagnostics(sandbox, bound_pid)
                evidence["route_b_endpoint"] = diag
                port = int(diag["devtools_port"]) if diag.get("devtools_port") else None
            if port is None:
                listing_all = driver.probe("list_windows", {"pid": bound_pid}, session=session)
                evidence["route_b_listing"] = listing_all
                raise ProbeError("could not locate the driver browser's loopback DevTools port")
            evidence["route_b_cdp_navigate"] = cdp_page_navigate(sandbox, port, _TARGET_URL)
            evidence["verdict"]["cdp_first_hop"] = bool(
                evidence["route_b_cdp_navigate"].get("navigated")
            )
        else:
            driver.call(
                "browser_navigate",
                {"target_id": target_id, "tab_id": tab_id, "url": _TARGET_URL},
                session=session,
            )
            evidence["verdict"]["typed_navigate"] = True

        # --- Task 1: typed semantic_v2 snapshot on the allowed origin --------
        task1_at_ns = time.monotonic_ns()
        semantic = driver.call(
            "get_browser_state",
            {
                "target_id": target_id,
                "tab_id": tab_id,
                "snapshot_format": "semantic_v2",
                "include_screenshot": True,
            },
            session=session,
            screenshot_out="/run/nightwatch/frames/task1-probe.png",
        )
        evidence["task1_semantic_state"] = semantic
        evidence["task1_frame"] = frame_record(
            sandbox, "/run/nightwatch/frames/task1-probe.png", task1_at_ns
        )
        semantic_url = _find_url(
            {
                key: semantic.get(key)
                for key in ("url", "bound_url", "native_url", "current_url")
            },
            ("http://127.0.0.1:8080",),
        ) or str(semantic.get("url") or "")
        element_count = len(_refs(semantic))
        evidence["task1_summary"] = {
            "url": semantic_url,
            "binding_quality": semantic.get("binding_quality"),
            "mutation_allowed": semantic.get("mutation_allowed"),
            "element_count": element_count,
            "snapshot_id": semantic.get("snapshot_id"),
            "capture_id": semantic.get("capture_id"),
            "ref_roles": [
                {"ref": ref.get("ref"), "role": ref.get("role"), "name": ref.get("name")}
                for ref in _refs(semantic)[:12]
            ],
        }
        evidence["verdict"]["typed_semantic_snapshot"] = bool(
            semantic.get("binding_quality") == "exact"
            and semantic.get("mutation_allowed") is True
            and str(semantic.get("url") or "").startswith(_ALLOWED_ORIGIN)
            and element_count > 0
        )

        # --- Task 2: one live Jev atom ---------------------------------------
        goal = (
            "Complete one checkout of SKU-A quantity 1 and reach a paid state, "
            "using only the supplied actions."
        )
        completed: list[str] = []
        actions: list[dict[str, Any]] = []
        decision_records: list[dict[str, Any]] = []
        for step in range(1, 5):
            observation = compact_observation(semantic, completed)
            observation_hash = hashlib.sha256(
                json.dumps(observation, sort_keys=True).encode()
            ).hexdigest()
            candidates = build_candidates(semantic, _FIXTURE_EMAIL)
            decision = jev_choose(goal, observation, candidates)
            answer = decision.get("answer") if isinstance(decision.get("answer"), dict) else {}
            choice = str(answer.get("choice"))
            record = {
                "step": step,
                "observation_hash": observation_hash,
                "offered": list(candidates),
                "decision": decision,
                "confidence": answer.get("confidence"),
                "probabilities": answer.get("probabilities"),
                "model_name": decision.get("response_model"),
            }
            decision_records.append(record)
            if choice not in candidates:
                raise ProbeError(f"Jev chose an unoffered candidate: {choice!r}")
            if choice in ("abstain", "reobserve"):
                record["executed"] = False
                break
            selected_candidate = candidates[choice]
            before_path = f"/run/nightwatch/frames/jev-{step:02d}-before.png"
            before_at_ns = time.monotonic_ns()
            fresh = driver.call(
                "get_browser_state",
                {
                    "target_id": target_id,
                    "tab_id": tab_id,
                    "snapshot_format": "semantic_v2",
                    "include_screenshot": True,
                },
                session=session,
                screenshot_out=before_path,
            )
            ref = str(selected_candidate.get("ref"))
            if not any(item.get("ref") == ref for item in _refs(fresh)):
                record["executed"] = False
                record["action"] = "stale_ref"
                break
            driver.call(
                str(selected_candidate["tool"]),
                dict(selected_candidate["args"]),
                session=session,
            )
            after_path = f"/run/nightwatch/frames/jev-{step:02d}-after.png"
            after_at_ns = time.monotonic_ns()
            after = driver.call(
                "get_browser_state",
                {
                    "target_id": target_id,
                    "tab_id": tab_id,
                    "snapshot_format": "semantic_v2",
                    "include_screenshot": True,
                },
                session=session,
                screenshot_out=after_path,
            )
            post_ref = next(
                (item for item in _refs(after) if item.get("ref") == ref), None
            )
            record["executed"] = True
            record["action"] = choice
            action_record = {
                "step": step,
                "candidate": choice,
                "confidence": answer.get("confidence"),
                "probabilities": answer.get("probabilities"),
                "before_frame": frame_record(sandbox, before_path, before_at_ns),
                "after_frame": frame_record(sandbox, after_path, after_at_ns),
                "postcondition": {
                    "kind": "element_state",
                    "ref": ref,
                    "value": (post_ref or {}).get("value"),
                    "verified": (post_ref or {}).get("value") == _FIXTURE_EMAIL,
                    "url_after": after.get("url"),
                },
            }
            actions.append(action_record)
            completed.append(choice)
            semantic = after
            if choice == "pay_now":
                break
        evidence["decisions"] = decision_records
        evidence["actions"] = actions
        evidence["verdict"]["jev_live_choice"] = bool(decision_records)
        evidence["verdict"]["action_executed"] = any(item.get("executed") for item in actions)
        evidence["verdict"]["element_postcondition_verified"] = any(
            item.get("postcondition", {}).get("verified") for item in actions
        )

        # Independent server-side postcondition (trusted app state, not the model).
        server_state: dict[str, Any] = {}
        server_ok = False
        for _ in range(20):
            server_state = fetch_state(sandbox)
            posts = server_state.get("checkout_posts") or []
            if posts:
                server_ok = posts[-1].get("email") == _FIXTURE_EMAIL
                break
            time.sleep(0.3)
        evidence["postcondition"] = {
            "checkout_posts": server_state.get("checkout_posts"),
            "email_matches_fixture": server_ok,
        }
        evidence["verdict"]["server_postcondition_verified"] = server_ok

        # Screenshot inventory: Task 1 + Task 2 frames.
        inventory: list[dict[str, Any]] = [evidence["task1_frame"]]
        for action in actions:
            for key in ("before_frame", "after_frame"):
                frame = action.get(key)
                if isinstance(frame, dict):
                    inventory.append(frame)
        hashes = [str(f["sha256"]) for f in inventory if f.get("sha256")]
        evidence["screenshot_inventory"] = {
            "count": len(inventory),
            "distinct_sha256": len(set(hashes)),
            "inventory": inventory,
        }
        evidence["verdict"]["screenshots_3_distinct"] = (
            len(inventory) >= 3 and len(set(hashes)) >= 3
        )

        with contextlib.suppress(Exception):
            driver.probe("end_session", {}, session=session)
            evidence["end_session"] = "ok"
    except Exception as error:  # noqa: BLE001 - recorded, never faked
        evidence["errors"].append(f"{type(error).__name__}: {error}")
    finally:
        if driver is not None and sandbox is not None:
            with contextlib.suppress(Exception):
                driver.probe("end_session", {}, session=session)
        if sandbox is not None:
            with contextlib.suppress(Exception):
                sandbox.terminate()
            evidence["terminated"] = True

    evidence["verdict"]["probe_passed"] = bool(
        evidence["verdict"].get("prepare_ready")
        and evidence["verdict"].get("typed_semantic_snapshot")
        and evidence["verdict"].get("screenshots_3_distinct")
        and not evidence.get("errors")
    )
    artifacts_dir = _REPO_ROOT / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    artifact_path = artifacts_dir / f"browser_journey_{int(evidence['started_unix_s'])}.json"
    evidence["artifact_path"] = str(artifact_path)
    artifact_path.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(json.dumps(evidence, indent=2, default=str))
    if not evidence["verdict"]["probe_passed"]:
        raise SystemExit(1)
