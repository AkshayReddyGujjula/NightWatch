"""Build the candidate application bundle injected into a world.

Track B owns packaging. The builder never edits Track A source: it copies the
reviewed contracts, live-store package and storefront into an isolated payload,
then selects only a supported router mode in a generated bootstrap module.
"""

from __future__ import annotations

from pathlib import Path

from apps.contracts.incident import CandidateSpec
from services.oracle import live_store_code_hash
from services.worlds.interface import CandidatePayload

_ROOT = Path(__file__).resolve().parents[2]
_REMOTE_ROOT = Path("/opt/nightwatch/app")
_TEXT_SUFFIXES = {".css", ".html", ".js", ".json", ".py"}


class CandidatePayloadUnavailable(ValueError):
    """A candidate cannot be packaged without inventing untrusted bytes."""


def _remote_path(relative: Path) -> str:
    return str(_REMOTE_ROOT / relative).replace("\\", "/")


def _copy_tree(relative_root: str) -> dict[str, str]:
    source_root = _ROOT / relative_root
    if not source_root.is_dir():
        raise CandidatePayloadUnavailable(f"candidate source tree is missing: {relative_root}")
    files: dict[str, str] = {}
    for source in sorted(source_root.rglob("*")):
        if not source.is_file() or source.suffix not in _TEXT_SUFFIXES:
            continue
        relative = source.relative_to(_ROOT)
        files[_remote_path(relative)] = source.read_text(encoding="utf-8")
    return files


def _safe_bootstrap() -> str:
    return '''"""Generated Track B bootstrap for Candidate B."""
from datetime import UTC, datetime, timedelta

from apps.live_store.app import StoreSettings, create_app
from apps.live_store.router import handler_hash_for

app = create_app(
    StoreSettings(
        store_db_path="/opt/nightwatch/app/candidate.db",
        storefront_dir="/opt/nightwatch/app/apps/storefront",
    )
)
state = app.state.store.router_state()
app.state.store.set_router(
    mode="SAFE",
    expected_generation=state.generation,
    handler_hash=handler_hash_for("SAFE"),
    lease_id="candidate-b-evaluation",
    lease_expires_at=datetime.now(UTC) + timedelta(minutes=15),
)
'''


def build_candidate_payload(spec: CandidateSpec) -> CandidatePayload:
    """Return the exact app bytes and start command for ``spec``.

    Candidate B is available from the committed safe handler. Candidate A
    remains unavailable until a concrete previous-release source/ref is
    supplied; the installed router explicitly rejects ``LEGACY``. Candidate C
    remains unavailable until the guarded patch bytes are carried by the spec.
    Both cases fail closed instead of substituting another candidate.
    """
    if spec.kind == "ROLLBACK":
        raise CandidatePayloadUnavailable(
            "candidate A requires a concrete previous-release source/ref; LEGACY is not installed"
        )
    if spec.kind == "GEMINI_PATCH":
        raise CandidatePayloadUnavailable(
            "candidate C has no guarded patch bytes in CandidateSpec; keep it SKIPPED_INVALID"
        )

    expected_hash = live_store_code_hash()
    if spec.code_hash != expected_hash:
        raise CandidatePayloadUnavailable(
            "candidate B code_hash does not match the packaged live-store bundle"
        )
    files: dict[str, str] = {}
    for tree in ("apps/contracts", "apps/live_store", "apps/storefront"):
        files.update(_copy_tree(tree))
    files[_remote_path(Path("candidate_boot.py"))] = _safe_bootstrap()
    return CandidatePayload(
        files=files,
        start_command=(
            "python3 -m uvicorn candidate_boot:app --host 127.0.0.1 --port 8080"
        ),
        ready_path="/health",
        browser_enabled=True,
        code_hash=expected_hash,
    )
