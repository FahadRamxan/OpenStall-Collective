"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge, type BadgeTone } from "@/components/badge";
import { RailChip } from "@/components/rail-chip";
import { ApiError, errorMessage } from "@/lib/api";
import { formatUsd, languageName, mediaUrl, place } from "@/lib/catalog";
import {
  PART_STATUS_LABELS,
  authorizationSentence,
  awaitingNotices,
  confirmedWords,
  formatDay,
  getOrder,
  isSimulated,
  noticeChannel,
  reserveOrder,
  simulateProof,
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
          {simulated ? "Simulated PayPal" : "PayPal"} is holding {total}
        </h1>
      </div>
      <p className="mt-4 text-lg leading-8 text-muted">
        Nothing has been taken yet. Each maker is paid when she ships, and a share she cannot deliver goes back to
        you.
      </p>
      {simulated ? (
        <p className="mt-3 flex flex-wrap items-center gap-2 text-sm text-muted">
          <Badge tone="warning">Simulated</Badge>
          Test mode: a simulated PayPal stands in for PayPal, and no money moves.
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
                  <ProofLine part={part} />
                  {simulated && part.status === "authorized" ? (
                    <SimulateProof part={part} onOrder={onOrder} />
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
        <div className="mt-4 flex flex-wrap items-baseline justify-between gap-2 px-1">
          <p className="text-muted">Reserved at {payPal}</p>
          <p className="text-3xl font-semibold tabular-nums">{total}</p>
        </div>
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

/**
 * " · ships by December 1, 2026, arrives by December 10, 2026": when her share must leave her, and when it must reach
 * the buyer. Without a ship-by date from the API, the delivery date alone.
 */
function shipDates(part: OrderPart): string {
  const leaves = part.ship_by ?? part.delivery_date;
  if (!leaves) return "";
  const arrives =
    part.delivery_date && part.ship_by && part.ship_by !== part.delivery_date
      ? `, arrives by ${formatDay(part.delivery_date)}`
      : "";
  return ` · ships by ${formatDay(leaves)}${arrives}`;
}

/** Under the PayPal line: whether every maker has been told about her share yet. */
function MakersTold({ order }: { order: Order }) {
  // Only shares PayPal holds or paid are told; and only an API that reports notices says anything here.
  const shares = order.parts.filter(
    (part) => part.notice !== undefined && part.status !== "pending" && part.status !== "released",
  );
  if (shares.length === 0) return null;
  const told = shares.filter((part) => part.notice?.state === "sent").length;
  const unreachable = shares.filter((part) => part.notice?.state === "failed").map((part) => part.seller.name);
  if (told === shares.length) {
    return (
      <p role="status" className="mt-1 text-sm font-medium text-success">
        Each maker has been told about her share, in her own language.
      </p>
    );
  }
  return (
    <p role="status" className="mt-1 text-sm font-medium text-muted">
      {unreachable.length > 0
        ? `${told} of ${shares.length} makers told. Not reached yet: ${unreachable.join(", ")}.`
        : "Telling each maker about her share…"}
    </p>
  );
}

/** Whether she was told about her share: where, in which language, and a link to her chat. */
function NoticeLine({ part }: { part: OrderPart }) {
  const notice = part.notice;
  if (!notice) {
    return part.notice === null && part.status === "authorized" ? (
      <p className="mt-2 text-xs text-muted">Telling her about her share…</p>
    ) : null;
  }
  if (notice.state === "sending") {
    return <p className="mt-2 text-xs text-muted">Telling her about her share {noticeChannel(notice)}…</p>;
  }
  if (notice.state === "failed") {
    return (
      <p className="mt-2 text-xs font-semibold text-danger">
        Not told yet: {notice.reason ?? "WhatsApp did not take the message"}. OpenStall tries again when this page is
        opened again.
      </p>
    );
  }
  const language = languageName(notice.language);
  return (
    <p className="mt-2 flex flex-wrap items-center gap-x-2 text-xs">
      <span className="inline-flex items-center gap-1 font-semibold text-success">
        <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.5" className="size-3.5">
          <path d="M4.5 10.5l3.5 3.5 7.5-8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        Told {noticeChannel(notice)}
        {language ? `, in ${language}` : null}
      </span>
      <Link
        href={`/seller-chat?seller=${encodeURIComponent(part.seller.id)}`}
        className="font-semibold text-accent underline underline-offset-4 hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        See {part.seller.name}&apos;s chat
      </Link>
    </p>
  );
}

/**
 * Her proof of shipping: the tracking she confirmed (she is paid on it), with her courier receipt photo; or, while she
 * is still answering OpenStall, what was read from it.
 */
function ProofLine({ part }: { part: OrderPart }) {
  const proof = part.proof;
  if (part.tracking_number) {
    const courier = part.carrier && part.carrier !== "OTHER" ? ` with ${part.carrier}` : "";
    return (
      <p className="mt-2 flex flex-wrap items-center gap-x-2 text-xs">
        <span>
          <span className="font-semibold">Shipped{courier}:</span>{" "}
          <span className="font-mono break-all">{part.tracking_number}</span>
        </span>
        {proof?.photo_url ? (
          <a
            href={mediaUrl(proof.photo_url)}
            target="_blank"
            rel="noreferrer"
            className="font-semibold text-accent underline underline-offset-4 hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            See her courier receipt
          </a>
        ) : null}
      </p>
    );
  }
  if (proof?.state === "awaiting_confirmation") {
    return (
      <p className="mt-2 text-xs text-muted">
        Her courier receipt reads {proof.carrier ? `${proof.carrier}, ` : ""}tracking{" "}
        <span className="font-mono">{proof.tracking_number}</span>: waiting for her to confirm it.
      </p>
    );
  }
  if (proof?.state === "awaiting_number") {
    return (
      <p className="mt-2 text-xs text-muted">
        Her courier receipt arrived; waiting for her to type its tracking number.
      </p>
    );
  }
  return null;
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
