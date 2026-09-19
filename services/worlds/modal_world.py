"""Track B — one isolated Modal Sandbox per candidate world (plan §12.2).

The lifecycle proven in the §11.8 gate, productized: create exactly one Sandbox
from the pinned desktop image, drop privileges through the bootstrap script,
inject the candidate payload, start the candidate app as ``nightwatch_app`` and
record measured lifecycle facts. Scenario execution, the Jev decision loop and
oracle calls stay in the trusted runner — this class moves bytes and processes,
it never grades.

Reduced mode: when ``payload.browser_enabled`` is False the world boots
X11/D-Bus/app only (``NW_BROWSER_ENABLED=0``) and is fully usable for API
scenarios; the browser stack is added back when the CUA gate is green.
"""

from __future__ import annotations

import base64
import json
import shlex
import time
from datetime import UTC, datetime
from typing import Any

import modal
from apps.contracts.incident import CandidateSpec
from infra.modal_desktop_image import DESKTOP_IMAGE
from services.worlds.interface import (
    CandidatePayload,
    WorldError,
    WorldLifecycle,
)

_WORLD_EVIDENCE_PATH = "/run/nightwatch/world-evidence.json"


def _read_stream(stream: Any) -> str:
    data = stream.read()
    return data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)


class ModalWorld:
    """Lifecycle for exactly one candidate world inside one Modal Sandbox."""

    name = "modal"

    def __init__(
        self,
        *,
        app: modal.App,
        payload: CandidatePayload,
        environment: str,
        timeout_s: int = 1200,
        idle_timeout_s: int = 600,
        bootstrap_timeout_s: int = 420,
    ) -> None:
        self._app = app
        self._payload = payload
        self.environment = environment
        self.image_digest: str | None = None
        self._timeout_s = timeout_s
        self._idle_timeout_s = idle_timeout_s
        self._bootstrap_timeout_s = bootstrap_timeout_s
        self._sandbox: modal.Sandbox | None = None
        self._sandbox_id: str | None = None
        self._world_evidence: dict[str, Any] = {}
        self._candidate_id = ""
        self.created_monotonic_ns: int | None = None
        self.ready_monotonic_ns: int | None = None
        self.created_at_utc: datetime | None = None
        self.ready_at_utc: datetime | None = None
        self.finished_at_utc: datetime | None = None

    # -- lifecycle -----------------------------------------------------------

    def start(self, spec: CandidateSpec) -> WorldLifecycle:
        """Create the sandbox, inject the payload and boot the world."""
        self._validate_spec(spec)
        self._candidate_id = spec.candidate_id
        created_ns = time.monotonic_ns()
        self.created_at_utc = datetime.now(UTC)
        sandbox = modal.Sandbox.create(
            app=self._app,
            image=DESKTOP_IMAGE,
            timeout=self._timeout_s,
            idle_timeout=self._idle_timeout_s,
        )
        self._sandbox = sandbox
        self._sandbox_id = sandbox.object_id
        self.created_monotonic_ns = created_ns
        try:
            self.image_digest = DESKTOP_IMAGE.object_id
        except AttributeError:
            # The image is hydrated only after the backend resolves it.
            self.image_digest = "unresolved"
        try:
            for remote_path, content in self._payload.files.items():
                self._write_file(remote_path, content)
            code, stdout, stderr = self._exec_root(
                "/opt/nightwatch/start_desktop_world.sh",
                env={
                    "NW_APP_PORT": str(self._payload.app_port),
                    "NW_APP_DIR": "/opt/nightwatch/app",
                    "NW_APP_CMD": self._payload.start_command,
                    "NW_APP_READY_PATH": self._payload.ready_path,
                    "NW_BROWSER_ENABLED": "1" if self._payload.browser_enabled else "0",
                },
                timeout=self._bootstrap_timeout_s,
            )
            if code != 0:
                raise WorldError(
                    f"world bootstrap failed: {(stderr or stdout)[-500:]}"
                )
            evidence_code, evidence_text, _ = self._exec_root(
                "cat", _WORLD_EVIDENCE_PATH, timeout=30
            )
            if evidence_code != 0:
                raise WorldError("world evidence file missing after bootstrap")
            self._world_evidence = json.loads(evidence_text)
            self.ready_monotonic_ns = time.monotonic_ns()
            self.ready_at_utc = datetime.now(UTC)
            return self.lifecycle(terminated=False)
        except Exception as error:  # noqa: BLE001 - cleanup then re-raise
            self.stop()
            if isinstance(error, WorldError):
                raise
            raise WorldError(f"{type(error).__name__}: {error}") from error

    def stop(self) -> WorldLifecycle:
        """Idempotent teardown; the sandbox is always terminated."""
        self.finished_at_utc = datetime.now(UTC)
        sandbox = self._sandbox
        if sandbox is not None:
            try:
                sandbox.terminate()
            except Exception:  # noqa: BLE001 - teardown is best effort, then reflected
                return self.lifecycle(terminated=False, cleanup_note="terminate raised")
            self._sandbox = None
        return self.lifecycle(terminated=True)

    def lifecycle(
        self, *, terminated: bool, cleanup_note: str | None = None
    ) -> WorldLifecycle:
        return WorldLifecycle(
            candidate_id=self._candidate_id,
            sandbox_id=self.sandbox_id,
            created_monotonic_ns=self.created_monotonic_ns,
            ready_monotonic_ns=self.ready_monotonic_ns,
            finished_monotonic_ns=time.monotonic_ns(),
            created_at_utc=self.created_at_utc,
            ready_at_utc=self.ready_at_utc,
            finished_at_utc=self.finished_at_utc,
            terminated=terminated,
            cleanup_note=cleanup_note,
        )

    # -- accessors for the trusted runner ------------------------------------

    @property
    def sandbox_id(self) -> str | None:
        """The sandbox id, kept after teardown so lifecycle records stay complete."""
        if self._sandbox is not None:
            return self._sandbox.object_id
        return self._sandbox_id

    @property
    def world_evidence(self) -> dict[str, Any]:
        return dict(self._world_evidence)

    def exec_root(
        self, *argv: str, env: dict[str, str | None] | None = None, timeout: int = 120
    ) -> tuple[int, str, str]:
        """Run argv as root inside the sandbox (bootstrap/cleanup only)."""
        return self._exec_root(*argv, env=env, timeout=timeout)

    def exec_controller(self, *argv: str, timeout: int = 120) -> tuple[int, str, str]:
        """Run argv as the controller identity with the world's display/D-Bus env."""
        return self._exec_root(
            "/run/nightwatch/as_controller.sh", *argv, timeout=timeout
        )

    # -- internals -----------------------------------------------------------

    def _validate_spec(self, spec: CandidateSpec) -> None:
        if self._payload.code_hash and spec.code_hash != self._payload.code_hash:
            raise WorldError("candidate code_hash does not match the injected payload")
        if self._payload.seed_hash and spec.seed_hash != self._payload.seed_hash:
            raise WorldError("candidate seed_hash does not match the injected payload")

    def _exec_root(
        self, *argv: str, env: dict[str, str | None] | None = None, timeout: int = 120
    ) -> tuple[int, str, str]:
        sandbox = self._require_sandbox()
        process = sandbox.exec(*argv, env=env, timeout=timeout)
        stdout = _read_stream(process.stdout)
        stderr = _read_stream(process.stderr)
        return process.wait(), stdout, stderr

    def _require_sandbox(self) -> modal.Sandbox:
        if self._sandbox is None:
            raise WorldError("world is not running")
        return self._sandbox

    def _write_file(self, remote_path: str, content: str) -> None:
        """Write one UTF-8 file via base64 over an argument-array exec."""
        quoted_path = shlex.quote(remote_path)
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        command = (
            f"mkdir -p \"$(dirname {quoted_path})\" && "
            f"printf %s {shlex.quote(encoded)} | base64 -d > {quoted_path}"
        )
        code, _, stderr = self._exec_root("bash", "-lc", command, timeout=60)
        if code != 0:
            raise WorldError(f"could not write {remote_path}: {stderr[-200:]}")
