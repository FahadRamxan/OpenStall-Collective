"use client";

import { useEffect, useId, useRef, useState } from "react";

import { errorMessage } from "@/lib/api";
import { formatUsd, type Product } from "@/lib/catalog";
import { reserveOrder, startCheckout } from "@/lib/orders";
import { createStallOrder, getPayPalConfig, loadPayPal, type PayPalConfig } from "@/lib/stall-orders";

/** The most a person can buy at a stall; more goes through a quote, where the collective can split it. */
export const MAX_UNITS = 50;

/**
 * Buy from her stall (prompt 42): how many, the city it ships to, and PayPal's own buttons, which reserve the total at
 * her list price; she is paid when she proves she shipped. Test mode has no PayPal to load, so a simulated PayPal
 * button goes through the simulated PayPal page. The total here is a preview: OpenStall works out the real one.
 * `go` leaves for PayPal's page, and for the receipt once PayPal's buttons are approved (a prop so tests can follow
 * it).
 */
export function StallBuy({
  product,
  maker,
  go = (url) => window.location.assign(url),
}: {
  product: Product;
  maker: string;
  go?: (url: string) => void;
}) {
  const id = useId();
  const [config, setConfig] = useState<PayPalConfig | null>(null);
  const [quantity, setQuantity] = useState(1);
  const [city, setCity] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const buttons = useRef<HTMLDivElement>(null);
  // PayPal's buttons are drawn once; they read what the person chose through these.
  const chosen = useRef({ quantity, city });
  const orderId = useRef<string | null>(null);

  useEffect(() => {
    chosen.current = { quantity, city };
  }, [quantity, city]);

  useEffect(() => {
    const controller = new AbortController();
    getPayPalConfig({ signal: controller.signal })
      .then(setConfig)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setProblem(`PayPal could not be set up: ${errorMessage(error)}`);
      });
    return () => controller.abort();
  }, []);

  /** What is wrong with the choice, in words, or null. */
  function invalid(): string | null {
    const { quantity: units, city: place } = chosen.current;
    if (!Number.isInteger(units) || units < 1 || units > MAX_UNITS) return `Choose from 1 to ${MAX_UNITS}.`;
    if (!place.trim()) return "Say which city it ships to.";
    return null;
  }

  /** Draft the purchase and send it to PayPal: the PayPal order to approve. */
  async function toPayPal(): Promise<{ orderId: string; paypalOrderId: string; approvalUrl: string }> {
    const order = await createStallOrder({
      product_id: product.id,
      quantity: chosen.current.quantity,
      ship_to: chosen.current.city.trim(),
    });
    const checkout = await startCheckout(order.id);
    orderId.current = order.id;
    return { orderId: order.id, paypalOrderId: checkout.paypal_order_id, approvalUrl: checkout.approval_url };
  }

  useEffect(() => {
    const container = buttons.current;
    if (config?.mode !== "sandbox" || !config.client_id || !container) return;
    let drawn: { close?: () => Promise<void> } | null = null;
    let stopped = false;
    loadPayPal(config.client_id)
      .then((paypal) => {
        if (stopped) return;
        drawn = paypal.Buttons({
          style: { layout: "vertical", label: "pay", shape: "pill" },
          onClick: (_data, actions) => {
            const why = invalid();
            setProblem(why);
            return why ? actions.reject() : actions.resolve();
          },
          createOrder: async () => {
            setProblem(null);
            try {
              return (await toPayPal()).paypalOrderId;
            } catch (error) {
              setProblem(errorMessage(error));
              throw error;
            }
          },
          onApprove: async () => {
            const approved = orderId.current;
            if (!approved) return;
            await reserveOrder(approved);
            go(`/approve/${encodeURIComponent(approved)}/return`);
          },
          onCancel: () => setProblem("You closed PayPal before approving: nothing was reserved."),
          onError: (error) => setProblem(`PayPal stopped: ${errorMessage(error)}`),
        });
        void (drawn as { render: (into: HTMLElement) => Promise<void> }).render(container);
      })
      .catch((error: unknown) => setProblem(errorMessage(error)));
    return () => {
      stopped = true;
      void drawn?.close?.();
    };
    // invalid, toPayPal and go read refs or stay the same, so the buttons are drawn once per config.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config]);

  async function simulated() {
    const why = invalid();
    setProblem(why);
    if (why) return;
    setBusy(true);
    try {
      go((await toPayPal()).approvalUrl);
    } catch (error) {
      setProblem(errorMessage(error));
      setBusy(false);
    }
  }

  const units = Number.isInteger(quantity) && quantity > 0 ? quantity : 0;
  const total = (Math.round(Number(product.price_usd) * 100) * units) / 100;
  return (
    <section aria-labelledby={`${id}-buy`} className="mt-8 rounded-2xl border border-border bg-surface p-5">
      <h4 id={`${id}-buy`} className="text-lg font-semibold">
        Buy from {maker}
      </h4>
      <p className="mt-1 text-sm leading-6 text-muted">
        PayPal only reserves the money. {maker} is paid when she proves she shipped; if she cannot, you are never
        charged.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-[8rem_minmax(0,1fr)]">
        <label className="flex flex-col gap-1 text-sm font-medium">
          How many
          <input
            type="number"
            min={1}
            max={MAX_UNITS}
            step={1}
            inputMode="numeric"
            value={Number.isNaN(quantity) ? "" : quantity}
            onChange={(event) => setQuantity(event.target.valueAsNumber)}
            className="min-h-11 rounded-lg border border-border bg-background px-3 tabular-nums"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          Ship to (city)
          <input
            type="text"
            value={city}
            autoComplete="address-level2"
            maxLength={120}
            onChange={(event) => setCity(event.target.value)}
            className="min-h-11 rounded-lg border border-border bg-background px-3"
          />
        </label>
      </div>
      <p className="mt-3 text-sm" aria-live="polite">
        {/* One sentence, so the listing's own price stays the only one written alone on the page. */}
        {units > 0
          ? `${units} × ${formatUsd(product.price_usd)} = ${formatUsd(total.toFixed(2))}, worked out again by OpenStall`
          : "Choose how many."}
      </p>
      <div className="mt-4">
        {config === null ? (
          problem ? null : (
            <p aria-busy="true" className="text-sm text-muted">
              Loading PayPal…
            </p>
          )
        ) : config.mode === "fake" ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => void simulated()}
            className="inline-flex min-h-12 w-full items-center justify-center gap-2 rounded-full bg-accent px-6 text-base font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60 sm:w-auto"
          >
            {busy ? "Going to simulated PayPal…" : "Buy with simulated PayPal"}
            <span className="rounded-full bg-warning-soft px-2 py-0.5 text-xs text-warning">Test mode</span>
          </button>
        ) : config.client_id ? (
          <div ref={buttons} aria-label="PayPal's buttons" className="max-w-sm" />
        ) : (
          <p className="text-sm text-muted">PayPal is not connected here yet: PAYPAL_CLIENT_ID is not set.</p>
        )}
      </div>
      {problem ? (
        <p role="alert" className="mt-3 text-sm text-danger">
          {problem}
        </p>
      ) : null}
    </section>
  );
}
