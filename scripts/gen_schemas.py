"""Generate committed JSON Schemas for the frozen boundary models (plan §16.1).

Run from the repository root::

    uv run python scripts/gen_schemas.py

Track B's dashboard consumes these through ``npm run gen:types``; no
hand-written TypeScript client schema exists on either side.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.contracts import browser, evaluation, incident, lease, payment  # noqa: E402
from apps.contracts.base import StrictModel  # noqa: E402

MODEL_GROUPS: dict[str, list[type[StrictModel]]] = {
    "browser": [
        browser.BrowserFrame,
        browser.FrameIngestAck,
        browser.BrowserReadyRequest,
        browser.BrowserBarrierState,
        browser.BrowserObservation,
        browser.JevDecision,
        browser.ObservedControl,
    ],
    "incident": [
        incident.IncidentEvent,
        incident.IncidentCapsule,
        incident.CapsuleRowSet,
        incident.LogLine,
        incident.TriageAdvisory,
        incident.Hypothesis,
        incident.GeminiDiagnosis,
        incident.PatchProposal,
        incident.CandidateSpec,
    ],
    "payment": [
        payment.IntentItem,
        payment.CreateIntentRequest,
        payment.IntentResponse,
        payment.CheckoutRequest,
        payment.CheckoutResponse,
        payment.OrderResponse,
        payment.CheckoutIntent,
        payment.Order,
        payment.PaymentOperation,
        payment.Confirmation,
        payment.Fulfillment,
        payment.RefundIntent,
        payment.RouterState,
        payment.RegistrationRow,
        payment.CaptureRow,
        payment.RefundRow,
        payment.LedgerView,
        payment.ProviderTokenClaims,
        payment.CaptureRequest,
        payment.CaptureResponse,
        payment.RefundRequest,
        payment.RefundResponse,
        payment.OperationRegisterRequest,
        payment.ScopedTokenRequest,
        payment.ScopedTokenResponse,
        payment.RefundApiRequest,
        payment.RouterUpdateRequest,
        payment.StoreFacts,
    ],
    "evaluation": [
        evaluation.Scenario,
        evaluation.NegativeControl,
        evaluation.ScenarioRegistry,
        evaluation.InvariantResult,
        evaluation.ScenarioResult,
        evaluation.CandidateEvaluation,
        evaluation.StageEvent,
    ],
    "lease": [
        lease.RepairLease,
        lease.OriginalHarm,
        lease.ContainmentSummary,
        lease.RepairReceipt,
    ],
}

OUTPUT_DIR = ROOT / "apps" / "contracts" / "schemas"


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for module, models in MODEL_GROUPS.items():
        for model in models:
            path = OUTPUT_DIR / f"{module}.{model.__name__}.json"
            path.write_text(json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n")
            written += 1
    print(f"wrote {written} schemas to {OUTPUT_DIR.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
