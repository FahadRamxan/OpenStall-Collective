"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge, type BadgeTone } from "@/components/badge";
import { ApiError, errorMessage } from "@/lib/api";
import { formatUsd, place } from "@/lib/catalog";
import {
  PART_STATUS_LABELS,
  formatDay,
  getOrder,
  reserveOrder,
  type Order,
  type OrderPart,
  type PartStatus,
} from "@/lib/orders";

/** How often the receipt asks whether PayPal's confirmations have arrived, and for how long. */
export const RECEIPT_POLL_MS = 2_000;
const MAX_POLLS = 30;

type Load =
  | { state: "reserving" }
  | { state: "reserved"; order: Order }
  | { state: "missing" }
  | { state: "failed"; message: string; canRetry: boolean };

/** Shares PayPal has not confirmed yet, and nothing has gone wrong with: their webhooks are still on the way. */
function awaitingPayPal(order: Order): boolean {
  return order.parts.some((part) => part.status !== "pending" && !part.confirmed_by_paypal && !part.attention);
}

const PART_TONES: Record<PartStatus, BadgeTone> = {
  pending: "neutral",
  authorized: "accent",
  captured: "success",
  delivered: "success",
  released: "neutral",
};

/**
 * Where PayPal sends the human after they approve. It reserves the order (safe to repeat) and shows the receipt:
 * the total PayPal holds, and each maker's share, paid only when she ships.
 */
export function ReturnView() {
  const { orderId } = useParams<{ orderId: string }>();
  const [load, setLoad] = useState<Load>({ state: "reserving" });
  const [attempt, setAttempt] = useState(0);
  const [polls, setPolls] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    reserveOrder(orderId, { signal: controller.signal })
      .then((order) => setLoad({ state: "reserved", order }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) {
          setLoad({ state: "missing" });
          return;
        }
        // 409: PayPal does not have a valid approval. Trying again here cannot help; approving again can.
        const canRetry = !(error instanceof ApiError && error.status === 409);
        setLoad({ state: "failed", message: errorMessage(error), canRetry });
      });
    return () => controller.abort();
  }, [orderId, attempt]);

  // PayPal confirms each share with a webhook a moment later: look again until every one has arrived.
  useEffect(() => {
    if (load.state !== "reserved" || !awaitingPayPal(load.order) || polls >= MAX_POLLS) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      getOrder(orderId, { signal: controller.signal })
        .then((order) => setLoad({ state: "reserved", order }))
        .catch(() => {}) // a missed look is made up by the next one
        .finally(() => setPolls((count) => count + 1));
    }, RECEIPT_POLL_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [load, polls, orderId]);

  const backToOrder = (
    <Link
      href={`/approve/${encodeURIComponent(orderId)}`}
      className="inline-flex min-h-11 items-center rounded-full border border-border px-5 text-sm font-semibold hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      Back to the order
    </Link>
  );

  if (load.state === "reserving") {
    return (
      <div role="status" aria-label="Reserving the money at PayPal" className="max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight">Reserving the money at PayPal…</h1>
        <p className="mt-4 text-lg leading-8 text-muted">This takes a moment. PayPal only holds the total; nothing is taken.</p>
        <div className="mt-8 space-y-3" aria-hidden="true">
          {[0, 1, 2, 3].map((key) => (
            <div key={key} className="h-16 animate-pulse rounded-xl bg-border/60" />
          ))}
        </div>
      </div>
    );
  }
  if (load.state === "missing") {
    return (
      <div className="max-w-2xl">
        <h1 className="text-3xl font-semibold tracking-tight">No order here</h1>
        <p className="mt-4 text-lg leading-8 text-muted">
          There is no order at this address. Ask the agent that sent you here for a fresh link.
        </p>
      </div>
    );
  }
  if (load.state === "failed") {
    return (
      <div role="alert" className="max-w-2xl rounded-xl border border-border bg-surface p-6">
        <h1 className="text-2xl font-semibold tracking-tight">The money is not reserved yet</h1>
        <p className="mt-2 leading-7 text-muted">{load.message}</p>
        <div className="mt-5 flex flex-wrap gap-3">
          {load.canRetry ? (
            <button
              type="button"
              onClick={() => {
                setLoad({ state: "reserving" });
                setAttempt((count) => count + 1);
              }}
              className="inline-flex min-h-11 items-center rounded-full bg-accent px-5 text-sm font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              Try again
            </button>
          ) : null}
          {backToOrder}
        </div>
      </div>
    );
  }
  return <Receipt order={load.order} backToOrder={backToOrder} />;
}

function Receipt({ order, backToOrder }: { order: Order; backToOrder: React.ReactNode }) {
  const total = formatUsd(order.total_usd);
  return (
    <div className="max-w-3xl">
      <p className="text-sm font-semibold text-accent">
        <span className="tracking-wide uppercase">Order</span> <span className="font-mono">{order.id}</span>
      </p>
      <div className="mt-3 flex items-start gap-3">
        <span
          aria-hidden="true"
          className="mt-1 grid size-9 shrink-0 place-items-center rounded-full bg-success-soft text-success"
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.5" className="size-5">
            <path d="M4.5 10.5l3.5 3.5 7.5-8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
        <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">PayPal is holding {total}</h1>
      </div>
      <p className="mt-4 text-lg leading-8 text-muted">
        Nothing has been taken yet. Each maker is paid when she ships, and a share she cannot deliver goes back to
        you.
      </p>
      <p role="status" className="mt-3 text-sm font-medium">
        {awaitingPayPal(order) ? (
          <span className="text-muted">Waiting for PayPal to confirm each share…</span>
        ) : (
          <span className="text-success">PayPal confirmed every share.</span>
        )}
      </p>

      <section aria-labelledby="receipt-heading" className="mt-8">
        <h2 id="receipt-heading" className="text-xl font-semibold tracking-tight">
          Your receipt
        </h2>
        <ul
          aria-label="Each maker's share"
          className="mt-4 divide-y divide-border rounded-2xl border border-border bg-surface"
        >
          {order.parts.map((part) => {
            const where = place(part.seller.city, part.seller.country);
            return (
              <li key={part.id} className="flex flex-col gap-2 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
                <div className="min-w-0">
                  <p className="font-semibold">
                    {part.seller.name}
                    {where ? <span className="font-normal text-muted"> · {where}</span> : null}
                  </p>
                  <p className="mt-0.5 text-sm text-muted">
                    {part.quantity} × {formatUsd(part.unit_price_usd)}
                    {part.delivery_date ? ` · ships by ${formatDay(part.delivery_date)}` : null}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 sm:flex-col sm:items-end">
                  <p className="font-semibold tabular-nums">{formatUsd(part.amount_usd)}</p>
                  <Badge tone={PART_TONES[part.status]}>{PART_STATUS_LABELS[part.status]}</Badge>
                  <PayPalNote part={part} />
                </div>
              </li>
            );
          })}
        </ul>
        <div className="mt-4 flex flex-wrap items-baseline justify-between gap-2 px-1">
          <p className="text-muted">Reserved at PayPal</p>
          <p className="text-3xl font-semibold tabular-nums">{total}</p>
        </div>
        {order.paypal_order_id ? (
          <p className="mt-2 px-1 text-sm text-muted">
            PayPal order <span className="font-mono">{order.paypal_order_id}</span>
          </p>
        ) : null}
      </section>

      <div className="mt-10 flex flex-wrap gap-3">
        <Link
          href="/demo"
          className="inline-flex min-h-11 items-center rounded-full bg-accent px-5 text-sm font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Watch it happen on the live demo
        </Link>
        {backToOrder}
      </div>
    </div>
  );
}

/** Whether PayPal itself confirmed where the share stands, from its verified webhooks. */
function PayPalNote({ part }: { part: OrderPart }) {
  if (part.attention) {
    return <p className="text-xs font-semibold text-danger">{part.attention}</p>;
  }
  if (part.status === "pending") return null;
  if (!part.confirmed_by_paypal) {
    return <p className="text-xs text-muted">Waiting for PayPal…</p>;
  }
  return (
    <p className="inline-flex items-center gap-1 text-xs font-semibold text-success">
      <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.5" className="size-3.5">
        <path d="M4.5 10.5l3.5 3.5 7.5-8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Confirmed by PayPal
    </p>
  );
}
