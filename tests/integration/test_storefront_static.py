"""The deployed live-store app serves the two real checkout surfaces."""

from __future__ import annotations

from fastapi.testclient import TestClient

from apps.live_store.app import StoreSettings, create_app


def test_storefront_pages_and_assets_are_served_without_shadowing_api() -> None:
    app = create_app(StoreSettings())
    client = TestClient(app)

    checkout_x = client.get("/checkout-x.html")
    assert checkout_x.status_code == 200
    assert "Pay now" in checkout_x.text

    checkout_y = client.get("/checkout-y.html")
    assert checkout_y.status_code == 200
    assert "Confirm order" in checkout_y.text
    assert "Add voucher" in checkout_y.text

    assert client.get("/assets/api.js").status_code == 200
    assert client.get("/health").json()["service"] == "live_store"
    # API routing still wins over the final catch-all static mount.
    assert client.get("/api/intents/not-present").status_code == 404


def test_storefront_root_renders_catalogue() -> None:
    response = TestClient(create_app(StoreSettings())).get("/")
    assert response.status_code == 200
    assert "NightMart" in response.text
