"""Stage-dashboard polish and engineer-report contracts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _load_demo_server() -> ModuleType:
    path = ROOT / "demo-target" / "server.py"
    spec = importlib.util.spec_from_file_location("nightwatch_demo_server_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _diagnosis() -> dict[str, Any]:
    return {
        "root_cause": "One operation used a fresh idempotency key for each retry.",
        "fixes": [
            {"candidate_id": "A", "strategy": "Rollback."},
            {"candidate_id": "B", "strategy": "Activate the stable safe handler."},
            {"candidate_id": "C", "strategy": "Generate a bounded patch."},
        ],
    }


def test_payment_engineer_report_contains_exact_diff_and_customer_recovery() -> None:
    module = _load_demo_server()
    module._state = {"incident_type": "DOUBLE_CHARGE", "gemini": _diagnosis()}

    report = module._build_engineer_report(
        {"A": 0, "B": 0, "C": 0},
        {"refund_amount_minor": 7999},
        {"mode": "SAFE"},
    )

    assert report["title"] == "Payment retry repair"
    assert "used_key = retry_key" in report["applied_diff"]
    assert "provider.captures(operation_id)" in report["applied_diff"]
    assert "refunded" in " ".join(report["verification"])
    assert report["fix"] == "Activate the stable safe handler."


def test_security_engineer_report_records_outage_recovery_diff() -> None:
    module = _load_demo_server()
    module._state = {
        "incident_type": "SCRIPTED_SECURITY_CRASH",
        "gemini": _diagnosis(),
    }

    report = module._build_engineer_report(
        {"A": 0, "B": 0, "C": 0}, None, {"mode": "SAFE"}
    )

    assert report["title"] == "Storefront availability repair"
    assert 'await _set_store_outage(False)' in report["applied_diff"]
    assert "HTTP 200" in " ".join(report["verification"])


def test_dashboard_has_live_monitoring_report_and_no_clock() -> None:
    dashboard = (ROOT / "demo-target" / "dashboard.html").read_text(encoding="utf-8")

    assert "Monitoring NightMart" in dashboard
    assert 'id="watch-value"' in dashboard
    assert 'id="engineer-report"' in dashboard
    assert "Exact activated code diff" in dashboard
    assert ".step > span:last-child" in dashboard
    assert 'id="updated"' not in dashboard
    assert 'class="clock"' not in dashboard
