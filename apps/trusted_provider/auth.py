"""Scoped provider-token minting and verification (plan §9.3).

Tokens are HMAC-signed claims bound to one run/candidate/scenario namespace,
its allowed operation IDs and an expiry. Candidate tokens cannot call evaluator
or namespace-management routes. ``*`` in ``allowed_operation_ids`` means "any
operation within this namespace" and is used for UI-driven worlds where the
intent IDs are created during the journey.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime

from apps.contracts.payment import ProviderTokenClaims

__all__ = ["TokenError", "mint_token", "verify_token"]

TOKEN_PREFIX = "nw1"


class TokenError(Exception):
    """Malformed, forged or expired scoped token."""


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(payload_b64: str, signing_secret: str) -> bytes:
    key = signing_secret.encode("utf-8")
    return hmac.new(key, payload_b64.encode("ascii"), hashlib.sha256).digest()


def mint_token(claims: ProviderTokenClaims, signing_secret: str) -> str:
    if not signing_secret:
        raise TokenError("provider signing secret is not configured")
    payload_b64 = _b64_encode(claims.model_dump_json().encode("utf-8"))
    signature = _sign(payload_b64, signing_secret)
    return f"{TOKEN_PREFIX}.{payload_b64}.{_b64_encode(signature)}"


def verify_token(
    token: str,
    signing_secret: str,
    *,
    now: datetime | None = None,
) -> ProviderTokenClaims:
    if not signing_secret:
        raise TokenError("provider signing secret is not configured")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise TokenError("malformed token")
    payload_b64, signature_b64 = parts[1], parts[2]
    try:
        supplied = _b64_decode(signature_b64)
    except Exception as exc:  # noqa: BLE001 - any decode failure is a malformed token
        raise TokenError("malformed token signature") from exc
    # URL-safe base64 without padding can have multiple textual spellings for
    # the same bytes when the unused tail bits are changed. Reject those
    # non-canonical spellings before comparing the decoded signature so a
    # changed token string is always treated as tampering.
    if _b64_encode(supplied) != signature_b64:
        raise TokenError("malformed token signature")
    if not hmac.compare_digest(supplied, _sign(payload_b64, signing_secret)):
        raise TokenError("token signature does not verify")
    try:
        claims = ProviderTokenClaims.model_validate_json(_b64_decode(payload_b64), strict=True)
    except Exception as exc:  # noqa: BLE001 - any payload failure is a malformed token
        raise TokenError("malformed token payload") from exc
    reference = now or datetime.now(UTC)
    if claims.expires_at_utc <= reference:
        raise TokenError("token expired")
    return claims
