"""Track B — driver-launch routes: `allow_launch` isolated profile and `launch_app`.

Discovered from the 0.28.2 binary's own vocabulary (recorded in
`infra/BROWSER_STACK_NOTES.md`):

* `browser_prepare` with `allow_launch=true` and `profile.mode=isolated_new`
  launches a separate driver-owned Chromium process (the `strategy.kind`
  enum only accepts `existing_profile`, so the isolated route is a profile
  mode, not a strategy);
* `launch_app` accepts `launch_path`, `urls` and `cdp_debugging_port`, so the
  driver can launch the browser directly at the allowed origin with the
  DevTools endpoint it owns.

Whichever route prepares first is bound, observed with the typed
`semantic_v2` snapshot, and (if the live page is not already on the allowed
origin) given exactly ONE raw CDP `Page.navigate` inside the sandbox — recorded
as a deviation. Then one live TypeSafe Jev action with a fresh-snapshot
postcondition.

Run:  uv run modal run -e nightwatch-b scripts/probe_browser_launch.py
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = Path(__file__).resolve().parent
for entry in (str(_REPO_ROOT), str(_SCRIPTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import modal  # noqa: E402
import probe_browser_journey as base  # noqa: E402

app = modal.App("nightwatch-b-browser-launch")

_ALLOWED_ORIGIN = base._ALLOWED_ORIGIN
_TARGET_URL = base._TARGET_URL
_FIXTURE_EMAIL = base._FIXTURE_EMAIL
_FIXTURE_ADDRESS = "1 Demo Street, London"
_FRAME_DIR = _REPO_ROOT / "artifacts" / "browser_frames"


def _copy_out(sandbox: modal.Sandbox, remote: str, local_name: str) -> dict[str, Any]:
    """Copy the exact frame bytes out of the sandbox so they survive teardown."""
    code, stdout, stderr = base._exec(sandbox, "base64", "-w", "0", remote, timeout=60)
    if code != 0:
        return {"error": (stderr or stdout)[-200:]}
    _FRAME_DIR.mkdir(parents=True, exist_ok=True)
    target = _FRAME_DIR / local_name
    import base64 as _b64

    target.write_bytes(_b64.b64decode(stdout))
    return {"local_path": str(target), "local_size": target.stat().st_size}


def _main_chrome_processes(sandbox: modal.Sandbox) -> list[dict[str, Any]]:
    """Main browser processes only (no renderer/zygote `--type=` children)."""
    code, stdout, _ = base._exec(
        sandbox,
        "bash",
        "-lc",
        "for p in $(pgrep -f '/opt/google/chrome/chrome' 2>/dev/null); do "
        "cmd=$(tr '\\0' ' ' < /proc/$p/cmdline 2>/dev/null); "
        "case \"$cmd\" in *--type=*) ;; *) echo \"$p|$cmd\";; esac; done",
        timeout=30,
    )
    processes: list[dict[str, Any]] = []
    if code != 0:
        return processes
    for line in stdout.splitlines():
        pid_text, _, cmdline = line.partition("|")
        if pid_text.strip().isdigit():
            processes.append({"pid": int(pid_text.strip()), "cmdline": cmdline.strip()})
    return processes


def _listener_ports(sandbox: modal.Sandbox) -> list[dict[str, Any]]:
    code, stdout, _ = base._exec(sandbox, "ss", "-ltnp", timeout=20)
    listeners: list[dict[str, Any]] = []
    if code != 0:
        return listeners
    for line in stdout.splitlines()[1:]:
        port_match = re.search(r"127\.0\.0\.1:(\d+)", line)
        pid_match = re.search(r"pid=(\d+)", line)
        if port_match and pid_match:
            listeners.append({"port": int(port_match.group(1)), "pid": int(pid_match.group(1))})
    return listeners


def _port_for_pid(sandbox: modal.Sandbox, pid: int) -> int | None:
    for listener in _listener_ports(sandbox):
        if listener["pid"] == pid and listener["port"] != 8080:
            return int(listener["port"])
    return None


@app.local_entrypoint()
def main() -> None:
    evidence: dict[str, Any] = {
        "probe": "browser_launch_routes",
        "environment": "nightwatch-b",
        "started_unix_s": time.time(),
        "sandbox_id": None,
        "verdict": {},
        "errors": [],
    }
    sandbox: modal.Sandbox | None = None
    session = f"nw-launch-{uuid.uuid4().hex[:8]}"
    evidence["session"] = session
    driver: base.CuaDriver | None = None
    try:
        image = base._probe_image()
        create_started = time.monotonic()
        sandbox = modal.Sandbox.create(app=app, image=image, timeout=900, idle_timeout=300)
        evidence["sandbox_id"] = sandbox.object_id
        evidence["image_id"] = image.object_id
        evidence["sandbox_create_s"] = round(time.monotonic() - create_started, 3)

        bootstrap_started = time.monotonic()
        code, stdout, stderr = base._exec(
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
            },
            timeout=420,
        )
        evidence["bootstrap_s"] = round(time.monotonic() - bootstrap_started, 3)
        evidence["bootstrap_exit_code"] = code
        if code != 0:
            raise base.ProbeError(f"world bootstrap failed: {(stderr or stdout)[-600:]}")
        code, text, _ = base._exec(sandbox, "cat", "/run/nightwatch/world-evidence.json", timeout=30)
        evidence["world"] = base._json_from(text)
        socket_path = str(evidence["world"].get("cua_socket") or "/run/nightwatch/cua.sock")
        driver = base.CuaDriver(sandbox, evidence, socket_path)
        code, _, _ = base._exec(
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
            raise base.ProbeError("could not create frames dir")
        controller = base._browser_identity(sandbox)
        evidence["controller_browser"] = controller
        baseline_pids = {item["pid"] for item in _main_chrome_processes(sandbox)}
        evidence["baseline_main_chrome_pids"] = sorted(baseline_pids)

        chosen: dict[str, Any] | None = None

        # --- Route X: driver-owned isolated profile ---------------------------
        route_x = driver.probe(
            "browser_prepare",
            {"allow_launch": True, "profile": {"mode": "isolated_new"}},
            session=session,
        )
        evidence["route_x_prepare"] = route_x
        if route_x["ok"]:
            chosen = {"route": "isolated_new", "response": route_x["data"]}

        # --- Route Y: launch_app at the allowed origin, then attach -----------
        if chosen is None:
            route_y = driver.probe(
                "launch_app",
                {
                    "launch_path": "/opt/google/chrome/chrome",
                    "urls": [f"{_ALLOWED_ORIGIN}/"],
                    "cdp_debugging_port": 9222,
                    "additional_arguments": ["--remote-debugging-address=127.0.0.1"],
                },
                session=session,
            )
            evidence["route_y_launch_app"] = route_y
            if route_y["ok"]:
                launched_pid = int(base._pick(route_y["data"], "pid") or 0)
                time.sleep(1.5)
                processes = _main_chrome_processes(sandbox)
                evidence["route_y_chrome_processes"] = processes
                if not launched_pid:
                    new_pids = [
                        item["pid"] for item in processes if item["pid"] not in baseline_pids
                    ]
                    launched_pid = new_pids[0] if new_pids else 0
                if launched_pid:
                    listing = driver.probe("list_windows", {"pid": launched_pid}, session=session)
                    evidence["route_y_list_windows"] = listing
                    windows = (listing.get("data") or {}).get("windows") or []
                    if windows:
                        route_y_prepare = driver.probe(
                            "browser_prepare",
                            {
                                "pid": launched_pid,
                                "window_id": int(windows[0]["window_id"]),
                                "strategy": {"kind": "existing_profile"},
                            },
                            session=session,
                        )
                        evidence["route_y_prepare"] = route_y_prepare
                        if route_y_prepare["ok"]:
                            chosen = {
                                "route": "launch_app",
                                "pid": launched_pid,
                                "window_id": int(windows[0]["window_id"]),
                                "response": route_y_prepare["data"],
                            }
                            evidence["route_y_listener_port"] = _port_for_pid(
                                sandbox, launched_pid
                            )

        # --- Route A: controller-owned browser (evidence of the exact refusal) --
        if chosen is None:
            route_a = driver.probe(
                "browser_prepare",
                {
                    "pid": int(controller.get("pid") or 0),
                    "window_id": int(controller.get("window_id") or 0),
                    "strategy": {"kind": "existing_profile"},
                },
                session=session,
            )
            evidence["route_a_prepare"] = route_a
            if route_a["ok"]:
                chosen = {
                    "route": "existing_profile",
                    "pid": int(controller.get("pid") or 0),
                    "window_id": int(controller.get("window_id") or 0),
                    "response": route_a["data"],
                }

        if chosen is None:
            raise base.ProbeError(
                "no prepare route succeeded: "
                + json.dumps(
                    {
                        "x": (evidence.get("route_x_prepare") or {}).get("data"),
                        "y": (evidence.get("route_y_prepare") or {}).get("data"),
                        "a": (evidence.get("route_a_prepare") or {}).get("data"),
                    }
                )[:900]
            )

        evidence["chosen_route"] = {
            "route": chosen["route"],
            "endpoint_ownership": base._pick(chosen["response"], "endpoint_ownership"),
            "side_effects": base._pick(chosen["response"], "side_effects"),
            "prepared_pid": base._pick(chosen["response"], "prepared_pid"),
            "window_id": base._pick(chosen["response"], "window_id"),
        }
        evidence["verdict"]["prepare_ok"] = True

        bind_pid = int(
            chosen.get("pid")
            or base._pick(chosen["response"], "prepared_pid")
            or base._pick(chosen["response"], "pid")
            or controller.get("pid")
            or 0
        )
        bind_window = int(
            chosen.get("window_id") or base._pick(chosen["response"], "window_id") or 0
        )
        if not bind_window and bind_pid == int(controller.get("pid") or 0):
            # Only the controller-owned browser shares browser.json's window id.
            bind_window = int(controller.get("window_id") or 0)
        if not bind_window:
            # The driver-launched browser registers its own X11 window; give the
            # window manager a moment, then bind the window that pid actually owns.
            listing: dict[str, Any] = {}
            for _ in range(20):
                listing = driver.probe("list_windows", {"pid": bind_pid}, session=session)
                windows = (listing.get("data") or {}).get("windows") or []
                if windows:
                    bind_window = int(windows[0]["window_id"])
                    break
                time.sleep(0.5)
            evidence["bind_list_windows"] = listing
        bound = driver.call(
            "get_browser_state",
            {"pid": bind_pid, "window_id": bind_window},
            session=session,
        )
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
                "url",
            )
        }
        target_id = str(bound["target_id"])
        tabs = [tab for tab in (bound.get("tabs") or []) if isinstance(tab, dict)]
        if not tabs:
            raise base.ProbeError("binding returned no tabs")
        selected = next((tab for tab in tabs if tab.get("active")), tabs[0])
        tab_id = str(selected["tab_id"])
        evidence["target_id"] = target_id
        evidence["tab_id"] = tab_id
        evidence["bound_pid"] = bind_pid

        if not str(bound.get("url") or "").startswith(_ALLOWED_ORIGIN):
            port = int(base._pick(chosen["response"], "port") or 0) or _port_for_pid(
                sandbox, bind_pid
            )
            evidence["hop_port"] = port
            if not port:
                diag = base._endpoint_diagnostics(sandbox, bind_pid)
                evidence["hop_diagnostics"] = diag
                port = int(diag["devtools_port"]) if diag.get("devtools_port") else 0
            if not port:
                raise base.ProbeError("could not locate a loopback DevTools port for the hop")
            evidence["cdp_hop"] = base.cdp_page_navigate(sandbox, port, _TARGET_URL)
            evidence["verdict"]["cdp_first_hop"] = bool(evidence["cdp_hop"].get("navigated"))
        else:
            driver.call(
                "browser_navigate",
                {"target_id": target_id, "tab_id": tab_id, "url": _TARGET_URL},
                session=session,
            )
            evidence["verdict"]["typed_navigate"] = True

        # --- Task 1: typed semantic_v2 snapshot on the allowed origin ---------
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
        evidence["task1_frame"] = base.frame_record(
            sandbox, "/run/nightwatch/frames/task1-probe.png", task1_at_ns
        )
        evidence["task1_frame"].update(
            _copy_out(sandbox, "/run/nightwatch/frames/task1-probe.png", "task1-probe.png")
        )
        evidence["tool_schemas"] = {
            tool: driver.probe(tool, {}, session=session)
            for tool in ("browser_type", "browser_click")
        }
        element_count = len(base._refs(semantic))
        semantic_page = semantic.get("page") if isinstance(semantic.get("page"), dict) else {}
        semantic_url = str(semantic_page.get("url") or "")
        binding_quality = base._pick(bound, "binding_quality")
        mutation_allowed = base._pick(bound, "mutation_allowed")
        evidence["task1_summary"] = {
            "url": semantic_url,
            "page_title": semantic_page.get("title"),
            "binding_quality": binding_quality,
            "mutation_allowed": mutation_allowed,
            "element_count": element_count,
            "snapshot_id": base._pick(semantic, "id"),
            "capture_id": base._pick(semantic, "capture_id"),
            "ref_roles": [
                {"ref": ref.get("ref"), "role": ref.get("role"), "name": ref.get("name")}
                for ref in base._refs(semantic)[:12]
            ],
        }
        evidence["verdict"]["typed_semantic_snapshot"] = bool(
            binding_quality == "exact"
            and mutation_allowed is True
            and semantic_url.startswith(_ALLOWED_ORIGIN)
            and element_count > 0
        )

        # --- Task 2: one live Jev atom ----------------------------------------
        goal = (
            "Complete one checkout of SKU-A quantity 1 and reach a paid state, "
            "using only the supplied actions."
        )
        completed: list[str] = []
        actions: list[dict[str, Any]] = []
        decision_records: list[dict[str, Any]] = []
        judged_frame_path = "/run/nightwatch/frames/task1-probe.png"
        judged_frame_at_ns = task1_at_ns
        for step in range(1, 5):
            observation = base.compact_observation(semantic, completed)
            observation_hash = hashlib.sha256(
                json.dumps(observation, sort_keys=True).encode()
            ).hexdigest()
            candidates = base.build_candidates(semantic, _FIXTURE_EMAIL)
            # Checkout requires email AND address before the page submits: offer
            # the address fill as its own bounded action and offer pay_now only
            # once the fresh snapshot shows both values set (plan §11.3).
            address_ref = next(
                (
                    ref
                    for ref in base._refs(semantic)
                    if ref.get("role") == "textbox"
                    and "address" in str(ref.get("name", "")).lower()
                ),
                None,
            )
            email_ref = next(
                (
                    ref
                    for ref in base._refs(semantic)
                    if ref.get("role") == "textbox"
                    and "email" in str(ref.get("name", "")).lower()
                ),
                None,
            )
            candidates.pop("pay_now", None)
            if address_ref is not None and address_ref.get("value") != _FIXTURE_ADDRESS:
                candidates["fill_address"] = {
                    "description": (
                        "Type the fixture delivery address into the visible "
                        "Delivery address field."
                    ),
                    "tool": "browser_type",
                    "ref": address_ref.get("ref"),
                    "args": {
                        "ref": address_ref.get("ref"),
                        "text": _FIXTURE_ADDRESS,
                        "replace": True,
                    },
                }
            email_filled = email_ref is not None and email_ref.get("value") == _FIXTURE_EMAIL
            address_filled = (
                address_ref is not None and address_ref.get("value") == _FIXTURE_ADDRESS
            )
            if email_filled and address_filled:
                pay_ref = next(
                    (
                        ref
                        for ref in base._refs(semantic)
                        if ref.get("role") == "button"
                        and str(ref.get("name", "")).strip().lower() == "pay now"
                    ),
                    None,
                )
                if pay_ref is not None:
                    candidates["pay_now"] = {
                        "description": (
                            "Click the visible Pay now button to submit the checkout."
                        ),
                        "tool": "browser_click",
                        "ref": pay_ref.get("ref"),
                        "args": {"ref": pay_ref.get("ref"), "input_route": "dom_event"},
                    }
            # Typed actions are tab-scoped: the driver refuses any browser_type /
            # browser_click without the exact current target_id and tab_id.
            for item in candidates.values():
                if item.get("tool") in ("browser_type", "browser_click"):
                    item["args"].setdefault("target_id", target_id)
                    item["args"].setdefault("tab_id", tab_id)
            decision = base.jev_choose(goal, observation, candidates)
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
                raise base.ProbeError(f"Jev chose an unoffered candidate: {choice!r}")
            if choice in ("abstain", "reobserve"):
                record["executed"] = False
                break
            selected_candidate = candidates[choice]
            # Refs are snapshot-scoped: act on exactly the observation Jev judged
            # (no intervening snapshot), then verify from a FRESH snapshot.
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
            expected_role = None
            expected_name = None
            for ref in base._refs(semantic):
                if ref.get("ref") == selected_candidate.get("ref"):
                    expected_role = ref.get("role")
                    expected_name = ref.get("name")
                    break
            post_ref = next(
                (
                    item
                    for item in base._refs(after)
                    if item.get("role") == expected_role and item.get("name") == expected_name
                ),
                None,
            )
            expected_value = (
                _FIXTURE_ADDRESS if choice == "fill_address" else _FIXTURE_EMAIL
            )
            record["executed"] = True
            record["action"] = choice
            action_record = {
                "step": step,
                "candidate": choice,
                "confidence": answer.get("confidence"),
                "probabilities": answer.get("probabilities"),
                "executed_ref": selected_candidate.get("ref"),
                "judged_frame": base.frame_record(
                    sandbox, judged_frame_path, judged_frame_at_ns
                ),
                "after_frame": base.frame_record(sandbox, after_path, after_at_ns),
                "postcondition": {
                    "kind": "element_state"
                    if choice in ("fill_email", "fill_address")
                    else "server_state_pending",
                    "expected_role": expected_role,
                    "expected_name": expected_name,
                    "value": (post_ref or {}).get("value"),
                    "expected_value": expected_value,
                    "verified": (post_ref or {}).get("value") == expected_value,
                    "url_after": base._pick(after, "url"),
                },
            }
            action_record["after_frame"].update(
                _copy_out(sandbox, after_path, f"jev-{step:02d}-after.png")
            )
            actions.append(action_record)
            completed.append(choice)
            semantic = after
            judged_frame_path = after_path
            judged_frame_at_ns = after_at_ns
            if choice == "pay_now":
                break
        evidence["decisions"] = decision_records
        evidence["actions"] = actions
        evidence["verdict"]["jev_live_choice"] = bool(decision_records)
        evidence["verdict"]["action_executed"] = any(item.get("executed") for item in actions)
        evidence["verdict"]["element_postcondition_verified"] = any(
            item.get("postcondition", {}).get("verified") for item in actions
        )

        server_state: dict[str, Any] = {}
        server_ok = False
        for _ in range(20):
            server_state = base.fetch_state(sandbox)
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
        if server_ok:
            for action in actions:
                if action.get("candidate") == "pay_now":
                    action["postcondition"]["verified"] = True
                    action["postcondition"]["server_state"] = {
                        "checkout_posts": server_state.get("checkout_posts"),
                        "email_matches_fixture": True,
                    }

        inventory: list[dict[str, Any]] = [evidence["task1_frame"]]
        for action in actions:
            for key in ("judged_frame", "after_frame"):
                frame = action.get(key)
                if isinstance(frame, dict):
                    inventory.append(frame)
        hashes = [str(frame["sha256"]) for frame in inventory if frame.get("sha256")]
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
        evidence["verdict"].get("prepare_ok")
        and evidence["verdict"].get("typed_semantic_snapshot")
        and evidence["verdict"].get("screenshots_3_distinct")
        and not evidence.get("errors")
    )
    artifacts_dir = _REPO_ROOT / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    artifact_path = artifacts_dir / f"browser_launch_{int(evidence['started_unix_s'])}.json"
    evidence["artifact_path"] = str(artifact_path)
    artifact_path.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(json.dumps(evidence, indent=2, default=str))
    if not evidence["verdict"]["probe_passed"]:
        raise SystemExit(1)
