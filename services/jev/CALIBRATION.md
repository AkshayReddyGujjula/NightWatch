# Jev action-choice calibration — pilot evidence

Track B keeps event-day evidence for the §11.3 low-margin rule here.
This file is a log, not a threshold source.

## 2026-09-19 — T+0 preflight smoke (TypeSafe `jev-1.13.0`)

- **Request:** one native `system_one` call, one `Choice` question (`next_action`)
  over a compact checkout observation (goal, URL, heading, two visible controls).
  Criteria offered: `click__a17`, `reobserve`, `abstain`.
- **Response (exact fields):** `choice="click__a17"`, `confidence=0.27`,
  `probabilities={"abstain": 0.45, "click__a17": 0.52, "reobserve": 0.03}`;
  `model="jev-1.13.0"`; usage 474 input / 51 output tokens.
- **Reading:** confidence is a margin, not a correctness probability. The
  non-winning `abstain` score (0.45) sits close to the winner (0.52) — a textbook
  low-margin decision. The §11.3 behaviour applies: reobserve once, then abstain.
- **Threshold policy:** no numeric threshold is set from this single sample.
  Calibration targets ~30 event-day decisions; until then the default rule
  (low margin → reobserve once → abstain) stands, and raw probabilities,
  confidence and `model_name` are preserved on every decision for the receipt.
