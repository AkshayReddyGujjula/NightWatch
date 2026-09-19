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
    assert 'type="text" inputmode="email" autocomplete="email"' in checkout_x.text
    assert 'value="demo@example.com"' in checkout_x.text
    assert "A blank email safely defaults to demo@example.com" in checkout_x.text
    assert "1 Demo Street, London" in checkout_x.text
    assert "storefront.js?v=20260919-demo2" in checkout_x.text

    checkout_y = client.get("/checkout-y.html")
    assert checkout_y.status_code == 200
    assert "Confirm order" in checkout_y.text
    assert "Add voucher" in checkout_y.text
    assert 'type="text" inputmode="email" autocomplete="email"' in checkout_y.text
    assert 'value="demo@example.com"' in checkout_y.text
    assert "A blank email safely defaults to demo@example.com" in checkout_y.text
    assert "1 Demo Street, London" in checkout_y.text

    assert client.get("/assets/api.js").status_code == 200
    assert client.get("/health").json()["service"] == "live_store"
    # API routing still wins over the final catch-all static mount.
    assert client.get("/api/intents/not-present").status_code == 404


def test_direct_checkout_urls_create_intent_and_redirect_to_interactive_page() -> None:
    app = create_app(StoreSettings())
    client = TestClient(app)

    for path, button_text in (
        ("/checkout-x.html", "Pay now"),
        ("/checkout-y.html", "Confirm order"),
    ):
        redirect = client.get(path, follow_redirects=False)
        assert redirect.status_code == 303
        location = redirect.headers["location"]
        assert location.startswith(f"{path}?intent=pi_")
        assert redirect.headers["cache-control"] == "no-store"

        page = client.get(location)
        assert page.status_code == 200
        assert button_text in page.text
        assert page.headers["cache-control"] == "no-store"

        intent_id = location.partition("?intent=")[2]
        intent = client.get(f"/api/intents/{intent_id}")
        assert intent.status_code == 200
        assert intent.json()["items"] == [{"sku": "SKU-A", "quantity": 1}]


def test_storefront_root_renders_catalogue() -> None:
    response = TestClient(create_app(StoreSettings())).get("/")
    assert response.status_code == 200
    assert "NightMart" in response.text


def test_storefront_carries_provider_incident_notice_to_status_page() -> None:
    response = TestClient(create_app(StoreSettings())).get("/assets/storefront.js")
    assert response.status_code == 200
    assert "nw.incident.${orderId}" in response.text
    assert 'showBanner(incidentMessage, "err")' in response.text
    assert '|| "demo@example.com"' in response.text
    assert "captured_total_minor" in response.text
    assert "chargedQuery" in response.text
    assert 'params.get("charged")' in response.text
    assert "Recovery complete" in response.text
    assert "REFUNDED_PARTIAL" in response.text


def test_scripted_outage_blocks_every_public_nightmart_route_and_recovers() -> None:
    app = create_app(StoreSettings(live_internal_token="test-live-token"))
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-live-token"}

    assert client.get("/").status_code == 200
    assert client.put("/internal/demo/outage", json={"active": True}).status_code == 401
    enabled = client.put(
        "/internal/demo/outage", json={"active": True}, headers=headers
    )
    assert enabled.json() == {"active": True}

    for method, path in (
        ("get", "/"),
        ("get", "/checkout-x.html?intent=pi_demo"),
        ("get", "/status.html?order=ord_demo"),
        ("get", "/assets/storefront.js"),
        ("get", "/health"),
        ("post", "/api/intents"),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == 503
        assert "NightMart is unavailable" in response.text
        assert response.headers["cache-control"] == "no-store"

    assert client.get("/internal/router", headers=headers).status_code == 200
    disabled = client.put(
        "/internal/demo/outage", json={"active": False}, headers=headers
    )
    assert disabled.json() == {"active": False}
    assert client.get("/").status_code == 200
    assert client.get("/health").status_code == 200
