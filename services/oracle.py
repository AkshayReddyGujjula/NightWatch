"""Trusted deterministic oracle and isolated API-scenario executor.

The candidate app never supplies a verdict.  This module consumes only the
provider's append-only ledger, evaluator-only store facts, trusted API trace
metadata and frozen hashes.  It also owns the exact evidence-set validator:
an empty or partial matrix is always an error, never a vacuous pass.
"""

from __future__ import annotations

import asyncio
import secrets
import shutil
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx

from apps.contracts.base import canonical_sha256, sha256_hex
from apps.contracts.control import NegativeControlResult
from apps.contracts.evaluation import (
    CandidateEvaluation,
    InvariantId,
    InvariantResult,
    InvariantStatus,
    Scenario,
    ScenarioRegistry,
    ScenarioResult,
)
from apps.contracts.incident import CandidateSpec
from apps.contracts.payment import (
    CaptureRow,
    IntentItem,
    LedgerView,
    RegistrationRow,
    StoreFacts,
)
from apps.live_store.app import StoreSettings
from apps.live_store.app import create_app as create_store_app
from apps.live_store.provider import HttpPaymentProvider
from apps.live_store.router import safe_handler_hash
from apps.live_store.store import Store
from apps.trusted_provider.app import ProviderSettings
from apps.trusted_provider.app import create_app as create_provider_app

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "fixtures" / "scenarios.json"
CHECKOUT_BODY = {
    "email": "fixture@example.com",
    "address": "1 Evidence Street, London",
}

DemoMode = Literal["FULL", "CORE"]
CORE_SCENARIO_IDS = frozenset({"S03", "S04", "S05", "S06", "S07", "S08"})


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _trusted_id(prefix: str, payload: Any) -> str:
    return f"{prefix}:{canonical_sha256(payload)}"


def load_registry(path: Path = REGISTRY_PATH) -> ScenarioRegistry:
    return ScenarioRegistry.model_validate_json(path.read_bytes(), strict=True)


def registry_hash(path: Path = REGISTRY_PATH) -> str:
    return sha256_hex(path.read_bytes())


def oracle_code_hash() -> str:
    return sha256_hex(Path(__file__).read_bytes())


def live_store_code_hash() -> str:
    files = sorted((ROOT / "apps" / "live_store").rglob("*.py"))
    material = b"".join(
        path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes() + b"\0"
        for path in files
    )
    return sha256_hex(material)


@dataclass(frozen=True)
class ScenarioEvidence:
    candidate_id: str
    scenario: Scenario
    namespace: str
    store_facts: StoreFacts
    ledger: LedgerView
    http_statuses: tuple[int, ...]
    reported_status: str | None
    expected_stock: int | None
    original_namespace: str
    original_digest_before: str
    original_digest_after: str
    trace_facts: dict[str, str]
    refund_replay_unchanged: bool | None = None
    browser_error: str | None = None

    @property
    def store_evidence_id(self) -> str:
        return _trusted_id("store", self.store_facts.model_dump(mode="json"))

    @property
    def ledger_evidence_id(self) -> str:
        return f"ledger:{self.namespace}:{self.ledger.digest}"

    @property
    def trace_evidence_id(self) -> str:
        return _trusted_id(
            "trace",
            {
                "statuses": self.http_statuses,
                "reported_status": self.reported_status,
                "facts": self.trace_facts,
            },
        )

    @property
    def original_evidence_id(self) -> str:
        return f"original-ledger:{self.original_namespace}:{self.original_digest_after}"


class Oracle:
    """INV-01..06 plus exact-set candidate grading."""

    def __init__(self, registry: ScenarioRegistry | None = None) -> None:
        self.registry = registry or load_registry()

    def evaluate(self, evidence: ScenarioEvidence, invariant_id: InvariantId) -> InvariantResult:
        method = getattr(self, f"_inv_{invariant_id[-2:]}")
        return method(evidence)

    @staticmethod
    def _result(
        invariant_id: InvariantId,
        status: InvariantStatus,
        expected: str,
        observed: str,
        evidence_ids: list[str],
    ) -> InvariantResult:
        if not evidence_ids:
            raise ValueError("oracle invariant results always require trusted evidence IDs")
        return InvariantResult(
            invariant_id=invariant_id,
            status=status,
            expected_summary=expected,
            observed_summary=observed,
            evidence_ids=evidence_ids,
        )

    def _inv_01(self, e: ScenarioEvidence) -> InvariantResult:
        registrations = [
            row
            for row in e.ledger.registrations
            if row.intent_id == e.store_facts.intent_id
        ]
        captures = [
            row
            for row in e.ledger.captures
            if e.store_facts.operation_id is None or row.operation_id == e.store_facts.operation_id
        ]
        counts = {
            "orders": e.store_facts.order_count,
            "operations": e.store_facts.operation_count,
            "registrations": len(registrations),
            "captures": len(captures),
            "confirmations": e.store_facts.confirmation_count,
        }
        passed = all(value <= 1 for value in counts.values())
        return self._result(
            "INV-01",
            "PASS" if passed else "FAIL",
            "at most one order, operation, capture and confirmation per logical intent",
            ", ".join(f"{key}={value}" for key, value in counts.items()),
            [e.store_evidence_id, e.ledger_evidence_id],
        )

    def _inv_02(self, e: ScenarioEvidence) -> InvariantResult:
        captures = len(e.ledger.captures)
        confirmations = e.store_facts.confirmation_count
        status = e.store_facts.order_status
        if status in {"PAID", "REFUNDED_PARTIAL", "REFUNDED_FULL"}:
            passed = captures == 1 and confirmations == 1
        elif status == "DECLINED":
            passed = captures == 0 and confirmations == 0
        elif status == "PENDING_CONFIRMATION":
            passed = captures <= 1 and confirmations == 0
        elif status in {"QUARANTINED", "SAFE_HOLD", None}:
            passed = confirmations == 0
        else:
            passed = False
        return self._result(
            "INV-02",
            "PASS" if passed else "FAIL",
            "application payment status must match capture and confirmation truth",
            f"status={status}, captures={captures}, confirmations={confirmations}",
            [e.store_evidence_id, e.ledger_evidence_id],
        )

    def _inv_03(self, e: ScenarioEvidence) -> InvariantResult:
        capture_total = sum(row.amount_minor for row in e.ledger.captures)
        refund_total = sum(row.amount_minor for row in e.ledger.refunds)
        positive = all(row.amount_minor > 0 for row in e.ledger.captures) and all(
            row.amount_minor > 0 for row in e.ledger.refunds
        )
        replay_ok = e.refund_replay_unchanged is not False
        passed = positive and refund_total <= capture_total and replay_ok
        return self._result(
            "INV-03",
            "PASS" if passed else "FAIL",
            "positive integer amounts, refunds capped by capture, replay appends nothing",
            (
                f"capture_total={capture_total}, refund_total={refund_total}, "
                f"replay_unchanged={e.refund_replay_unchanged}"
            ),
            [e.ledger_evidence_id, e.trace_evidence_id],
        )

    def _inv_04(self, e: ScenarioEvidence) -> InvariantResult:
        expected_stock = e.expected_stock
        passed = (
            e.store_facts.fulfillment_count == 1
            and expected_stock is not None
            and e.store_facts.stock_remaining == expected_stock
        )
        return self._result(
            "INV-04",
            "PASS" if passed else "FAIL",
            "one fulfillment and exactly one inventory decrement",
            (
                f"fulfillments={e.store_facts.fulfillment_count}, "
                f"stock={e.store_facts.stock_remaining}, expected_stock={expected_stock}"
            ),
            [e.store_evidence_id],
        )

    def _inv_05(self, e: ScenarioEvidence) -> InvariantResult:
        available = bool(e.http_statuses) and all(status < 500 for status in e.http_statuses)
        status_match = e.reported_status == e.store_facts.order_status
        payment_truth = self._inv_02(e).status == "PASS"
        passed = available and status_match and payment_truth and e.browser_error is None
        return self._result(
            "INV-05",
            "PASS" if passed else ("ERROR" if e.browser_error else "FAIL"),
            "journey available and reported state consistent with trusted payment evidence",
            (
                f"http={list(e.http_statuses)}, reported={e.reported_status}, "
                f"store={e.store_facts.order_status}, browser_error={e.browser_error}"
            ),
            [e.trace_evidence_id, e.store_evidence_id, e.ledger_evidence_id],
        )

    def _inv_06(self, e: ScenarioEvidence) -> InvariantResult:
        passed = (
            e.namespace != e.original_namespace
            and e.original_digest_before == e.original_digest_after
        )
        return self._result(
            "INV-06",
            "PASS" if passed else "FAIL",
            "original incident ledger immutable and separated from reproduction namespace",
            (
                f"separate={e.namespace != e.original_namespace}, "
                f"digest_unchanged={e.original_digest_before == e.original_digest_after}"
            ),
            [e.original_evidence_id, e.ledger_evidence_id],
        )

    def scenario_result(
        self,
        evidence: ScenarioEvidence,
        *,
        started_at: datetime,
        finished_at: datetime,
        capsule_sha256: str,
        seed_hash: str,
        code_hash: str,
        scenario_registry_hash: str,
        oracle_hash: str,
    ) -> ScenarioResult:
        invariants = [
            self.evaluate(evidence, invariant)
            for invariant in evidence.scenario.invariants
        ]
        if evidence.browser_error:
            status: InvariantStatus = "ERROR"
            failure_reason = evidence.browser_error
        elif any(result.status == "ERROR" for result in invariants):
            status = "ERROR"
            failure_reason = "oracle invariant error"
        elif any(result.status == "FAIL" for result in invariants):
            status = "FAIL"
            failure_reason = "one or more deterministic invariants failed"
        else:
            status = "PASS"
            failure_reason = None
        return ScenarioResult(
            candidate_id=evidence.candidate_id,  # type: ignore[arg-type]
            scenario_id=evidence.scenario.scenario_id,
            status=status,
            started_at_utc=started_at,
            finished_at_utc=finished_at,
            app_facts={
                "provider_namespace": evidence.namespace,
                "store_evidence_id": evidence.store_evidence_id,
                **evidence.trace_facts,
            },
            ledger_evidence_ids=[evidence.ledger_evidence_id],
            browser_trace_hash=(
                None if evidence.browser_error else sha256_hex(evidence.trace_evidence_id.encode())
            ),
            invariants=invariants,
            capsule_sha256=capsule_sha256,
            seed_hash=seed_hash,
            code_hash=code_hash,
            scenario_registry_hash=scenario_registry_hash,
            oracle_code_hash=oracle_hash,
            failure_reason=failure_reason,
        )

    def validate_evidence_set(
        self,
        spec: CandidateSpec,
        results: list[ScenarioResult],
        *,
        demo_mode: DemoMode = "FULL",
    ) -> list[str]:
        errors: list[str] = []
        required_scenarios = [
            scenario
            for scenario in self.registry.scenarios
            if demo_mode == "FULL" or scenario.scenario_id in CORE_SCENARIO_IDS
        ]
        if not required_scenarios:
            errors.append(f"{demo_mode} produced an empty required scenario set")
        expected = Counter(
            (spec.candidate_id, scenario.scenario_id, invariant)
            for scenario in required_scenarios
            for invariant in scenario.invariants
        )
        actual = Counter(
            (result.candidate_id, result.scenario_id, invariant.invariant_id)
            for result in results
            if any(
                scenario.scenario_id == result.scenario_id
                for scenario in required_scenarios
            )
            for invariant in result.invariants
        )
        if not expected:
            errors.append("registry produced an empty required evidence set")
        if actual != expected:
            missing = list((expected - actual).elements())
            extra = list((actual - expected).elements())
            errors.append(f"evidence matrix mismatch: missing={missing}, extra={extra}")
        known_ids = {scenario.scenario_id for scenario in self.registry.scenarios}
        all_result_ids = Counter(result.scenario_id for result in results)
        duplicates = {
            scenario_id: count
            for scenario_id, count in all_result_ids.items()
            if count != 1
        }
        if duplicates:
            errors.append(f"scenario results must be unique: {duplicates}")
        unexpected = sorted(set(all_result_ids) - known_ids)
        if unexpected:
            errors.append(f"unexpected scenario results: {unexpected}")
        result_ids = Counter(
            result.scenario_id
            for result in results
            if result.scenario_id in {scenario.scenario_id for scenario in required_scenarios}
        )
        expected_ids = Counter(scenario.scenario_id for scenario in required_scenarios)
        if result_ids != expected_ids:
            errors.append(
                f"required {demo_mode} scenario set mismatch: actual={dict(result_ids)}"
            )
        for result in results:
            if result.candidate_id != spec.candidate_id:
                errors.append(f"{result.scenario_id}: wrong candidate_id {result.candidate_id}")
            if result.capsule_sha256 != spec.capsule_sha256:
                errors.append(f"{result.scenario_id}: capsule hash mismatch")
            if result.seed_hash != spec.seed_hash:
                errors.append(f"{result.scenario_id}: seed hash mismatch")
            if result.code_hash != spec.code_hash:
                errors.append(f"{result.scenario_id}: code hash mismatch")
            if result.scenario_registry_hash != registry_hash():
                errors.append(f"{result.scenario_id}: scenario registry hash mismatch")
            if result.oracle_code_hash != oracle_code_hash():
                errors.append(f"{result.scenario_id}: oracle code hash mismatch")
            if not result.app_facts.get("provider_namespace", "").startswith(
                f"{spec.provider_namespace}-"
            ):
                errors.append(f"{result.scenario_id}: provider namespace mismatch")
            for invariant in result.invariants:
                if not invariant.evidence_ids:
                    errors.append(
                        f"{result.scenario_id}/{invariant.invariant_id}: empty evidence IDs"
                    )
        return errors

    def grade_candidate(
        self,
        spec: CandidateSpec,
        results: list[ScenarioResult],
        *,
        demo_mode: DemoMode = "FULL",
    ) -> CandidateEvaluation:
        errors = self.validate_evidence_set(spec, results, demo_mode=demo_mode)
        controls = self.run_negative_controls(spec.candidate_id)
        controls_ok = all(
            control.status == "FAIL"
            and set(control.failed_invariants)
            == set(
                next(
                    item.must_fail
                    for item in self.registry.negative_controls
                    if item.control_id == control.control_id
                )
            )
            for control in controls
        )
        if not controls_ok:
            errors.append("negative controls did not fail for the exact intended invariants")
        required_ids = {
            scenario.scenario_id
            for scenario in self.registry.scenarios
            if demo_mode == "FULL" or scenario.scenario_id in CORE_SCENARIO_IDS
        }
        required_results = [
            result for result in results if result.scenario_id in required_ids
        ]
        if errors or not required_results or any(
            result.status == "ERROR" for result in required_results
        ):
            verdict: Literal["PASS", "FAIL", "ERROR"] = "ERROR"
        elif any(result.status == "FAIL" for result in required_results):
            verdict = "FAIL"
        else:
            # Not vacuous: validate_evidence_set proved the exact non-empty matrix.
            verdict = "PASS"
        now = _utcnow()
        evidence_hash = canonical_sha256(
            [
                result.model_dump(mode="json")
                for result in sorted(results, key=lambda item: item.scenario_id)
            ]
        )
        return CandidateEvaluation(
            candidate_id=spec.candidate_id,
            scenario_ids=[
                scenario.scenario_id
                for scenario in self.registry.scenarios
                if scenario.scenario_id in required_ids
            ],
            invariant_ids=sorted(
                {
                    item
                    for scenario in self.registry.scenarios
                    if scenario.scenario_id in required_ids
                    for item in scenario.invariants
                }
            ),
            verdict=verdict,
            started_at_utc=min((result.started_at_utc for result in results), default=now),
            finished_at_utc=max((result.finished_at_utc for result in results), default=now),
            evidence_set_sha256=evidence_hash,
        )

    def run_negative_controls(self, candidate_id: str = "B") -> list[NegativeControlResult]:
        now = _utcnow()
        empty_ledger = LedgerView(
            namespace="nc-01",
            registrations=[],
            captures=[],
            refunds=[],
            digest=canonical_sha256({"nc": "01"}),
        )
        nc1_scenario = Scenario(
            scenario_id="S01",
            surface="API",
            case="negative control 1",
            required_outcome="must fail",
            invariants=["INV-02", "INV-05"],
        )
        nc1 = ScenarioEvidence(
            candidate_id=candidate_id,
            scenario=nc1_scenario,
            namespace="nc-01",
            store_facts=StoreFacts(
                intent_id="pi_nc_01",
                order_status="PAID",
                order_count=1,
                operation_count=1,
                operation_id="op_nc_01",
                confirmation_count=1,
                fulfillment_count=1,
                stock_remaining=99,
            ),
            ledger=empty_ledger,
            http_statuses=(200,),
            reported_status="PAID",
            expected_stock=99,
            original_namespace="original",
            original_digest_before=canonical_sha256({"original": True}),
            original_digest_after=canonical_sha256({"original": True}),
            trace_facts={"control": "fake-paid-without-capture"},
        )

        registration_1 = RegistrationRow(
            namespace="nc-02",
            operation_id="op_nc_02_a",
            intent_id="pi_nc_02",
            amount_minor=7999,
            currency="GBP",
            allowed_actions=["capture"],
            registered_at=now,
        )
        registration_2 = registration_1.model_copy(update={"operation_id": "op_nc_02_b"})
        capture_1 = CaptureRow(
            capture_id="cap_nc_02_a",
            namespace="nc-02",
            operation_id="op_nc_02_a",
            idempotency_key="key_nc_02_a",
            amount_minor=7999,
            currency="GBP",
            captured_at=now,
        )
        capture_2 = capture_1.model_copy(
            update={
                "capture_id": "cap_nc_02_b",
                "operation_id": "op_nc_02_b",
                "idempotency_key": "key_nc_02_b",
            }
        )
        nc2_scenario = Scenario(
            scenario_id="S02",
            surface="API",
            case="negative control 2",
            required_outcome="must fail",
            invariants=["INV-01"],
        )
        nc2 = ScenarioEvidence(
            candidate_id=candidate_id,
            scenario=nc2_scenario,
            namespace="nc-02",
            store_facts=StoreFacts(
                intent_id="pi_nc_02",
                order_status="PAID",
                order_count=2,
                operation_count=2,
                operation_id=None,
                confirmation_count=2,
                fulfillment_count=2,
                stock_remaining=98,
            ),
            ledger=LedgerView(
                namespace="nc-02",
                registrations=[registration_1, registration_2],
                captures=[capture_1, capture_2],
                refunds=[],
                digest=canonical_sha256({"nc": "02"}),
            ),
            http_statuses=(200,),
            reported_status="PAID",
            expected_stock=98,
            original_namespace="original",
            original_digest_before=canonical_sha256({"original": True}),
            original_digest_after=canonical_sha256({"original": True}),
            trace_facts={"control": "two-orders-one-intent"},
        )
        controls: list[tuple[str, ScenarioEvidence, list[InvariantId]]] = [
            ("NC-01", nc1, ["INV-02", "INV-05"]),
            ("NC-02", nc2, ["INV-01"]),
        ]
        outcomes: list[NegativeControlResult] = []
        for control_id, evidence, invariants in controls:
            results = [self.evaluate(evidence, invariant) for invariant in invariants]
            failed = [result.invariant_id for result in results if result.status == "FAIL"]
            outcomes.append(
                NegativeControlResult(
                    control_id=control_id,  # type: ignore[arg-type]
                    status="FAIL" if failed else "PASS",
                    failed_invariants=failed,
                    evidence_ids=[
                        evidence.store_evidence_id,
                        evidence.ledger_evidence_id,
                        evidence.trace_evidence_id,
                    ],
                )
            )
        return outcomes


class ScenarioSuite:
    """Real S03–S08 API execution with per-scenario SQLite generations/tokens."""

    def __init__(self, *, browser_error: str = "ERROR_BROWSER_STACK") -> None:
        self.registry = load_registry()
        self.oracle = Oracle(self.registry)
        self.browser_error = browser_error
        self._temporary = tempfile.TemporaryDirectory(prefix="nightwatch-oracle-")
        self.root = Path(self._temporary.name)
        self.seed_path = self.root / "store-seed.db"
        seed_store = Store(str(self.seed_path))
        seed_store.connection.close()
        self.seed_hash = sha256_hex(self.seed_path.read_bytes())
        self.code_hash = live_store_code_hash()
        self.scenario_registry_hash = registry_hash()
        self.oracle_hash = oracle_code_hash()

    def close(self) -> None:
        self._temporary.cleanup()

    def execute(self, spec: CandidateSpec, _world: object | None = None) -> list[ScenarioResult]:
        return asyncio.run(self.execute_async(spec))

    async def execute_async(self, spec: CandidateSpec) -> list[ScenarioResult]:
        if spec.seed_hash != self.seed_hash:
            raise ValueError("candidate seed_hash does not match the frozen seed generation")
        if spec.code_hash != self.code_hash:
            raise ValueError("candidate code_hash does not match the executable store bundle")

        evaluator_token = secrets.token_urlsafe(24)
        signing_secret = secrets.token_urlsafe(32)
        provider_path = self.root / f"provider-{spec.candidate_id}.db"
        provider_app = create_provider_app(
            ProviderSettings(
                provider_signing_secret=signing_secret,
                evaluator_token=evaluator_token,
            ),
            db_path=str(provider_path),
        )
        evaluator_headers = {"Authorization": f"Bearer {evaluator_token}"}
        evaluator = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=provider_app), base_url="http://provider"
        )
        provider_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=provider_app), base_url="http://provider"
        )
        original_namespace = f"original-{spec.candidate_id.lower()}"
        created = await evaluator.post(
            "/internal/namespaces",
            json={"namespace": original_namespace},
            headers=evaluator_headers,
        )
        if created.status_code != 201:
            raise RuntimeError(f"original namespace setup failed: {created.text}")
        original_before = await self._ledger(evaluator, evaluator_headers, original_namespace)
        results: list[ScenarioResult] = []
        try:
            for scenario in self.registry.scenarios:
                if scenario.surface != "API":
                    results.append(
                        await self._browser_error_result(
                            spec,
                            scenario,
                            evaluator,
                            evaluator_headers,
                            original_namespace,
                            original_before.digest,
                        )
                    )
                else:
                    results.append(
                        await self._run_api_scenario(
                            spec,
                            scenario,
                            evaluator,
                            evaluator_headers,
                            provider_client,
                            original_namespace,
                            original_before.digest,
                        )
                    )
        finally:
            await provider_client.aclose()
            await evaluator.aclose()
            provider_app.state.ledger.connection.close()
        return results

    async def _new_namespace(
        self,
        evaluator: httpx.AsyncClient,
        headers: dict[str, str],
        namespace: str,
    ) -> None:
        response = await evaluator.post(
            "/internal/namespaces", json={"namespace": namespace}, headers=headers
        )
        if response.status_code != 201:
            raise RuntimeError(f"namespace setup failed: {response.status_code} {response.text}")

    async def _browser_error_result(
        self,
        spec: CandidateSpec,
        scenario: Scenario,
        evaluator: httpx.AsyncClient,
        headers: dict[str, str],
        original_namespace: str,
        original_digest: str,
    ) -> ScenarioResult:
        started = _utcnow()
        namespace = f"{spec.provider_namespace}-{scenario.scenario_id.lower()}"
        await self._new_namespace(evaluator, headers, namespace)
        generation = self.root / f"{spec.candidate_id}-{scenario.scenario_id}.db"
        shutil.copyfile(self.seed_path, generation)
        if sha256_hex(generation.read_bytes()) != self.seed_hash:
            raise RuntimeError("scenario DB generation does not match frozen seed")
        store = Store(str(generation))
        intent = store.create_intent(
            "browser_fixture", [IntentItem(sku=scenario.sku, quantity=scenario.quantity)]
        )
        facts = store.store_facts(intent.intent_id)
        store.connection.close()
        ledger = await self._ledger(evaluator, headers, namespace)
        original_after = await self._ledger(evaluator, headers, original_namespace)
        token_response = await evaluator.post(
            "/internal/scoped-tokens",
            json={
                "incident_id": "NW-ORACLE-GATE",
                "candidate_id": spec.candidate_id,
                "scenario_id": scenario.scenario_id,
                "namespace": namespace,
                "allowed_operation_ids": ["*"],
                "expires_in_seconds": 300,
            },
            headers=headers,
        )
        token_response.raise_for_status()
        evidence = ScenarioEvidence(
            candidate_id=spec.candidate_id,
            scenario=scenario,
            namespace=namespace,
            store_facts=facts,
            ledger=ledger,
            http_statuses=(),
            reported_status=None,
            expected_stock=scenario.expected_stock,
            original_namespace=original_namespace,
            original_digest_before=original_digest,
            original_digest_after=original_after.digest,
            trace_facts={
                "db_generation_sha256": self.seed_hash,
                "fault_sha256": sha256_hex((scenario.fault or "NONE").encode()),
                "browser_state": self.browser_error,
                "provider_token_scope": "wildcard-ui",
                "original_digest_before": original_digest,
                "original_digest_after": original_after.digest,
            },
            browser_error=self.browser_error,
        )
        return self.oracle.scenario_result(
            evidence,
            started_at=started,
            finished_at=_utcnow(),
            capsule_sha256=spec.capsule_sha256,
            seed_hash=self.seed_hash,
            code_hash=self.code_hash,
            scenario_registry_hash=self.scenario_registry_hash,
            oracle_hash=self.oracle_hash,
        )

    async def _run_api_scenario(
        self,
        spec: CandidateSpec,
        scenario: Scenario,
        evaluator: httpx.AsyncClient,
        evaluator_headers: dict[str, str],
        provider_client: httpx.AsyncClient,
        original_namespace: str,
        original_digest: str,
    ) -> ScenarioResult:
        started = _utcnow()
        namespace = f"{spec.provider_namespace}-{scenario.scenario_id.lower()}"
        await self._new_namespace(evaluator, evaluator_headers, namespace)
        generation = self.root / f"{spec.candidate_id}-{scenario.scenario_id}.db"
        shutil.copyfile(self.seed_path, generation)
        if sha256_hex(generation.read_bytes()) != self.seed_hash:
            raise RuntimeError("scenario DB generation does not match frozen seed")

        live_internal = secrets.token_urlsafe(20)
        evaluator_token = evaluator_headers["Authorization"].removeprefix("Bearer ")
        live_app = create_store_app(
            StoreSettings(
                live_internal_token=live_internal,
                evaluator_token=evaluator_token,
            ),
            db_path=str(generation),
        )
        store_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=live_app), base_url="http://store"
        )
        live_headers = {"Authorization": f"Bearer {live_internal}"}
        trace: dict[str, str] = {
            "db_generation_sha256": self.seed_hash,
            "fault_sha256": sha256_hex((scenario.fault or "NONE").encode()),
            "original_digest_before": original_digest,
        }
        statuses: list[int] = []
        replay_unchanged: bool | None = None
        try:
            created = await store_client.post(
                "/api/intents",
                json={
                    "customer_id": f"customer-{scenario.scenario_id.lower()}",
                    "items": [{"sku": scenario.sku, "quantity": scenario.quantity}],
                },
            )
            statuses.append(created.status_code)
            created.raise_for_status()
            intent_id = created.json()["intent_id"]
            operation_id = f"op_{intent_id}"
            amount_minor = int(created.json()["amount_minor"]) - (scenario.voucher_minor or 0)
            registered = await evaluator.post(
                "/internal/operations",
                json={
                    "namespace": namespace,
                    "operation_id": operation_id,
                    "intent_id": intent_id,
                    "amount_minor": amount_minor,
                    "currency": "GBP",
                    "allowed_actions": ["capture", "refund", "inquiry"],
                },
                headers=evaluator_headers,
            )
            registered.raise_for_status()
            token_response = await evaluator.post(
                "/internal/scoped-tokens",
                json={
                    "incident_id": "NW-ORACLE-GATE",
                    "candidate_id": spec.candidate_id,
                    "scenario_id": scenario.scenario_id,
                    "namespace": namespace,
                    "allowed_operation_ids": [operation_id],
                    "expires_in_seconds": 300,
                },
                headers=evaluator_headers,
            )
            token_response.raise_for_status()
            live_app.state.provider = HttpPaymentProvider(
                "http://provider", token_response.json()["token"], client=provider_client
            )
            if scenario.fault is not None:
                fault_response = await evaluator.post(
                    "/internal/faults",
                    json={"namespace": namespace, "fault": scenario.fault},
                    headers=evaluator_headers,
                )
                if fault_response.status_code != 204:
                    raise RuntimeError(f"fault arm failed: {fault_response.text}")
            await self._activate_safe(store_client, live_headers)

            checkout_body = dict(CHECKOUT_BODY)
            if scenario.voucher_minor:
                checkout_body["voucher_code"] = "NIGHT10"
            path = f"/api/checkout/{intent_id}"
            responses: list[httpx.Response]
            if scenario.scenario_id == "S03":
                responses = list(
                    await asyncio.gather(
                        store_client.post(path, json=checkout_body),
                        store_client.post(path, json=checkout_body),
                    )
                )
                trace["same_order"] = str(
                    responses[0].json().get("order_id") == responses[1].json().get("order_id")
                ).lower()
            else:
                responses = [await store_client.post(path, json=checkout_body)]
                if scenario.scenario_id == "S04":
                    responses.append(await store_client.post(path, json=checkout_body))
                    trace["same_order"] = str(
                        responses[0].json().get("order_id")
                        == responses[1].json().get("order_id")
                    ).lower()
            statuses.extend(response.status_code for response in responses)
            for response in responses:
                response.raise_for_status()
            final_body = responses[-1].json()
            order_id = final_body.get("order_id")

            if scenario.scenario_id == "S06":
                refund_body = {
                    "order_id": order_id,
                    "refund_intent_id": "refund-full",
                    "amount_minor": 7999,
                }
                first_refund = await store_client.post("/api/refunds", json=refund_body)
                statuses.append(first_refund.status_code)
                first_refund.raise_for_status()
                before_replay = await self._ledger(evaluator, evaluator_headers, namespace)
                replay = await store_client.post("/api/refunds", json=refund_body)
                statuses.append(replay.status_code)
                replay.raise_for_status()
                after_replay = await self._ledger(evaluator, evaluator_headers, namespace)
                replay_unchanged = before_replay.digest == after_replay.digest
                final_body = replay.json()
            elif scenario.scenario_id == "S07":
                for refund_id, amount in (("refund-20", 2000), ("refund-10", 1000)):
                    response = await store_client.post(
                        "/api/refunds",
                        json={
                            "order_id": order_id,
                            "refund_intent_id": refund_id,
                            "amount_minor": amount,
                        },
                    )
                    statuses.append(response.status_code)
                    response.raise_for_status()
                    final_body = response.json()
                before_replay = await self._ledger(evaluator, evaluator_headers, namespace)
                replay = await store_client.post(
                    "/api/refunds",
                    json={
                        "order_id": order_id,
                        "refund_intent_id": "refund-10",
                        "amount_minor": 1000,
                    },
                )
                statuses.append(replay.status_code)
                replay.raise_for_status()
                after_replay = await self._ledger(evaluator, evaluator_headers, namespace)
                replay_unchanged = before_replay.digest == after_replay.digest
                final_body = replay.json()

            ledger = await self._ledger(evaluator, evaluator_headers, namespace)
            facts_response = await store_client.get(
                f"/internal/state/{intent_id}",
                headers={"Authorization": f"Bearer {evaluator_token}"},
            )
            facts_response.raise_for_status()
            facts = StoreFacts.model_validate_json(facts_response.content, strict=True)
            original_after = await self._ledger(
                evaluator, evaluator_headers, original_namespace
            )
            trace.update(
                {
                    "operation_id": operation_id,
                    "provider_token_scope": "exact-operation",
                    "capture_count": str(len(ledger.captures)),
                    "refund_count": str(len(ledger.refunds)),
                    "original_digest_after": original_after.digest,
                }
            )
            evidence = ScenarioEvidence(
                candidate_id=spec.candidate_id,
                scenario=scenario,
                namespace=namespace,
                store_facts=facts,
                ledger=ledger,
                http_statuses=tuple(statuses),
                reported_status=final_body.get("status"),
                expected_stock=scenario.expected_stock,
                original_namespace=original_namespace,
                original_digest_before=original_digest,
                original_digest_after=original_after.digest,
                trace_facts=trace,
                refund_replay_unchanged=replay_unchanged,
            )
            return self.oracle.scenario_result(
                evidence,
                started_at=started,
                finished_at=_utcnow(),
                capsule_sha256=spec.capsule_sha256,
                seed_hash=self.seed_hash,
                code_hash=self.code_hash,
                scenario_registry_hash=self.scenario_registry_hash,
                oracle_hash=self.oracle_hash,
            )
        finally:
            await store_client.aclose()
            live_app.state.store.connection.close()

    @staticmethod
    async def _activate_safe(
        client: httpx.AsyncClient, headers: dict[str, str]
    ) -> None:
        current = await client.get("/internal/router", headers=headers)
        current.raise_for_status()
        response = await client.put(
            "/internal/router",
            json={
                "mode": "SAFE",
                "expected_generation": current.json()["generation"],
                "lease_id": "lease-oracle-gate",
                "lease_expires_at": (_utcnow() + timedelta(minutes=10)).isoformat(),
                "handler_sha256": safe_handler_hash(),
            },
            headers=headers,
        )
        response.raise_for_status()

    @staticmethod
    async def _ledger(
        evaluator: httpx.AsyncClient, headers: dict[str, str], namespace: str
    ) -> LedgerView:
        response = await evaluator.get(f"/internal/ledger/{namespace}", headers=headers)
        response.raise_for_status()
        return LedgerView.model_validate_json(response.content, strict=True)
