"use strict";

// NightMart storefront API adapter (NightWatch Track B, apps/storefront).
//
// Endpoint shapes follow Final-nightwatch-plan.md §9.2 (public store API).
// Nothing outside this file may depend on these shapes until the freeze
// reconciles them against apps/contracts/** and apps/live_store/**.
// FROZEN-CONTRACT NOTE (contract freeze, T+0:20): this file is the ONLY place
// in apps/storefront that knows request/response field names. Reconcile them
// at the freeze; never edit field names in the pages.
const StoreAPI = (() => {
  async function request(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const text = await response.text();
    let body = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = text;
    }
    if (!response.ok) {
      const detail = body && typeof body === "object" ? body.detail : null;
      const error = new Error(detail ? String(detail) : `HTTP ${response.status}`);
      error.status = response.status;
      error.body = body;
      throw error;
    }
    return body;
  }

  return {
    createIntent({ customerId, sku, quantity }) {
      return request("/api/intents", {
        method: "POST",
        body: JSON.stringify({
          customer_id: customerId,
          items: [{ sku, quantity }],
        }),
      });
    },

    getIntent(intentId) {
      return request(`/api/intents/${encodeURIComponent(intentId)}`);
    },

    checkout(intentId, { email, address, voucherCode }) {
      const payload = { email, address };
      if (voucherCode) payload.voucher_code = voucherCode;
      return request(`/api/checkout/${encodeURIComponent(intentId)}`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    },

    getOrder(orderId) {
      return request(`/api/orders/${encodeURIComponent(orderId)}`);
    },
  };
})();
