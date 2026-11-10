"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/badge";
import { Confetti } from "@/components/confetti";
import { RailChip } from "@/components/rail-chip";
import {
  AdvanceLine,
  DeliveryLine,
  DisputeLine,
  MakersTold,
  NoticeLine,
  PART_TONES,
  ProofLine,
  shipDates,
} from "@/components/share-lines";
import { TopUps } from "@/components/top-ups";
import { ApiError, errorMessage } from "@/lib/api";
import { formatUsd, place } from "@/lib/catalog";
import {
  PART_STATUS_LABELS,
  authorizationSentence,
  awaitingNotices,
  confirmDelivery,
  confirmedWords,
  getOrder,
  isSimulated,
  reserveOrder,
  simulateDispute,
  simulateProof,
  type Order,
  type OrderPart,
} from "@/lib/orders";

/** How often the receipt asks whether PayPal's confirmations have arrived, and for how long. */
export const RECEIPT_POLL_MS = 2_000;
const MAX_POLLS = 30;

type Load =
  | { state: "reserving" }
  | { state: "reserved"; order: Order }
  | { state: "missing" }
  | { state: "failed"; message: string; canRetry: boolean };

function isPaid(part: OrderPart): boolean {
  return part.status === "captured" || part.status === "delivered";
}

/**
 * Shares whose PayPal confirmation is still on the way: their status, or for a paid share her payout when it goes
 * through PayPal. Not a share with a problem, nor one released mid-order, which PayPal never hears about.
 */
function awaitingPayPal(order: Order): boolean {
  return order.parts.some((part) => {
    if (part.status === "pending" || part.attention || part.nothing_to_confirm) return false;
    if (!part.confirmed_by_paypal) return true;
    return isPaid(part) && part.payout_via_paypal && !part.payout_confirmed;
  });
}


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

  // PayPal confirms each share with a webhook a moment later, and each maker is told about her share just after the
  // reservation: look again until every confirmation and every message is in.
  useEffect(() => {
    if (load.state !== "reserved" || polls >= MAX_POLLS) return;
    if (!awaitingPayPal(load.order) && !awaitingNotices(load.order)) return;
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
  return (
    <Receipt
      order={load.order}
      backToOrder={backToOrder}
      onOrder={(order) => {
        // A share was just paid: its confirmations follow, so look again from the start.
        setLoad({ state: "reserved", order });
        setPolls(0);
      }}
    />
  );
}

function Receipt({
  order,
  backToOrder,
  onOrder,
}: {
  order: Order;
  backToOrder: React.ReactNode;
  onOrder: (order: Order) => void;
}) {
  const total = formatUsd(order.total_usd);
  const simulated = isSimulated(order);
  const complete = order.status === "completed";
  const payPal = simulated ? "simulated PayPal" : "PayPal";
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
        <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
          {complete ? "Order complete" : `${simulated ? "Simulated PayPal" : "PayPal"} is holding ${total}`}
        </h1>
      </div>
      {/* Once when PayPal holds the money, once more when the order completes. */}
      <Confetti key={complete ? "complete" : "holding"} />
      <p className="mt-4 text-lg leading-8 text-muted">
        {complete
          ? "Every parcel that shipped has arrived, and every maker who shipped is paid."
          : "Nothing has been taken yet. Each maker is paid when she ships, and a share she cannot deliver goes back to you."}
      </p>
      {simulated ? (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-sm text-muted">
          <Badge tone="warning">Simulated</Badge>
          Test mode: a simulated PayPal stands in for PayPal, and no money moves.
        </p>
      ) : null}
      {order.paid_with === "venmo" ? (
        <p className="mt-3 text-sm font-medium">
          Approved with Venmo{simulated ? " (simulated)" : ""}: PayPal holds the money the same way, and each maker is
          paid when she ships.
        </p>
      ) : null}
      <p role="status" className="mt-3 text-sm font-medium">
        {awaitingPayPal(order) ? (
          <span className="text-muted">Waiting for {payPal} to confirm each share…</span>
        ) : (
          <span className="text-success">
            {simulated ? "Simulated PayPal confirmed every share." : "PayPal confirmed every share."}
          </span>
        )}
      </p>
      <MakersTold order={order} />

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
              <li key={part.id} className="flex flex-col gap-2 p-4 sm:flex-row sm:items-start sm:justify-between sm:p-5">
                <div className="min-w-0">
                  <p className="font-semibold">
                    {part.seller.name}
                    {where ? <span className="font-normal text-muted"> · {where}</span> : null}
                  </p>
                  <p className="mt-0.5 text-sm text-muted">
                    {part.quantity} × {formatUsd(part.unit_price_usd)}
                    {shipDates(part)}
                  </p>
                  <div className="mt-2">
                    <RailChip part={part} />
                  </div>
                  <NoticeLine part={part} />
                  <AdvanceLine part={part} simulated={simulated} />
                  <ProofLine part={part} simulated={simulated} />
                  <DisputeLine part={part} />
                  <DeliveryLine part={part} />
                  {part.status === "captured" ? (
                    <ConfirmDelivery orderId={order.id} part={part} onOrder={onOrder} />
                  ) : null}
                  {simulated && part.status === "authorized" ? (
                    <SimulateProof part={part} onOrder={onOrder} />
                  ) : null}
                  {simulated && isPaid(part) && !part.dispute ? (
                    <SimulateDispute part={part} onOrder={onOrder} />
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 sm:flex-col sm:items-end">
                  <p className="font-semibold tabular-nums">{formatUsd(part.amount_usd)}</p>
                  <Badge tone={PART_TONES[part.status]}>{PART_STATUS_LABELS[part.status]}</Badge>
                  <PayPalNote part={part} simulated={simulated} />
                </div>
              </li>
            );
          })}
        </ul>
        <TopUps order={order} you />
        {complete && order.paid_usd !== undefined ? (
          <dl aria-label="Where the total went" className="mt-4 space-y-1 px-1">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <dt className="text-muted">Paid to the makers, on proof of shipping</dt>
              <dd className="text-3xl font-semibold tabular-nums">{formatUsd(order.paid_usd)}</dd>
            </div>
            {order.released_usd && Number(order.released_usd) > 0 ? (
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <dt className="text-muted">Released back to you, never charged</dt>
                <dd className="font-semibold tabular-nums">{formatUsd(order.released_usd)}</dd>
              </div>
            ) : null}
          </dl>
        ) : (
          <div className="mt-4 flex flex-wrap items-baseline justify-between gap-2 px-1">
            <p className="text-muted">Reserved at {payPal}</p>
            <p className="text-3xl font-semibold tabular-nums">{total}</p>
          </div>
        )}
        <p className="mt-2 px-1 text-sm text-muted">{authorizationSentence(order.total_usd)}</p>
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

type ProofState = { state: "idle" } | { state: "sending" } | { state: "failed"; message: string };

/**
 * Fake mode only: stands in for her shipping receipt photo (prompt 32), so her share is paid on proof. Disabled, with
 * the reason, for a maker no payout rail can reach yet: her share is never captured.
 */
function SimulateProof({ part, onOrder }: { part: OrderPart; onOrder: (order: Order) => void }) {
  const [proof, setProof] = useState<ProofState>({ state: "idle" });
  const blocked = part.payout_rail === "unavailable";
  const reasonId = `proof-reason-${part.id}`;
  async function send() {
    setProof({ state: "sending" });
    try {
      onOrder(await simulateProof(part.id));
    } catch (error) {
      setProof({ state: "failed", message: errorMessage(error) });
    }
  }
  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={send}
        disabled={blocked || proof.state === "sending"}
        aria-describedby={blocked ? reasonId : undefined}
        className="inline-flex min-h-11 items-center gap-2 rounded-full border border-border px-4 text-sm font-semibold hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
      >
        {proof.state === "sending" ? "Sending proof…" : "Simulate proof of shipping"}
        <span className="rounded-full bg-warning-soft px-2 py-0.5 text-xs text-warning">Simulated</span>
      </button>
      {blocked ? (
        <p id={reasonId} className="mt-1 text-xs text-muted">
          Not possible yet: {part.payout_label.charAt(0).toLowerCase() + part.payout_label.slice(1)}. Her share
          stays reserved and is not captured.
        </p>
      ) : null}
      {proof.state === "failed" ? (
        <p role="alert" className="mt-1 text-xs font-semibold text-danger">
          {proof.message}
        </p>
      ) : null}
    </div>
  );
}

/**
 * Fake mode only: the buyer opens a PayPal dispute on a paid share, saying the parcel never came (prompt 56).
 * OpenStall answers it with her proof of shipping, and simulated PayPal decides.
 */
function SimulateDispute({ part, onOrder }: { part: OrderPart; onOrder: (order: Order) => void }) {
  const [dispute, setDispute] = useState<ProofState>({ state: "idle" });
  async function open() {
    setDispute({ state: "sending" });
    try {
      onOrder(await simulateDispute(part.id));
    } catch (error) {
      setDispute({ state: "failed", message: errorMessage(error) });
    }
  }
  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={open}
        disabled={dispute.state === "sending"}
        className="inline-flex min-h-11 items-center gap-2 rounded-full border border-border px-4 text-sm font-semibold hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
      >
        {dispute.state === "sending" ? "Opening the dispute…" : "Dispute this parcel at PayPal"}
        <span className="rounded-full bg-warning-soft px-2 py-0.5 text-xs text-warning">Simulated</span>
      </button>
      {dispute.state === "failed" ? (
        <p role="alert" className="mt-1 text-xs font-semibold text-danger">
          {dispute.message}
        </p>
      ) : null}
    </div>
  );
}

type DeliveryState = { state: "idle" } | { state: "sending" } | { state: "failed"; message: string };

/**
 * Her parcel arrived: the buyer confirms it here, share by share (prompt 34). Her share is then delivered, with the
 * day it arrived, and the order completes with its last parcel. No money moves: she was paid when she shipped.
 */
function ConfirmDelivery({
  orderId,
  part,
  onOrder,
}: {
  orderId: string;
  part: OrderPart;
  onOrder: (order: Order) => void;
}) {
  const [delivery, setDelivery] = useState<DeliveryState>({ state: "idle" });
  async function confirm() {
    setDelivery({ state: "sending" });
    try {
      onOrder(await confirmDelivery(orderId, part.id));
    } catch (error) {
      setDelivery({ state: "failed", message: errorMessage(error) });
    }
  }
  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={confirm}
        disabled={delivery.state === "sending"}
        aria-label={`Confirm delivery of ${part.seller.name}'s parcel`}
        className="inline-flex min-h-11 items-center rounded-full border border-border px-4 text-sm font-semibold hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
      >
        {delivery.state === "sending" ? "Confirming…" : "Confirm delivery"}
      </button>
      <p className="mt-1 text-xs text-muted">Press it once her parcel has arrived. She was already paid when she shipped.</p>
      {delivery.state === "failed" ? (
        <p role="alert" className="mt-1 text-xs font-semibold text-danger">
          {delivery.message}
        </p>
      ) : null}
    </div>
  );
}

/** Whether PayPal itself confirmed where the share stands, from its verified webhooks, or simulated PayPal did. */
function PayPalNote({ part, simulated }: { part: OrderPart; simulated: boolean }) {
  if (part.attention) {
    return <p className="text-xs font-semibold text-danger">{part.attention}</p>;
  }
  if (part.status === "pending") return null;
  if (part.nothing_to_confirm) {
    return <p className="text-xs text-muted">Never captured; nothing for PayPal to confirm</p>;
  }
  if (!part.confirmed_by_paypal) {
    return <p className="text-xs text-muted">{simulated ? "Waiting for simulated PayPal…" : "Waiting for PayPal…"}</p>;
  }
  return (
    <p className="inline-flex items-center gap-1 text-xs font-semibold text-success">
      <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.5" className="size-3.5">
        <path d="M4.5 10.5l3.5 3.5 7.5-8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {confirmedWords(simulated)}
    </p>
  );
}
