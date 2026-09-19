"""Track B — `browser_type` route probe on an email input, then a full Jev checkout.

The 19 Sep probe proved the typed journey on the driver-launched isolated
browser: binding `exact`, CDP first hop to the allowed origin, semantic_v2
snapshots, and a verified `fill_address` postcondition from a fresh snapshot.
The Email field (`<input type="email">`) never reflected the write in the AX
value even though `browser_type` returned ok, and three Jev attempts abstained.

This probe records the raw outcome of each bounded `browser_type` argument shape
against that exact field, in order, and stops at the first shape whose FRESH
snapshot shows the value. If one lands, it continues through address + `pay_now`
so a complete checkout is proven from trusted server-side state.

Run:  uv run modal run -e nightwatch-b scripts/probe_browser_type.py
"""

from __future__ import annotations

import contextlib
import hashlib
import json
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
from probe_browser_launch import (  # noqa: E402
    _copy_out,
    _listener_ports,
    _port_for_pid,
)

app = modal.App("nightwatch-b-browser-type")

_ALLOWED_ORIGIN = base._ALLOWED_ORIGIN
_TARGET_URL = base._TARGET_URL
_FIXTURE_EMAIL = base._FIXTURE_EMAIL
_FIXTURE_ADDRESS = "1 Demo Street, London"


def _email_ref(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            ref
            for ref in base._refs(snapshot)
            if ref.get("role") == "textbox" and "email" in str(ref.get("name", "")).lower()
        ),
        None,
    )


def _ref_by_name(snapshot: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next(
        (ref for ref in base._refs(snapshot) if str(ref.get("name", "")).lower() == name),
        None,
    )


def _snapshot(
    sandbox: modal.Sandbox,
    driver: base.CuaDriver,
    target_id: str,
    tab_id: str,
    session: str,
    name: str,
) -> dict[str, Any]:
    path = f"/run/nightwatch/frames/{name}.png"
    at_ns = time.monotonic_ns()
    result = driver.call(
        "get_browser_state",
        {
            "target_id": target_id,
            "tab_id": tab_id,
            "snapshot_format": "semantic_v2",
            "include_screenshot": True,
        },
        session=session,
        screenshot_out=path,
    )
    record = base.frame_record(sandbox, path, at_ns)
    record.update(_copy_out(sandbox, path, f"{name}.png"))
    result["_frame"] = record
    return result


@app.local_entrypoint()
def main() -> None:
    evidence: dict[str, Any] = {
        "probe": "browser_type_routes",
        "environment": "nightwatch-b",
        "started_unix_s": time.time(),
        "sandbox_id": None,
        "verdict": {},
        "errors": [],
    }
    sandbox: modal.Sandbox | None = None
    session = f"nw-type-{uuid.uuid4().hex[:8]}"
    evidence["session"] = session
    driver: base.CuaDriver | None = None
    try:
        image = base._probe_image()
        sandbox = modal.Sandbox.create(app=app, image=image, timeout=900, idle_timeout=300)
        evidence["sandbox_id"] = sandbox.object_id
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

        prepared = driver.probe(
            "browser_prepare",
            {"allow_launch": True, "profile": {"mode": "isolated_new"}},
            session=session,
        )
        evidence["prepare"] = prepared
        if not prepared["ok"]:
            raise base.ProbeError(f"isolated prepare refused: {json.dumps(prepared)[:400]}")
        bind_pid = int(base._pick(prepared["data"], "prepared_pid") or 0)
        evidence["prepared_pid"] = bind_pid
        bind_window = 0
        for _ in range(20):
            listing = driver.probe("list_windows", {"pid": bind_pid}, session=session)
            windows = (listing.get("data") or {}).get("windows") or []
            if windows:
                bind_window = int(windows[0]["window_id"])
                break
            time.sleep(0.5)
        evidence["binding_listing"] = listing
        if not bind_window:
            raise base.ProbeError("driver browser exposed no X11 window")
        bound = driver.call(
            "get_browser_state", {"pid": bind_pid, "window_id": bind_window}, session=session
        )
        target_id = str(bound["target_id"])
        tabs = [tab for tab in (bound.get("tabs") or []) if isinstance(tab, dict)]
        tab_id = str(next((tab for tab in tabs if tab.get("active")), tabs[0])["tab_id"])
        evidence["binding"] = {
            key: bound.get(key) for key in ("binding_quality", "mutation_allowed", "url")
        }
        port = _port_for_pid(sandbox, bind_pid)
        evidence["listeners"] = _listener_ports(sandbox)
        evidence["hop_port"] = port
        if not port:
            raise base.ProbeError("no loopback DevTools port for the driver browser")
        evidence["cdp_hop"] = base.cdp_page_navigate(sandbox, port, _TARGET_URL)
        if not evidence["cdp_hop"].get("navigated"):
            raise base.ProbeError("CDP hop did not land on the allowed origin")

        snapshot = _snapshot(sandbox, driver, target_id, tab_id, session, "type-probe-initial")
        evidence["initial_frame"] = snapshot.pop("_frame", None)
        email = _email_ref(snapshot)
        evidence["initial_email_ref"] = email
        if email is None:
            raise base.ProbeError("no Email textbox in the first semantic snapshot")
        ref = str(email["ref"])

        variants: list[dict[str, Any]] = [
            {
                "label": "replace_true",
                "args": {"ref": ref, "text": _FIXTURE_EMAIL, "replace": True},
            },
            {"label": "no_replace", "args": {"ref": ref, "text": _FIXTURE_EMAIL}},
            {
                "label": "dom_event",
                "args": {
                    "ref": ref,
                    "text": _FIXTURE_EMAIL,
                    "replace": True,
                    "input_route": "dom_event",
                },
            },
            {
                "label": "click_then_type",
                "args": {"ref": ref, "text": _FIXTURE_EMAIL, "replace": False},
                "pre_click": True,
            },
        ]
        attempts: list[dict[str, Any]] = []
        winner: dict[str, Any] | None = None
        for variant in variants:
            result: dict[str, Any] = {"label": variant["label"], "args": variant["args"]}
            if variant.get("pre_click"):
                click_args = {
                    "ref": ref,
                    "input_route": "dom_event",
                    "target_id": target_id,
                    "tab_id": tab_id,
                }
                result["click"] = driver.probe(
                    "browser_click", click_args, session=session
                )
            call_args = dict(variant["args"])
            call_args.setdefault("target_id", target_id)
            call_args.setdefault("tab_id", tab_id)
            result["call"] = driver.probe("browser_type", call_args, session=session)
            after = _snapshot(
                sandbox, driver, target_id, tab_id, session, f"type-probe-{variant['label']}"
            )
            result["after_frame"] = after.pop("_frame", None)
            after_email = _email_ref(after)
            result["value_after"] = (after_email or {}).get("value")
            result["verified"] = (after_email or {}).get("value") == _FIXTURE_EMAIL
            attempts.append(result)
            if result["verified"]:
                winner = result
                snapshot = after
                break
        evidence["type_attempts"] = attempts
        evidence["verdict"]["email_write_variant"] = winner["label"] if winner else None

        # --- click probe: Pay now with a fresh ref must raise the page's own
        # validation banner; that banner text in a FRESH snapshot is the
        # postcondition (a real typed click with an observable page effect).
        # Refs are snapshot-scoped, so the ref is taken immediately before the
        # click from the newest snapshot (a stale ref was the earlier mistake).
        click_result: dict[str, Any] = {}
        pre_click = _snapshot(sandbox, driver, target_id, tab_id, session, "click-probe-before")
        click_result["before_frame"] = pre_click.pop("_frame", None)
        pay_ref = _ref_by_name(pre_click, "pay now")
        if pay_ref is not None:
            click_result["ref"] = pay_ref.get("ref")
            click_result["call"] = driver.probe(
                "browser_click",
                {
                    "ref": pay_ref.get("ref"),
                    "input_route": "dom_event",
                    "target_id": target_id,
                    "tab_id": tab_id,
                },
                session=session,
            )
            clicked = _snapshot(sandbox, driver, target_id, tab_id, session, "click-probe-after")
            click_result["after_frame"] = clicked.pop("_frame", None)
            searchable = [
                str(ref.get("name"))
                for key in ("refs", "content_refs")
                for ref in (clicked.get(key) or [])
                if isinstance(ref, dict)
            ]
            click_result["banner_matches"] = [
                name for name in searchable if "required" in name.lower()
            ]
            click_result["verified"] = any(
                "email and delivery address are required" in name.lower()
                for name in searchable
            )
            click_result["url_after"] = base._pick(clicked, "url")
            evidence["click_probe"] = click_result
            evidence["verdict"]["click_effect"] = (click_result["call"].get("data") or {}).get(
                "effect"
            )
            evidence["verdict"]["click_postcondition_verified"] = bool(click_result["verified"])

        # With the winning shape, complete a real checkout through Jev actions.
        completed: list[str] = []
        actions: list[dict[str, Any]] = []
        decision_records: list[dict[str, Any]] = []
        if winner is not None:
            goal = (
                "Complete one checkout of SKU-A quantity 1 and reach a paid state, "
                "using only the supplied actions."
            )
            for step in range(1, 6):
                observation = base.compact_observation(snapshot, completed)
                observation_hash = hashlib.sha256(
                    json.dumps(observation, sort_keys=True).encode()
                ).hexdigest()
                candidates = base.build_candidates(snapshot, _FIXTURE_EMAIL)
                address_ref = _ref_by_name(snapshot, "delivery address")
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
                email_now = _email_ref(snapshot)
                address_now = _ref_by_name(snapshot, "delivery address")
                if (
                    (email_now or {}).get("value") == _FIXTURE_EMAIL
                    and (address_now or {}).get("value") == _FIXTURE_ADDRESS
                ):
                    pay_ref = _ref_by_name(snapshot, "pay now")
                    if pay_ref is not None:
                        candidates["pay_now"] = {
                            "description": (
                                "Click the visible Pay now button to submit the checkout."
                            ),
                            "tool": "browser_click",
                            "ref": pay_ref.get("ref"),
                            "args": {
                                "ref": pay_ref.get("ref"),
                                "input_route": "dom_event",
                            },
                        }
                for item in candidates.values():
                    if item.get("tool") in ("browser_type", "browser_click"):
                        item["args"].setdefault("target_id", target_id)
                        item["args"].setdefault("tab_id", tab_id)
                decision = base.jev_choose(goal, observation, candidates)
                answer = (
                    decision.get("answer") if isinstance(decision.get("answer"), dict) else {}
                )
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
                if choice == "fill_email" and winner["label"] != "replace_true":
                    # Reuse only the proven shape for the email field.
                    selected_candidate["args"] = dict(winner["args"])
                    selected_candidate["args"].setdefault("target_id", target_id)
                    selected_candidate["args"].setdefault("tab_id", tab_id)
                judged = snapshot
                frame_at_ns = time.monotonic_ns()
                frame_path = f"/run/nightwatch/frames/final-{step:02d}-before.png"
                driver.call(
                    str(selected_candidate["tool"]),
                    dict(selected_candidate["args"]),
                    session=session,
                )
                after = _snapshot(
                    sandbox, driver, target_id, tab_id, session, f"final-{step:02d}-after"
                )
                action_frame = after.pop("_frame", None)
                expected_role = expected_name = None
                for ref_item in base._refs(judged):
                    if ref_item.get("ref") == selected_candidate.get("ref"):
                        expected_role = ref_item.get("role")
                        expected_name = ref_item.get("name")
                        break
                post_ref = next(
                    (
                        item
                        for item in base._refs(after)
                        if item.get("role") == expected_role
                        and item.get("name") == expected_name
                    ),
                    None,
                )
                record["executed"] = True
                record["action"] = choice
                actions.append(
                    {
                        "step": step,
                        "candidate": choice,
                        "confidence": answer.get("confidence"),
                        "probabilities": answer.get("probabilities"),
                        "after_frame": action_frame,
                        "postcondition": {
                            "kind": "element_state",
                            "expected_name": expected_name,
                            "value": (post_ref or {}).get("value"),
                            "verified": (post_ref or {}).get("value")
                            in (_FIXTURE_EMAIL, _FIXTURE_ADDRESS),
                            "url_after": base._pick(after, "url"),
                        },
                    }
                )
                completed.append(choice)
                snapshot = after
                if choice == "pay_now":
                    break
        evidence["decisions"] = decision_records
        evidence["actions"] = actions
        evidence["verdict"]["jev_live_choice"] = bool(decision_records)
        evidence["verdict"]["action_executed"] = any(
            record.get("executed") for record in decision_records
        )
        evidence["verdict"]["element_postcondition_verified"] = any(
            action["postcondition"]["verified"] for action in actions
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
        with contextlib.suppress(Exception):
            driver.probe("end_session", {}, session=session)
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
        evidence["verdict"].get("email_write_variant")
        and evidence["verdict"].get("element_postcondition_verified")
        and not evidence.get("errors")
    )
    artifacts_dir = _REPO_ROOT / "artifacts"
    artifacts_dir.mkdir(exist_ok=True)
    artifact_path = artifacts_dir / f"browser_type_{int(evidence['started_unix_s'])}.json"
    evidence["artifact_path"] = str(artifact_path)
    artifact_path.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(json.dumps(evidence, indent=2, default=str))
    if not evidence["verdict"]["probe_passed"]:
        raise SystemExit(1)
