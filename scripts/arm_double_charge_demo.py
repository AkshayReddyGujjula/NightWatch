"""Arm the deployed NightMart double-charge showcase without printing secrets.

Usage:
    uv run python scripts/arm_double_charge_demo.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.live_store.app import StoreSettings  # noqa: E402

DEFAULT_STORE_URL = (
    "https://jxzxl07-nightwatch-demo--nightwatch-live-store-asgi.modal.run"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-url", default=DEFAULT_STORE_URL)
    args = parser.parse_args()

    token = StoreSettings().live_internal_token
    if not token:
        raise SystemExit("LIVE_INTERNAL_TOKEN is not configured in .env")

    response = httpx.post(
        f"{args.store_url.rstrip('/')}/internal/demo/arm-double-charge",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    response.raise_for_status()
    setup = response.json()
    print("Double-charge showcase armed with real provider evidence.")
    print(f"Namespace: {setup['namespace']}")
    print(f"Router mode: {setup['router']['mode']}")
    print(f"Checkout X: {setup['checkout_x_url']}")
    print(f"Checkout Y: {setup['checkout_y_url']}")


if __name__ == "__main__":
    main()
