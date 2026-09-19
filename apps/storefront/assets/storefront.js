"use strict";

// Shared page wiring for every NightMart page (NightWatch Track B).
// Both checkout variants load this file unchanged: every behavioural
// difference between UI X and UI Y lives in their HTML structure and wording,
// never in variant-specific selectors or branches. Nothing here is an
// automation selector: CUA/Jev act on semantic accessible names only.
(() => {
  const catalog = NightMartCatalog;
  const page = document.body.dataset.page;
  const $ = (id) => document.getElementById(id);

  function pickNumber(object, keys) {
    for (const key of keys) {
      if (object && typeof object[key] === "number") return object[key];
    }
    return null;
  }

  function pickString(object, keys) {
    for (const key of keys) {
      if (object && typeof object[key] === "string") return object[key];
    }
    return null;
  }

  function showBanner(message, kind) {
    const slot = document.querySelector("[data-banner-slot]");
    if (!slot) return;
    const element = document.createElement("div");
    element.className = `banner ${kind || "info"}`;
    element.setAttribute("role", "status");
    element.textContent = message;
    slot.replaceChildren(element);
  }

  function intentIdFrom(intent) {
    return pickString(intent, ["intent_id", "id"]);
  }

  function unitQuantity(intent) {
    if (!intent) return 1;
    const first = Array.isArray(intent.items) ? intent.items[0] : null;
    const candidate =
      (first && typeof first.quantity === "number" ? first.quantity : null) ??
      pickNumber(intent, ["quantity"]);
    if (typeof candidate === "number" && candidate >= 1) return candidate;
    return 1;
  }

  function renderSummary(intent) {
    const quantity = unitQuantity(intent);
    const serverAmount = pickNumber(intent, ["amount_minor"]);
    const line = $("summary-line");
    const subtotal = $("subtotal");
    const total = $("total");
    if (line) line.textContent = `${catalog.sku} × ${quantity}`;
    if (subtotal) subtotal.textContent = catalog.formatGBP(catalog.unitPriceMinor * quantity);
    if (total) {
      total.textContent = catalog.formatGBP(serverAmount ?? catalog.unitPriceMinor * quantity);
    }
  }

  function heldMessage(status) {
    if (status === "SAFE_HOLD" || status === "HELD") {
      return "NightMart is holding new payments for review. This attempt was not captured.";
    }
    return `Payment status: ${status}. We will not charge again automatically.`;
  }

  // ---------------------------------------------------------------- catalogue

  function initCatalogue() {
    const quantityInput = $("quantity");
    const start = $("start-checkout");
    if (!quantityInput || !start) return;

    const clamp = (value) => Math.min(catalog.maxQuantity, Math.max(1, value));
    const current = () => clamp(Number.parseInt(quantityInput.value, 10) || 1);
    const sync = () => {
      quantityInput.value = String(current());
      const amount = catalog.unitPriceMinor * current();
      const subtotal = $("subtotal");
      const total = $("total");
      if (subtotal) subtotal.textContent = catalog.formatGBP(amount);
      if (total) total.textContent = catalog.formatGBP(amount);
    };

    $("qty-dec")?.addEventListener("click", () => {
      quantityInput.value = String(current() - 1);
      sync();
    });
    $("qty-inc")?.addEventListener("click", () => {
      quantityInput.value = String(current() + 1);
      sync();
    });
    quantityInput.addEventListener("input", sync);

    start.addEventListener("click", async () => {
      start.disabled = true;
      try {
        const customerId = `cust_web_${Date.now().toString(36)}`;
        const intent = await StoreAPI.createIntent({
          customerId,
          sku: catalog.sku,
          quantity: current(),
        });
        const intentId = intentIdFrom(intent);
        if (!intentId) throw new Error("Intent response did not include an intent_id.");
        sessionStorage.setItem(`nw.intent.${intentId}`, JSON.stringify(intent));
        window.location.href = `checkout-x.html?intent=${encodeURIComponent(intentId)}`;
      } catch (error) {
        showBanner(`Could not start checkout: ${error.message}`, "err");
        start.disabled = false;
      }
    });
  }

  // ----------------------------------------------------------------- checkout

  async function loadIntent(intentId) {
    const cached = sessionStorage.getItem(`nw.intent.${intentId}`);
    if (cached) {
      try {
        return JSON.parse(cached);
      } catch {
        // fall through to the server
      }
    }
    const intent = await StoreAPI.getIntent(intentId);
    sessionStorage.setItem(`nw.intent.${intentId}`, JSON.stringify(intent));
    return intent;
  }

  function initCheckout() {
    const intentId = new URLSearchParams(window.location.search).get("intent");
    const form = $("checkout-form");
    const pay = $("pay");

    if (!intentId) {
      showBanner("No checkout intent in the URL. Return to the shop and start again.", "err");
      form?.querySelectorAll("input, textarea, button").forEach((element) => {
        element.disabled = true;
      });
      return;
    }

    loadIntent(intentId)
      .then(renderSummary)
      .catch((error) => showBanner(`Could not load this checkout: ${error.message}`, "err"));

    const reveal = document.querySelector("[data-reveal]");
    if (reveal) {
      reveal.addEventListener("click", () => {
        const target = document.getElementById(reveal.dataset.reveal);
        if (!target) return;
        target.classList.remove("hidden");
        reveal.setAttribute("aria-expanded", "true");
        reveal.closest(".field")?.classList.add("hidden");
        target.querySelector("input, textarea, button")?.focus();
      });
    }

    form?.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (pay) pay.disabled = true;

      const email = $("email")?.value?.trim() ?? "";
      const address = $("address")?.value?.trim() ?? "";
      const voucher = $("voucher")?.value?.trim() ?? "";
      if (!email || !address) {
        showBanner("Email and delivery address are required.", "warn");
        if (pay) pay.disabled = false;
        return;
      }

      try {
        const result = await StoreAPI.checkout(intentId, {
          email,
          address,
          voucherCode: voucher || null,
        });
        const orderId = pickString(result, ["order_id", "id"]);
        if (orderId) {
          sessionStorage.setItem(`nw.order.${orderId}`, JSON.stringify(result));
          window.location.href = `status.html?order=${encodeURIComponent(orderId)}`;
          return;
        }
        const status = pickString(result, ["status", "state"]) ?? "HELD";
        showBanner(heldMessage(status), "warn");
        if (pay) pay.disabled = false;
      } catch (error) {
        showBanner(`Payment could not be completed: ${error.message}`, "err");
        if (pay) pay.disabled = false;
      }
    });
  }

  // ------------------------------------------------------------------- status

  const STATUS_VIEW = {
    PAID: { label: "Paid", kind: "ok", note: "Payment captured once. This order is confirmed." },
    PENDING: { label: "Pending", kind: "warn", note: "Waiting for the payment provider." },
    PENDING_CONFIRMATION: {
      label: "Awaiting confirmation",
      kind: "warn",
      note: "NightMart is confirming the payment before confirming the order. No further charge is made automatically.",
    },
    SAFE_HOLD: {
      label: "Temporarily held",
      kind: "warn",
      note: "New payments are held for review. Nothing has been captured for this attempt.",
    },
    QUARANTINED: {
      label: "Quarantined for review",
      kind: "err",
      note: "This order needs a human review before it can proceed.",
    },
    DECLINED: { label: "Declined", kind: "err", note: "The payment was declined and no capture was made." },
    REFUNDED_FULL: { label: "Refunded in full", kind: "ok", note: "The capture was refunded." },
    REFUNDED_PARTIAL: { label: "Partially refunded", kind: "ok", note: "Part of the capture was refunded." },
  };

  const POLLING_STATUSES = new Set(["PENDING", "PENDING_CONFIRMATION", "PROCESSING", "SAFE_HOLD"]);

  function renderOrder(order) {
    const status = (pickString(order, ["status", "state"]) ?? "UNKNOWN").toUpperCase();
    const view = STATUS_VIEW[status] ?? { label: status, kind: "info", note: "" };

    const badge = $("status-badge");
    if (badge) {
      badge.textContent = view.label;
      badge.className = `badge ${view.kind}`;
    }
    const note = $("status-note");
    if (note) note.textContent = view.note;

    const orderId = $("order-id");
    if (orderId) orderId.textContent = pickString(order, ["order_id", "id"]) ?? "—";
    const intentId = $("intent-id");
    if (intentId) intentId.textContent = pickString(order, ["intent_id"]) ?? "—";

    const amount = pickNumber(order, ["amount_minor"]);
    const amountElement = $("amount");
    if (amountElement) {
      amountElement.textContent = amount === null ? "—" : catalog.formatGBP(amount);
    }

    const raw = $("raw");
    if (raw) raw.textContent = JSON.stringify(order, null, 2);

    return status;
  }

  function initStatus() {
    const orderId = new URLSearchParams(window.location.search).get("order");
    if (!orderId) {
      showBanner("No order reference in the URL.", "err");
      return;
    }

    let timer = null;
    const stopPolling = () => {
      if (timer) {
        window.clearInterval(timer);
        timer = null;
      }
    };

    async function load() {
      try {
        const order = await StoreAPI.getOrder(orderId);
        sessionStorage.setItem(`nw.order.${orderId}`, JSON.stringify(order));
        const status = renderOrder(order);
        if (POLLING_STATUSES.has(status)) {
          if (!timer) timer = window.setInterval(load, 2500);
        } else {
          stopPolling();
        }
      } catch (error) {
        showBanner(`Could not load order status: ${error.message}`, "err");
        stopPolling();
        const cached = sessionStorage.getItem(`nw.order.${orderId}`);
        if (cached) {
          try {
            renderOrder(JSON.parse(cached));
          } catch {
            // ignore a bad cache entry; the banner above is the truth
          }
        }
      }
    }

    $("refresh")?.addEventListener("click", load);
    load();
  }

  // ------------------------------------------------------------------- boot

  if (page === "catalogue") initCatalogue();
  else if (page === "checkout") initCheckout();
  else if (page === "status") initStatus();
})();
