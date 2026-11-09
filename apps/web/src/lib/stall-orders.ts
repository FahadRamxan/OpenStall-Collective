import { apiGet, apiPost } from "@/lib/api";
import type { Funding, Order } from "@/lib/orders";

/** How the stall page shows PayPal (GET /api/paypal/config): the JS SDK in sandbox mode, simulated PayPal in test mode. */
export type PayPalConfig = {
  mode: "fake" | "sandbox";
  /** The sandbox app's client id, a public value; null in test mode or when sandbox mode has none set. */
  client_id: string | null;
  currency: "USD";
  /** Approving reserves the money; each share is captured when its maker proves she shipped. */
  intent: "authorize";
  /** Venmo's button, for a buyer in the US (prompt 57). */
  venmo?: boolean;
  /** Pay Later's button: off until an order that is only reserved is proven with it. */
  pay_later?: boolean;
  /** Set in PayPal's sandbox only, which shows Venmo only to a buyer it takes to be in the US. */
  buyer_country?: "US" | null;
};

export function getPayPalConfig(init: RequestInit = {}): Promise<PayPalConfig> {
  return apiGet<PayPalConfig>("/api/paypal/config", init);
}

export type StallOrderIn = { product_id: string; quantity: number; ship_to: string };

/** A person's purchase from a stall, drafted at her list price: the order to send to PayPal. */
export function createStallOrder(body: StallOrderIn): Promise<Order> {
  return apiPost<Order>("/api/stall-orders", body);
}

/** The few parts of PayPal's JS SDK the stall page uses. */
export type PayPalButtonActions = { resolve: () => Promise<void>; reject: () => Promise<void> };
export type PayPalButtonsOptions = {
  /** One standalone button for this funding source (PayPal's FUNDING.VENMO, say), instead of every eligible one. */
  fundingSource?: string;
  style?: Record<string, string | number>;
  onClick?: (data: unknown, actions: PayPalButtonActions) => Promise<void> | void;
  /** PayPal's JS SDK says which button the buyer pressed: `paymentSource` is "paypal", "venmo", "paylater"… */
  createOrder: (data?: { paymentSource?: string }) => Promise<string>;
  onApprove: () => Promise<void>;
  onCancel?: () => void;
  onError?: (error: unknown) => void;
};
export type PayPalButtons = {
  render: (container: HTMLElement) => Promise<void>;
  close?: () => Promise<void>;
  /** Whether PayPal offers this button to this buyer here (Venmo: a US buyer paying a US business). */
  isEligible?: () => boolean;
};
export type PayPalNamespace = {
  Buttons: (options: PayPalButtonsOptions) => PayPalButtons;
  FUNDING?: { PAYPAL: string; VENMO: string; PAYLATER: string };
};

/** The order to make for the button the buyer pressed: Venmo's own, or PayPal's (Pay Later is inside PayPal's). */
export function fundingOf(paymentSource: string | undefined): Funding {
  return paymentSource === "venmo" ? "venmo" : "paypal";
}

/** The JS SDK's address: intent authorize, so approving only reserves the money; Venmo when OpenStall offers it, Pay
 * Later only behind its flag, cards never (not proven with an order that is only reserved). */
export function sdkQuery(config: PayPalConfig): URLSearchParams {
  const query = new URLSearchParams({
    "client-id": config.client_id ?? "",
    currency: "USD",
    intent: "authorize",
    components: "buttons",
  });
  const enabled = [config.venmo ? "venmo" : "", config.pay_later ? "paylater" : ""].filter(Boolean);
  if (enabled.length) query.set("enable-funding", enabled.join(","));
  query.set("disable-funding", ["card", config.pay_later ? "" : "paylater", config.venmo ? "" : "venmo"].filter(Boolean).join(","));
  if (config.buyer_country) query.set("buyer-country", config.buyer_country);
  return query;
}

declare global {
  interface Window {
    paypal?: PayPalNamespace;
  }
}

let loading: Promise<PayPalNamespace> | null = null;

/** PayPal's JS SDK, loaded once per page, with intent=authorize so approving only reserves the money. */
export function loadPayPal(config: PayPalConfig): Promise<PayPalNamespace> {
  if (window.paypal) return Promise.resolve(window.paypal);
  if (loading) return loading;
  loading = new Promise<PayPalNamespace>((resolve, reject) => {
    const query = sdkQuery(config);
    const script = document.createElement("script");
    script.src = `https://www.paypal.com/sdk/js?${query}`;
    script.async = true;
    script.onload = () => {
      if (window.paypal) resolve(window.paypal);
      else reject(new Error("PayPal's script loaded, but PayPal's buttons did not."));
    };
    script.onerror = () => {
      loading = null;
      script.remove();
      reject(new Error("PayPal's buttons could not be loaded. Check your connection and reload the page."));
    };
    document.head.appendChild(script);
  });
  return loading;
}
