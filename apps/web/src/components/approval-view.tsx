"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/badge";
import { RailChip } from "@/components/rail-chip";
import { ApiError, errorMessage } from "@/lib/api";
import { formatUsd, mediaUrl, place } from "@/lib/catalog";
import { goTo } from "@/lib/navigation";
import {
  ORDER_STATUS_LABELS,
  authorizationSentence,
  canCheckout,
  formatDay,
  getOrder,
  startCheckout,
  type Order,
  type OrderPart,
} from "@/lib/orders";

type Load =
  | { state: "loading" }
  | { state: "loaded"; order: Order }
  | { state: "missing" }
  | { state: "failed"; message: string };

/** The human's approval step: what the agent asked for, who makes it, the total, and one button to PayPal. */
export function ApprovalView() {
  const { orderId } = useParams<{ orderId: string }>();
  // PayPal sends the human back here with ?cancelled=1 when they leave without approving.
  const cancelled = useSearchParams().get("cancelled") === "1";
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getOrder(orderId, { signal: controller.signal })
      .then((order) => setLoad({ state: "loaded", order }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) setLoad({ state: "missing" });
        else setLoad({ state: "failed", message: errorMessage(error) });
      });
    return () => controller.abort();
  }, [orderId, attempt]);

  if (load.state === "loading") return <ApprovalSkeleton />;
  if (load.state === "missing") {
    return (
      <div className="max-w-2xl">
        <h1 className="text-3xl font-semibold tracking-tight">No order here</h1>
        <p className="mt-4 text-lg leading-8 text-muted">
          There is no order at this address. Ask the agent that sent you here for a fresh link.
        </p>
        <Link href="/demo" className="mt-6 inline-block font-semibold text-accent underline underline-offset-4">
          Go to the live demo
        </Link>
      </div>
    );
  }
  if (load.state === "failed") {
    return (
      <div role="alert" className="max-w-2xl rounded-xl border border-border bg-surface p-6">
        <h1 className="text-2xl font-semibold tracking-tight">This order could not be loaded</h1>
        <p className="mt-2 text-muted">{load.message}</p>
        <button
          type="button"
          onClick={() => {
            setLoad({ state: "loading" });
            setAttempt((count) => count + 1);
          }}
          className="mt-4 inline-flex min-h-11 items-center rounded-full border border-border px-5 text-sm font-semibold hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Try again
        </button>
      </div>
    );
  }
  return <Approval order={load.order} cancelled={cancelled} />;
}

type CheckoutState = { state: "idle" } | { state: "opening" } | { state: "failed"; message: string };

/** Sends the order to PayPal. The page then leaves for PayPal, so "opening" lasts until it does. */
function useCheckout(orderId: string) {
  const [checkout, setCheckout] = useState<CheckoutState>({ state: "idle" });
  async function approve() {
    setCheckout({ state: "opening" });
    try {
      const { approval_url } = await startCheckout(orderId);
      goTo(approval_url);
    } catch (error) {
      setCheckout({ state: "failed", message: errorMessage(error) });
    }
  }
  return { checkout, approve };
}

function Approval({ order, cancelled }: { order: Order; cancelled: boolean }) {
  const makers = order.parts.length;
  const total = formatUsd(order.total_usd);
  const { checkout, approve } = useCheckout(order.id);
  const open = canCheckout(order.status);
  return (
    <div className="max-w-3xl">
      {cancelled && open ? (
        <div role="status" className="mb-8 rounded-2xl border border-border bg-surface p-5">
          <h2 className="font-semibold">You left PayPal before approving</h2>
          <p className="mt-1 leading-7 text-muted">
            Nothing was reserved and nothing was taken. The makers are still ready whenever you are.
          </p>
          <button
            type="button"
            onClick={approve}
            disabled={checkout.state === "opening"}
            className="mt-4 inline-flex min-h-11 items-center rounded-full border border-border px-5 text-sm font-semibold hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-wait disabled:opacity-60"
          >
            Try again
          </button>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm font-semibold text-accent">
          <span className="tracking-wide uppercase">{order.parent_order_id ? "Top-up order" : "Order"}</span>{" "}
          <span className="font-mono">{order.id}</span>
        </p>
        <Badge tone={order.status === "draft" ? "warning" : "accent"}>{ORDER_STATUS_LABELS[order.status]}</Badge>
      </div>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight text-balance sm:text-4xl">Approve this order</h1>

      {order.request ? (
        <section aria-labelledby="request-heading" className="mt-6 rounded-2xl border border-border bg-surface p-5">
          <h2 id="request-heading" className="text-sm font-semibold text-muted">
            What your AI agent asked for
          </h2>
          <p className="mt-1 text-lg font-medium">{order.request.summary}</p>
          <ul className="mt-3 flex flex-wrap gap-2 text-sm">
            <li className="rounded-full bg-background px-3 py-1">
              At most {formatUsd(order.request.max_unit_price)} each
            </li>
            <li className="rounded-full bg-background px-3 py-1">
              To {order.request.ship_to} by {formatDay(order.request.deadline)}
            </li>
          </ul>
        </section>
      ) : null}

      <section aria-labelledby="makers-heading" className="mt-8">
        <h2 id="makers-heading" className="text-xl font-semibold tracking-tight">
          {makers === 1 ? "One maker makes it" : `${makers} makers make it together`}
        </h2>
        <ul aria-label="Each maker's share" className="mt-4 divide-y divide-border rounded-2xl border border-border bg-surface">
          {order.parts.map((part) => (
            <ShareRow key={part.id} part={part} />
          ))}
        </ul>
        <div className="mt-4 flex flex-wrap items-baseline justify-between gap-2 px-1">
          <p className="text-muted">
            {order.units} items from {makers} {makers === 1 ? "maker" : "makers"}
          </p>
          <p className="text-lg">
            Total <span className="text-3xl font-semibold tabular-nums">{total}</span>
          </p>
        </div>
        <p className="mt-2 px-1 text-sm text-muted sm:text-right">{authorizationSentence(order.total_usd)}</p>
      </section>

      <section aria-labelledby="proof-heading" className="mt-8 rounded-2xl border border-accent/30 bg-accent-soft p-5">
        <h2 id="proof-heading" className="font-semibold">
          You pay once. Each maker is paid when she ships.
        </h2>
        <p className="mt-2 leading-7">
          When you approve, PayPal reserves {total}. Nothing is taken yet. Each maker&apos;s share is paid only when she
          sends a photo of her shipping receipt, and if a maker cannot deliver, her share is released back to you.
        </p>
      </section>

      <div className="mt-8">
        {open ? (
          <>
            <button
              type="button"
              onClick={approve}
              disabled={checkout.state === "opening"}
              aria-describedby="checkout-note"
              className="inline-flex min-h-12 w-full items-center justify-center rounded-full bg-accent px-6 text-base font-semibold text-accent-foreground transition-colors hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-wait disabled:opacity-70 sm:w-auto"
            >
              {checkout.state === "opening" ? "Opening PayPal…" : "Approve and pay with PayPal"}
            </button>
            <p id="checkout-note" className="mt-3 text-sm leading-6 text-muted">
              PayPal reserves the total now. Each maker is paid when she ships. Everything runs in the PayPal
              sandbox: no real money moves.
            </p>
            {checkout.state === "failed" ? (
              <p role="alert" className="mt-3 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm">
                {checkout.message}
              </p>
            ) : null}
          </>
        ) : order.status === "cancelled" ? (
          <p className="text-muted">This order was cancelled, so there is nothing to approve.</p>
        ) : (
          <p className="text-muted">
            You approved this order and PayPal holds the money for it.{" "}
            <Link
              href={`/approve/${encodeURIComponent(order.id)}/return`}
              className="font-semibold text-accent underline underline-offset-4"
            >
              See the receipt
            </Link>
          </p>
        )}
      </div>
    </div>
  );
}

function ShareRow({ part }: { part: OrderPart }) {
  const where = place(part.seller.city, part.seller.country);
  return (
    <li className="flex gap-4 p-4 sm:p-5">
      <div className="size-16 shrink-0 overflow-hidden rounded-xl border border-border bg-background sm:size-20">
        {part.photo ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={mediaUrl(part.photo)} alt="" className="size-full object-cover" />
        ) : null}
      </div>
      <div className="min-w-0 flex-1">
        {/* On a phone the amount gets its own line, so every row reads the same way. */}
        <div className="flex flex-col gap-1 sm:flex-row sm:flex-wrap sm:items-baseline sm:justify-between sm:gap-x-4">
          <h3 className="font-semibold">
            <Link href={`/stall/${part.seller.id}`} className="hover:underline">
              {part.seller.name}
            </Link>
            {where ? <span className="font-normal text-muted"> · {where}</span> : null}
          </h3>
          <p className="font-semibold tabular-nums">{formatUsd(part.amount_usd)}</p>
        </div>
        <p className="mt-1 text-sm text-muted">
          {part.quantity} × {formatUsd(part.unit_price_usd)}
          {part.product_title ? ` · ${part.product_title}` : null}
        </p>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          {part.delivery_date ? (
            <span className="rounded-full bg-background px-2.5 py-0.5">By {formatDay(part.delivery_date)}</span>
          ) : null}
          {part.trust_score ? (
            <span className="rounded-full bg-background px-2.5 py-0.5">
              Trust {part.trust_score}
              {part.trust_data_source === "seeded_demo" ? " (seeded)" : null}
            </span>
          ) : null}
          <RailChip part={part} />
        </div>
      </div>
    </li>
  );
}

export function ApprovalSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading the order" className="max-w-3xl">
      <div className="h-9 w-64 animate-pulse rounded bg-border/80" />
      <div className="mt-6 h-24 animate-pulse rounded-2xl bg-border/60" />
      <div className="mt-8 space-y-3">
        {[0, 1, 2].map((key) => (
          <div key={key} className="h-20 animate-pulse rounded-xl bg-border/60" />
        ))}
      </div>
    </div>
  );
}
