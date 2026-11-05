"use client";

import Link from "next/link";

import { type BadgeTone } from "@/components/badge";
import { languageName, mediaUrl } from "@/lib/catalog";
import { formatDay, noticeChannel, type Order, type OrderPart, type PartStatus } from "@/lib/orders";

/*
 * What a maker's share says beyond its money, shared by the receipt (/approve/{id}/return) and the live demo's
 * Payments panel: when it ships and arrives, whether she was told about it, and her proof of shipping and whether
 * its tracking is on the PayPal order.
 */

/** Each share's status as a badge tone. */
export const PART_TONES: Record<PartStatus, BadgeTone> = {
  pending: "neutral",
  authorized: "accent",
  captured: "success",
  delivered: "success",
  released: "neutral",
};

/**
 * " · ships by December 1, 2026, arrives by December 10, 2026": when her share must leave her, and when it must reach
 * the buyer. Without a ship-by date from the API, the delivery date alone.
 */
export function shipDates(part: OrderPart): string {
  const leaves = part.ship_by ?? part.delivery_date;
  if (!leaves) return "";
  const arrives =
    part.delivery_date && part.ship_by && part.ship_by !== part.delivery_date
      ? `, arrives by ${formatDay(part.delivery_date)}`
      : "";
  return ` · ships by ${formatDay(leaves)}${arrives}`;
}

/** Under the PayPal line: whether every maker has been told about her share yet. */
export function MakersTold({ order }: { order: Order }) {
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

/**
 * When the buyer received her parcel, and whether by its delivery date: "Received December 6, 2026, on time".
 * Nothing before it arrived.
 */
export function DeliveryLine({ part }: { part: OrderPart }) {
  if (part.status !== "delivered" || !part.delivered_at) return null;
  const late = part.on_time === false && part.delivery_date ? `, late: it was due ${formatDay(part.delivery_date)}` : "";
  return (
    <p className="mt-2 inline-flex flex-wrap items-center gap-1 text-xs font-semibold text-success">
      <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.5" className="size-3.5">
        <path d="M4.5 10.5l3.5 3.5 7.5-8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      Received {formatDay(part.delivered_at.slice(0, 10))}
      {part.on_time ? ", on time" : late}
    </p>
  );
}

/** Whether she was told about her share: where, in which language, and a link to her chat. */
export function NoticeLine({ part }: { part: OrderPart }) {
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
 * Her proof of shipping: the tracking she confirmed (she is paid on it), with her courier receipt photo, and whether
 * it is on her payment at PayPal; or, while she is still answering OpenStall, what was read from it.
 */
export function ProofLine({ part, simulated }: { part: OrderPart; simulated: boolean }) {
  const proof = part.proof;
  if (part.tracking_number) {
    const courier = part.carrier && part.carrier !== "OTHER" ? ` with ${part.carrier}` : "";
    const payPalOrder = simulated ? "the simulated PayPal order" : "the PayPal order";
    const captured = part.status === "captured" || part.status === "delivered";
    return (
      <div className="mt-2 text-xs">
        <p className="flex flex-wrap items-center gap-x-2">
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
        {part.tracking_on_paypal ? (
          <p className="mt-1 inline-flex items-center gap-1 font-semibold text-success">
            <svg aria-hidden="true" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2.5" className="size-3.5">
              <path d="M4.5 10.5l3.5 3.5 7.5-8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Tracking on {payPalOrder}
          </p>
        ) : part.tracking_on_paypal === false ? (
          <p className="mt-1 text-muted">
            {captured
              ? `Not on ${payPalOrder} yet: it is tried again when this page is opened again.`
              : `It goes on ${payPalOrder} once her share is captured.`}
          </p>
        ) : null}
      </div>
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
