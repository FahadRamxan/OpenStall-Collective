"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge } from "@/components/badge";
import { useEventStream } from "@/hooks/use-event-stream";
import { errorMessage } from "@/lib/api";
import { formatUsd } from "@/lib/catalog";
import { changesOrders, getLatestOrder, ORDER_STATUS_LABELS, type Order } from "@/lib/orders";

/**
 * The /demo page's "Order" card: the latest collective order, as a buyer agent drafted it from the plan, with the
 * link to its approval page. It loads again whenever an order changes (drafted, approved, paid, released).
 */
export function OrderCard() {
  const { events } = useEventStream();
  // Events are newest first: the newest event about an order or one of its shares.
  const lastChange = events.find(changesOrders)?.id ?? 0;
  const [order, setOrder] = useState<Order | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getLatestOrder({ signal: controller.signal })
      .then((latest) => {
        setOrder(latest);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(reason));
      });
    return () => controller.abort();
  }, [lastChange]);

  return (
    <section aria-labelledby="order-heading" className="mt-10">
      <h2 id="order-heading" className="text-xl font-semibold tracking-tight">
        Order
      </h2>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-danger">
          The latest order could not be loaded: {error}
        </p>
      ) : null}
      {order ? (
        <div className="mt-4 rounded-xl border border-border bg-surface p-5 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm font-semibold text-accent">
              <span className="tracking-wide uppercase">{order.parent_order_id ? "Top-up order" : "Order"}</span>{" "}
              <span className="font-mono">{order.id}</span>
            </p>
            <Badge tone={order.status === "draft" ? "warning" : "accent"}>{ORDER_STATUS_LABELS[order.status]}</Badge>
          </div>
          <p className="mt-2 text-lg font-semibold">
            {order.units} units from {order.parts.length === 1 ? "1 maker" : `${order.parts.length} makers`},{" "}
            {formatUsd(order.total_usd)}
          </p>
          <p className="mt-1 leading-7 text-muted">
            {order.status === "draft"
              ? "A person approves it before anything is reserved: PayPal then holds the total, and each maker is paid when she ships."
              : "Approved. Each maker's share is paid when she proves she shipped."}
          </p>
          <Link
            href={`/approve/${encodeURIComponent(order.id)}`}
            className="mt-4 inline-flex min-h-11 items-center rounded-full bg-accent px-5 text-sm font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Open the approval page
          </Link>
        </div>
      ) : order === null ? (
        <p className="mt-4 rounded-xl border border-dashed border-border p-6 leading-7 text-muted">
          No order yet. When a buyer agent turns a plan into a draft order, it appears here with its approval page.
        </p>
      ) : error ? null : (
        <p aria-busy="true" className="mt-4 text-muted">
          Loading the latest order…
        </p>
      )}
    </section>
  );
}
