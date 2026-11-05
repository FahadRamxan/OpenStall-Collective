"use client";

import { Badge } from "@/components/badge";
import { RailChip } from "@/components/rail-chip";
import { MakersTold, NoticeLine, PART_TONES, ProofLine, shipDates } from "@/components/share-lines";
import { useLatestOrder } from "@/hooks/use-latest-order";
import { formatUsd, place } from "@/lib/catalog";
import { PART_STATUS_LABELS, isSimulated, type Order, type OrderPart } from "@/lib/orders";

const PAID = new Set(["captured", "delivered"]);

/** After the person approves: each step of the order, and whether the latest order has got there. */
export function orderSteps(order: Order): { name: string; done: boolean }[] {
  const live = order.parts.filter((part) => part.status !== "pending" && part.status !== "released");
  return [
    { name: "Reserved at PayPal", done: !["draft", "awaiting_approval"].includes(order.status) },
    { name: "Makers told", done: live.length > 0 && live.every((part) => part.notice?.state === "sent") },
    { name: "Paid on proof", done: order.parts.some((part) => PAID.has(part.status)) },
    { name: "Tracking on PayPal", done: order.parts.some((part) => part.tracking_on_paypal) },
  ];
}

function total(parts: OrderPart[]): number {
  return parts.reduce((sum, part) => sum + Math.round(Number(part.amount_usd) * 100), 0) / 100;
}

/**
 * The /demo page's Payments panel, for the latest order: how far it has got since the person approved it, where the
 * money stands, and each maker's share: told in her language, her courier receipt, paid on proof, her tracking on
 * the PayPal order. It follows the order live (LatestOrderProvider).
 */
export function PaymentsPanel() {
  const { order, error } = useLatestOrder();
  return (
    <section aria-labelledby="payments-heading" className="mt-10">
      <h2 id="payments-heading" className="text-xl font-semibold tracking-tight">
        Payments
      </h2>
      <p className="mt-1 leading-7 text-muted">
        One PayPal authorization holds the whole order. Each maker is told in her language, photographs her courier
        receipt, and is paid on that proof, with her tracking on the PayPal order.
      </p>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-danger">
          The latest order could not be loaded: {error}
        </p>
      ) : null}
      {order ? (
        <Payments order={order} />
      ) : order === null ? (
        <p className="mt-4 rounded-xl border border-dashed border-border p-6 leading-7 text-muted">
          No order yet. Once a person approves one, PayPal holds it here, and each maker&apos;s payment follows.
        </p>
      ) : error ? null : (
        <p aria-busy="true" className="mt-4 text-muted">
          Loading the latest order…
        </p>
      )}
    </section>
  );
}

function Payments({ order }: { order: Order }) {
  const simulated = isSimulated(order);
  const steps = orderSteps(order);
  const next = steps.findIndex((step) => !step.done);
  const reserved = steps[0].done;
  const paid = order.parts.filter((part) => PAID.has(part.status));
  const released = order.parts.filter((part) => part.status === "released");
  const payPal = simulated ? "simulated PayPal" : "PayPal";
  return (
    <div className="mt-4 rounded-xl border border-border bg-surface p-5 sm:p-6">
      <p className="text-sm font-semibold text-accent">
        <span className="tracking-wide uppercase">Order</span> <span className="font-mono">{order.id}</span>
        {simulated ? (
          <span className="ml-2 align-middle">
            <Badge tone="warning">Simulated</Badge>
          </span>
        ) : null}
      </p>
      <ol aria-label="The order's steps after approval" className="mt-3 flex flex-wrap gap-2 text-sm">
        {steps.map((step, index) => {
          const state = step.done ? "done" : index === next ? "now" : "waiting";
          return (
            <li
              key={step.name}
              data-state={state}
              aria-current={state === "now" ? "step" : undefined}
              className={`rounded-full px-3 py-1 ${
                state === "done"
                  ? "bg-success-soft text-success"
                  : state === "now"
                    ? "bg-accent-soft font-semibold text-accent"
                    : "bg-background text-muted"
              }`}
            >
              {step.done ? "✓ " : null}
              {step.name}
            </li>
          );
        })}
      </ol>
      <p className="mt-3 leading-7">
        {reserved ? (
          <>
            <span className="font-semibold">{formatUsd(order.total_usd)}</span> reserved at {payPal}.{" "}
            {paid.length > 0 ? (
              <>
                <span className="font-semibold">{formatUsd(String(total(paid)))}</span> paid on proof to{" "}
                {paid.length === 1 ? "1 maker" : `${paid.length} makers`}
              </>
            ) : (
              <>Nothing is captured yet: each maker is paid when she proves she shipped</>
            )}
            {released.length > 0 ? (
              <>
                ; <span className="font-semibold">{formatUsd(String(total(released)))}</span> released back to the
                buyer
              </>
            ) : null}
            .
          </>
        ) : (
          <>Nothing is reserved yet: a person approves the order first, and PayPal then holds the total.</>
        )}
      </p>
      <MakersTold order={order} />
      <ul aria-label="Each maker's payment" className="mt-4 divide-y divide-border border-t border-border">
        {order.parts.map((part) => {
          const where = place(part.seller.city, part.seller.country);
          return (
            <li key={part.id} className="flex flex-col gap-2 py-4 sm:flex-row sm:items-start sm:justify-between">
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
                <ProofLine part={part} simulated={simulated} />
              </div>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 sm:flex-col sm:items-end">
                <p className="font-semibold tabular-nums">{formatUsd(part.amount_usd)}</p>
                <Badge tone={PART_TONES[part.status]}>{PART_STATUS_LABELS[part.status]}</Badge>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
