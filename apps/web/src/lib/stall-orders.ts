import { apiGet, apiPost } from "@/lib/api";
import type { Order } from "@/lib/orders";

/** How the stall page shows PayPal (GET /api/paypal/config): the JS SDK in sandbox mode, simulated PayPal in test mode. */
export type PayPalConfig = {
  mode: "fake" | "sandbox";
  /** The sandbox app's client id, a public value; null in test mode or when sandbox mode has none set. */
  client_id: string | null;
  currency: "USD";
  /** Approving reserves the money; each share is captured when its maker proves she shipped. */
  intent: "authorize";
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
  style?: Record<string, string | number>;
  onClick?: (data: unknown, actions: PayPalButtonActions) => Promise<void> | void;
  createOrder: () => Promise<string>;
  onApprove: () => Promise<void>;
  onCancel?: () => void;
  onError?: (error: unknown) => void;
};
export type PayPalButtons = { render: (container: HTMLElement) => Promise<void>; close?: () => Promise<void> };
export type PayPalNamespace = { Buttons: (options: PayPalButtonsOptions) => PayPalButtons };

declare global {
  interface Window {
    paypal?: PayPalNamespace;
  }
}

let loading: Promise<PayPalNamespace> | null = null;

/** PayPal's JS SDK, loaded once per page, with intent=authorize so approving only reserves the money. */
export function loadPayPal(clientId: string): Promise<PayPalNamespace> {
  if (window.paypal) return Promise.resolve(window.paypal);
  if (loading) return loading;
  loading = new Promise<PayPalNamespace>((resolve, reject) => {
    const query = new URLSearchParams({
      "client-id": clientId,
      currency: "USD",
      intent: "authorize",
      components: "buttons",
      // PayPal only for now: Pay Later and cards are not proven with an order that is only reserved (prompt 57).
      "disable-funding": "paylater,card",
    });
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
