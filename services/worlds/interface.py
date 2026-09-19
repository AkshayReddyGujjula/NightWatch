"""Track B — world-runner interface (plan §12, §16.1, §17).

A WorldRunner owns exactly one isolated candidate world per call: one Modal
Sandbox with its own app database, provider namespace and — when the browser
stack is green — its own Chromium profile and CUA session. Every model and
evidence credential stays in the trusted runner outside the sandbox; a world
returns only measured facts and a :class:`CandidateEvaluation`.

Worlds never score themselves: the verdict comes from the trusted oracle's
evidence set, and this interface carries no success flag a world could forge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from apps.contracts.evaluation import CandidateEvaluation
from apps.contracts.incident import CandidateSpec


class WorldError(RuntimeError):
    """A world could not be created, driven or cleaned up. Never a pass."""


@dataclass(frozen=True)
class CandidatePayload:
    """Candidate app bytes and start command, injected by the trusted runner.

    ``files`` maps an absolute remote path to UTF-8 content; binary assets are
    not expected in the candidate bundle. ``code_hash``/``seed_hash`` are
    optional expectations validated against the spec when set (empty string
    means "not pinned yet" while Track A's bundle lands).
    """

    files: dict[str, str]
    start_command: str
    ready_path: str = "/"
    app_port: int = 8080
    browser_enabled: bool = False
    code_hash: str = ""
    seed_hash: str = ""


@dataclass(frozen=True)
class WorldLifecycle:
    """Measured lifecycle facts for the dashboard and the receipt (plan §12.3)."""

    candidate_id: str
    sandbox_id: str | None = None
    created_monotonic_ns: int | None = None
    ready_monotonic_ns: int | None = None
    finished_monotonic_ns: int | None = None
    terminated: bool = False
    startup_error: str | None = None
    cleanup_note: str | None = None

    @property
    def startup_span_ns(self) -> int | None:
        """Sandbox-create to app-ready span, from monotonic nanoseconds."""
        if self.created_monotonic_ns is None or self.ready_monotonic_ns is None:
            return None
        return self.ready_monotonic_ns - self.created_monotonic_ns


@dataclass(frozen=True)
class WorldOutcome:
    """One world's evaluation plus its lifecycle record."""

    evaluation: CandidateEvaluation
    lifecycle: WorldLifecycle


@runtime_checkable
class WorldRunner(Protocol):
    """Implemented by ModalWorld (production) and LocalWorld (labelled dev fallback)."""

    name: str

    def run(self, spec: CandidateSpec) -> WorldOutcome: ...
