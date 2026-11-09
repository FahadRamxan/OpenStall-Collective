import { describe, expect, it } from "vitest";

import { fundingOf, sdkQuery, type PayPalConfig } from "@/lib/stall-orders";

const SANDBOX: PayPalConfig = { mode: "sandbox", client_id: "made-up-client-id", currency: "USD", intent: "authorize" };

describe("sdkQuery", () => {
  it("asks for intent authorize, PayPal's buttons only, and no cards, Pay Later or Venmo by default", () => {
    const query = sdkQuery(SANDBOX);

    expect(query.get("client-id")).toBe("made-up-client-id");
    expect(query.get("intent")).toBe("authorize");
    expect(query.get("components")).toBe("buttons");
    expect(query.get("enable-funding")).toBeNull();
    expect(query.get("disable-funding")).toBe("card,paylater,venmo");
    expect(query.get("buyer-country")).toBeNull();
  });

  it("offers Venmo, as a US buyer in PayPal's sandbox, when OpenStall offers it", () => {
    const query = sdkQuery({ ...SANDBOX, venmo: true, buyer_country: "US" });

    expect(query.get("enable-funding")).toBe("venmo");
    expect(query.get("disable-funding")).toBe("card,paylater");
    expect(query.get("buyer-country")).toBe("US");
  });

  it("offers Pay Later only behind its flag, and never cards", () => {
    const query = sdkQuery({ ...SANDBOX, venmo: true, pay_later: true });

    expect(query.get("enable-funding")).toBe("venmo,paylater");
    expect(query.get("disable-funding")).toBe("card");
  });
});

describe("fundingOf", () => {
  it("makes the order for Venmo only when the buyer pressed Venmo's button", () => {
    expect(fundingOf("venmo")).toBe("venmo");
    expect(fundingOf("paypal")).toBe("paypal");
    expect(fundingOf("paylater")).toBe("paypal"); // Pay Later is inside PayPal's checkout
    expect(fundingOf(undefined)).toBe("paypal");
  });
});
