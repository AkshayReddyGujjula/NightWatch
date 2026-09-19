"""Scoped provider token tests (plan §9.3)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.contracts.payment import ProviderTokenClaims
from apps.trusted_provider.auth import TokenError, mint_token, verify_token

SECRET = "unit-test-signing-secret"


def claims(*, expires_in_seconds: int = 60) -> ProviderTokenClaims:
    return ProviderTokenClaims(
        incident_id="NW-001",
        candidate_id="B",
        scenario_id="S02",
        namespace="ns-cand-b",
        allowed_operation_ids=["op_1"],
        expires_at_utc=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
    )


def test_roundtrip_preserves_claims() -> None:
    token = mint_token(claims(), SECRET)
    parsed = verify_token(token, SECRET)
    assert parsed.namespace == "ns-cand-b"
    assert parsed.allowed_operation_ids == ["op_1"]


def test_rejects_tampered_signature() -> None:
    token = mint_token(claims(), SECRET)
    tampered = token[:-1] + ("a" if token[-1] != "a" else "b")
    with pytest.raises(TokenError):
        verify_token(tampered, SECRET)


def test_rejects_wrong_secret() -> None:
    token = mint_token(claims(), SECRET)
    with pytest.raises(TokenError):
        verify_token(token, "another-secret")


def test_rejects_expired_token() -> None:
    token = mint_token(claims(expires_in_seconds=-5), SECRET)
    with pytest.raises(TokenError):
        verify_token(token, SECRET)


def test_rejects_malformed_token() -> None:
    with pytest.raises(TokenError):
        verify_token("not-a-token", SECRET)


def test_minting_requires_a_secret() -> None:
    with pytest.raises(TokenError):
        mint_token(claims(), "")


def test_verifying_requires_a_secret() -> None:
    with pytest.raises(TokenError):
        verify_token(mint_token(claims(), SECRET), "")
