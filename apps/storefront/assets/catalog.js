"use strict";

// NightMart catalogue fixtures (NightWatch Track B, apps/storefront).
// The demo has exactly one product (plan §5.0). These values are DISPLAY
// fixtures only: whenever the intent/order API response carries an amount,
// that server value wins (see storefront.js).
const NightMartCatalog = (() => {
  const sku = "SKU-A";
  const unitPriceMinor = 7999; // £79.99
  const currency = "GBP";
  const maxQuantity = 5;

  function formatGBP(minor) {
    return new Intl.NumberFormat("en-GB", { style: "currency", currency }).format(minor / 100);
  }

  return { sku, unitPriceMinor, currency, maxQuantity, formatGBP };
})();
