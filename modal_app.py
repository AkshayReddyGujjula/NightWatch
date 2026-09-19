"""Thin Modal entrypoint (plan §16): import wiring only.

Loads both service modules so every frozen exported function registers on the
single ``nightwatch`` App owned by ``modal/services_a.py``. The ``sys.path``
shim exists because this repository's ``modal/`` directory is a namespace
portion that the installed ``modal`` SDK (a regular package) always shadows —
the frozen ``from modal.services_a import app`` spelling cannot resolve in this
repository (verified live; recorded in ``CONTRACT_CHANGE.md``). File paths and
the one-App shape are unchanged. Never create a second ``modal.App``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SERVICES_DIR = Path(__file__).resolve().parent / "modal"
if str(_SERVICES_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICES_DIR))

import services_a  # noqa: E402,F401  — defines the single `app`
import services_b  # noqa: E402,F401  — binds run_candidate to services_a.app
from services_a import app  # noqa: E402,F401  — re-exported for modal run/deploy

__all__ = ["app"]
