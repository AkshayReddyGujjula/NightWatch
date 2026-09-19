"""Handler-level tests for the buggy and safe retry paths (plan §5.1, §5.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from apps.contracts.payment import CaptureResponse, CaptureRow
from apps.live_store.domain.payment_retry import (
    ProviderRejected,
    ProviderUncertain,
    buggy_retry_checkout,
    safe_retry_checkout,
)


def capture_response(capture_id: str = "cap_1") -> CaptureResponse:
    return CaptureResponse(
        capture_id=capture_id,
        operation_id="op_1",
        amount_minor=7999,
        currency="GBP",
        replayed=False,
    )


def capture_row(
    capture_id: str = "cap_1", key: str = "key", amount_minor: int = 7999
) -> CaptureRow:
    return CaptureRow(
        capture_id=capture_id,
        namespace="ns_unit",
        operation_id="op_1",
        idempotency_key=key,
        amount_minor=amount_minor,
        currency="GBP",
        captured_at=datetime.now(UTC),
    )


@dataclass
class FakeProvider:
    """Scripted provider: each call pops the next outcome or raises it."""

    outcomes: list[object] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)

    async def capture(
        self,
        operation_id: str,
        idempotency_key: str,
        amount_minor: int,
        currency: str,
        intent_id: str,
    ) -> CaptureResponse:
        self.calls.append(idempotency_key)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def captures(self, operation_id: str) -> list[CaptureRow]:
        self.calls.append(f"inquiry:{operation_id}")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


async def test_buggy_retries_with_a_fresh_key_after_a_lost_response() -> None:
    provider = FakeProvider(
        outcomes=[
            ProviderUncertain("lost"),
            capture_response("cap_2"),
            [capture_row("cap_1", "key_1"), capture_row("cap_2", "key_2")],
        ]
    )
    persisted: list[str] = []

    outcome = await buggy_retry_checkout(
        provider,
        operation_id="op_1",
        amount_minor=7999,
        currency="GBP",
        intent_id="pi_1",
        attempt_keys=["key_1", "key_2"],
        persist_key=persisted.append,
    )

    assert outcome.status == "PAID"
    assert persisted == ["key_1", "key_2"]
    assert outcome.idempotency_key == "key_2"
    assert outcome.reason is not None
    assert "You were charged twice" in outcome.reason
    assert provider.calls == ["key_1", "key_2", "inquiry:op_1"]


async def test_buggy_second_uncertainty_stays_pending() -> None:
    provider = FakeProvider(outcomes=[ProviderUncertain("lost"), ProviderUncertain("lost")])
    persisted: list[str] = []

    outcome = await buggy_retry_checkout(
        provider,
        operation_id="op_1",
        amount_minor=7999,
        currency="GBP",
        intent_id="pi_1",
        attempt_keys=["key_1", "key_2"],
        persist_key=persisted.append,
    )

    assert outcome.status == "PENDING_CONFIRMATION"
    assert persisted == ["key_1", "key_2"]


async def test_buggy_rejection_fails_once() -> None:
    provider = FakeProvider(outcomes=[ProviderRejected("declined")])
    persisted: list[str] = []

    outcome = await buggy_retry_checkout(
        provider,
        operation_id="op_1",
        amount_minor=7999,
        currency="GBP",
        intent_id="pi_1",
        attempt_keys=["key_1", "key_2"],
        persist_key=persisted.append,
    )

    assert outcome.status == "FAILED"
    assert persisted == ["key_1"]


async def test_safe_recovers_via_inquiry_after_a_lost_response() -> None:
    provider = FakeProvider(outcomes=[ProviderUncertain("lost"), [capture_row()]])
    persisted: list[str] = []

    outcome = await safe_retry_checkout(
        provider,
        operation_id="op_1",
        amount_minor=7999,
        currency="GBP",
        intent_id="pi_1",
        stable_key="key_stable",
        persist_key=persisted.append,
    )

    assert outcome.status == "PAID"
    assert outcome.capture_id == "cap_1"
    assert persisted == ["key_stable"]
    assert provider.calls == ["key_stable", "inquiry:op_1"]


async def test_safe_stays_pending_when_no_capture_exists() -> None:
    provider = FakeProvider(outcomes=[ProviderUncertain("lost"), []])

    outcome = await safe_retry_checkout(
        provider,
        operation_id="op_1",
        amount_minor=7999,
        currency="GBP",
        intent_id="pi_1",
        stable_key="key_stable",
        persist_key=lambda _key: None,
    )

    assert outcome.status == "PENDING_CONFIRMATION"


async def test_safe_stays_pending_when_the_lookup_is_unavailable() -> None:
    provider = FakeProvider(outcomes=[ProviderUncertain("lost"), ProviderUncertain("down")])

    outcome = await safe_retry_checkout(
        provider,
        operation_id="op_1",
        amount_minor=7999,
        currency="GBP",
        intent_id="pi_1",
        stable_key="key_stable",
        persist_key=lambda _key: None,
    )

    assert outcome.status == "PENDING_CONFIRMATION"


async def test_safe_quarantines_on_multiple_captures() -> None:
    provider = FakeProvider(
        outcomes=[ProviderUncertain("lost"), [capture_row("cap_1"), capture_row("cap_2")]]
    )

    outcome = await safe_retry_checkout(
        provider,
        operation_id="op_1",
        amount_minor=7999,
        currency="GBP",
        intent_id="pi_1",
        stable_key="key_stable",
        persist_key=lambda _key: None,
    )

    assert outcome.status == "QUARANTINED"


async def test_safe_quarantines_on_amount_mismatch() -> None:
    provider = FakeProvider(outcomes=[ProviderUncertain("lost"), [capture_row(amount_minor=1)]])

    outcome = await safe_retry_checkout(
        provider,
        operation_id="op_1",
        amount_minor=7999,
        currency="GBP",
        intent_id="pi_1",
        stable_key="key_stable",
        persist_key=lambda _key: None,
    )

    assert outcome.status == "QUARANTINED"


async def test_safe_rejection_fails_without_inquiry() -> None:
    provider = FakeProvider(outcomes=[ProviderRejected("declined")])

    outcome = await safe_retry_checkout(
        provider,
        operation_id="op_1",
        amount_minor=7999,
        currency="GBP",
        intent_id="pi_1",
        stable_key="key_stable",
        persist_key=lambda _key: None,
    )

    assert outcome.status == "FAILED"
    assert provider.calls == ["key_stable"]
