"""Shared strict primitives for every boundary model (plan §7).

All boundary models inherit :class:`StrictModel`: extra fields forbidden,
strict types, immutable. JSON call sites must additionally validate with
``model_validate_json(..., strict=True)`` because JSON strictness differs from
Python-object strictness (plan §7).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

__all__ = [
    "CandidateId",
    "Hash256",
    "IdStr",
    "MonotonicNs",
    "NonEmptyStr",
    "ScenarioId",
    "StrictModel",
    "UtcDatetime",
    "ensure_utc",
    "sha256_hex",
]

CandidateId = Literal["A", "B", "C"]

ScenarioId = Literal["S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08"]

# Lowercase 64-character SHA-256 hex digest.
Hash256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]

# Opaque identifier: non-empty, bounded. Deliberately pattern-free so that real
# sandbox/session/snapshot IDs can never fail a contract for formatting.
IdStr = Annotated[str, StringConstraints(min_length=1, max_length=128)]

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, max_length=512)]

# Monotonic integer nanoseconds (plan §7).
MonotonicNs = Annotated[int, Field(ge=0)]


def ensure_utc(value: datetime) -> datetime:
    """Reject naive datetimes and normalise timezone-aware values to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware (UTC)")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(ensure_utc)]


def sha256_hex(data: bytes) -> str:
    """Canonical lowercase SHA-256 digest used across evidence boundaries."""
    return hashlib.sha256(data).hexdigest()


class StrictModel(BaseModel):
    """Boundary model: extra fields forbidden, strict types, immutable (plan §7)."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
