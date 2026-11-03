"use client";

import { Fragment, useEffect, useState } from "react";

import { Badge } from "@/components/badge";
import { useEventStream } from "@/hooks/use-event-stream";
import { errorMessage } from "@/lib/api";
import { formatUsd } from "@/lib/catalog";
import {
  capacityDetails,
  changesLimits,
  getLimits,
  priceDetails,
  type Limits,
  type MakerLimits,
} from "@/lib/limits";
import { formatDay } from "@/lib/orders";

/**
 * The /demo page's "Offer rules" panel: each live maker's lowest price and how many she can still make by the
 * deadline, worked out by the same code that checks every offer, so viewers know the checks before the offers arrive.
 * It loads again when a share is reserved, paid or released, because her reserved shares use up her capacity.
 */
export function OfferRules() {
  const { events } = useEventStream();
  // Events are newest first: the newest event that can change a maker's limits.
  const lastChange = events.find(changesLimits)?.id ?? 0;
  const [limits, setLimits] = useState<Limits | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getLimits({ signal: controller.signal })
      .then((loaded) => {
        setLimits(loaded);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(reason));
      });
    return () => controller.abort();
  }, [lastChange]);

  return (
    <section aria-labelledby="rules-heading" className="mt-10">
      <h2 id="rules-heading" className="text-xl font-semibold tracking-tight">
        Offer rules
      </h2>
      <p className="mt-1 leading-7 text-muted">
        Code checks every offer a seller agent makes; the model only proposes a price. An offer counts only if its
        price is at least her lowest price (her floor, or her list price less her maximum discount, whichever is
        higher) and no more than the buyer&apos;s cap, if she can make and ship that many by the deadline, and if
        delivery gives her the notice she needs.
      </p>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-danger">
          {limits ? "The makers' limits could not be updated" : "The makers' limits could not be loaded"}: {error}
        </p>
      ) : null}
      {limits ? (
        <LimitsTable limits={limits} />
      ) : error ? null : (
        <p aria-busy="true" className="mt-4 text-muted">
          Loading the makers&apos; limits…
        </p>
      )}
    </section>
  );
}

function LimitsTable({ limits }: { limits: Limits }) {
  const deadline = formatDay(limits.deadline);
  const daysAhead = Math.round((Date.parse(limits.deadline) - Date.parse(limits.today)) / 86_400_000);
  return (
    <>
      {limits.makers.length > 0 ? (
        <div className="mt-4 overflow-hidden rounded-xl border border-border bg-surface">
          <table className="w-full text-left text-sm">
            <caption className="border-b border-border px-4 py-3 text-left leading-6 text-muted sm:px-5">
              Each maker&apos;s limits for an order due {deadline}, {daysAhead} days from today.
            </caption>
            <thead className="text-xs font-medium tracking-wide text-muted uppercase">
              <tr>
                <th scope="col" className="px-4 py-2 font-medium sm:px-5">
                  Maker
                </th>
                <th scope="col" className="px-2 py-2 font-medium sm:px-4">
                  Lowest price
                </th>
                <th scope="col" className="px-4 py-2 text-right font-medium sm:px-5">
                  Can make by {shortDay(limits.deadline)}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {limits.makers.map((maker) => (
                <MakerRow key={maker.product_id} maker={maker} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="mt-4 rounded-xl border border-dashed border-border p-6 leading-7 text-muted">
          No maker has a live listing yet, so there are no limits to show.
        </p>
      )}
      {limits.unreadable.length > 0 ? (
        <ul aria-label="Makers whose limits cannot be checked" className="mt-3 space-y-1 text-sm text-warning">
          {limits.unreadable.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

/** On a phone the details under each number wrap, so the three columns still fit. */
function MakerRow({ maker }: { maker: MakerLimits }) {
  return (
    <tr data-seller={maker.seller_id} className="align-top">
      <th scope="row" className="px-4 py-3 text-left font-normal sm:px-5">
        <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="font-semibold">{maker.seller_name}</span>
          {maker.data_source === "seeded_demo" ? <Badge tone="warning">Seeded demo</Badge> : null}
        </span>
        <span className="mt-0.5 block leading-5 break-words text-muted">
          {[maker.city, maker.product_title].filter(Boolean).join(" · ")}
        </span>
      </th>
      <td className="px-2 py-3 sm:px-4">
        <span className="block text-base font-semibold tabular-nums">{formatUsd(maker.lowest_price_usd)}</span>
        <Details parts={priceDetails(maker)} />
      </td>
      <td className="px-4 py-3 text-right sm:px-5">
        <span className="block text-base font-semibold tabular-nums">
          {maker.capacity_by_deadline} <span className="text-sm font-normal text-muted">units</span>
        </span>
        <Details parts={capacityDetails(maker)} />
      </td>
    </tr>
  );
}

/**
 * Small print joined with " · ". From the sm breakpoint up each part stays on one line, so "ships in 9 days" never
 * breaks in the middle; on a phone they wrap anywhere, so the three columns still fit. The dot stays with the part
 * before it.
 */
function Details({ parts }: { parts: string[] }) {
  return (
    <span className="mt-0.5 block leading-5 text-muted">
      {parts.map((part, index) => (
        <Fragment key={part}>
          {index > 0 ? " · " : null}
          <span className="sm:whitespace-nowrap">{part}</span>
        </Fragment>
      ))}
    </span>
  );
}

const SHORT_DAY = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

/** "Dec 10" from "2026-12-10", the same in every time zone. */
function shortDay(isoDate: string): string {
  const day = new Date(`${isoDate}T00:00:00Z`);
  return Number.isNaN(day.getTime()) ? isoDate : SHORT_DAY.format(day);
}
