"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/badge";
import { ApiError, errorMessage } from "@/lib/api";
import { formatUsd } from "@/lib/catalog";
import { approveFakePayPalOrder, getFakePayPalOrder, type FakePayPalOrder } from "@/lib/fake-paypal";
import { goTo } from "@/lib/navigation";

type Load =
  | { state: "loading" }
  | { state: "loaded"; order: FakePayPalOrder }
  | { state: "missing"; message: string }
  | { state: "failed"; message: string };

/**
 * Stands in for PayPal in fake mode, so the whole flow runs offline. It says plainly that it is a simulation and
 * uses no PayPal branding.
 */
export function FakePayPalView() {
  const token = useSearchParams().get("token") ?? "";
  const [load, setLoad] = useState<Load>({ state: "loading" });

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    getFakePayPalOrder(token, { signal: controller.signal })
      .then((order) => setLoad({ state: "loaded", order }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) setLoad({ state: "missing", message: error.message });
        else setLoad({ state: "failed", message: errorMessage(error) });
      });
    return () => controller.abort();
  }, [token]);

  const service = load.state === "loaded" && load.order.funding === "venmo" ? "Venmo" : "PayPal";
  return (
    <div className="mx-auto max-w-lg">
      <p
        role="note"
        className="flex flex-wrap items-center gap-2 rounded-xl border border-warning/40 bg-warning-soft px-4 py-3 text-sm leading-6"
      >
        <Badge tone="warning">Test mode</Badge>
        <span>
          This page stands in for {service} while OpenStall runs in fake mode. No PayPal or Venmo account is used and no
          money moves.
        </span>
      </p>
      <div className="mt-6 rounded-2xl border border-border bg-surface p-6 shadow-sm sm:p-8">
        <h1 className="text-2xl font-semibold tracking-tight">Simulated {service} (test mode)</h1>
        {!token ? (
          <Problem message="This link has no checkout in it. Go back to the order and press Approve." />
        ) : load.state === "loading" ? (
          <div aria-busy="true" aria-label="Loading the checkout" className="mt-6 h-40 animate-pulse rounded-xl bg-border/60" />
        ) : load.state === "missing" || load.state === "failed" ? (
          <Problem message={load.message} />
        ) : (
          <Checkout order={load.order} />
        )}
      </div>
    </div>
  );
}

function Problem({ message }: { message: string }) {
  return (
    <div role="alert" className="mt-4">
      <p className="leading-7 text-muted">{message}</p>
      <Link href="/demo" className="mt-4 inline-block font-semibold text-accent underline underline-offset-4">
        Go to the live demo
      </Link>
    </div>
  );
}

function Checkout({ order }: { order: FakePayPalOrder }) {
  const [state, setState] = useState<{ state: "idle" | "approving" } | { state: "failed"; message: string }>({
    state: "idle",
  });
  const total = formatUsd(order.total_usd);
  const approved = order.status === "APPROVED" || order.status === "COMPLETED";

  async function approve() {
    setState({ state: "approving" });
    try {
      goTo((await approveFakePayPalOrder(order.token)).redirect_url);
    } catch (error) {
      setState({ state: "failed", message: errorMessage(error) });
    }
  }

  return (
    <>
      <p className="mt-2 text-muted">
        OpenStall Collective asks you to approve order <span className="font-mono">{order.order_id}</span>
        {order.funding === "venmo" ? " with Venmo" : ""}.
      </p>
      <p className="mt-6 text-sm font-semibold text-muted">Total</p>
      <p className="text-4xl font-semibold tracking-tight tabular-nums">{total}</p>
      <ul aria-label="What you approve" className="mt-6 divide-y divide-border border-y border-border text-sm">
        {order.shares.map((share) => (
          <li key={share.reference_id} className="flex items-baseline justify-between gap-4 py-2.5">
            <span>{share.description}</span>
            <span className="font-semibold tabular-nums">{formatUsd(share.amount_usd)}</span>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-sm leading-6 text-muted">
        Approving reserves {total}. Each maker&apos;s share is taken only when she ships, and a share she cannot
        deliver is released.
      </p>
      {state.state === "failed" ? (
        <p role="alert" className="mt-4 rounded-xl border border-danger/30 bg-danger-soft px-4 py-3 text-sm">
          {state.message}
        </p>
      ) : null}
      <div className="mt-6 flex flex-col gap-3 sm:flex-row">
        <button
          type="button"
          onClick={approve}
          disabled={state.state === "approving"}
          className="inline-flex min-h-12 items-center justify-center rounded-full bg-foreground px-6 text-base font-semibold text-background transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-wait disabled:opacity-70"
        >
          {approved ? "Back to OpenStall" : state.state === "approving" ? "Approving…" : "Approve"}
        </button>
        {approved ? null : (
          <button
            type="button"
            onClick={() => goTo(order.cancel_url)}
            className="inline-flex min-h-12 items-center justify-center rounded-full border border-border px-6 text-base font-semibold hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Cancel and go back
          </button>
        )}
      </div>
    </>
  );
}
