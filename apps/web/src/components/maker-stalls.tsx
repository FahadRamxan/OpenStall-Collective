"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge } from "@/components/badge";
import { errorMessage } from "@/lib/api";
import { formatUsd, getSellers, mediaUrl, place, type SellerCard } from "@/lib/catalog";

type Load = { state: "loading" } | { state: "loaded"; sellers: SellerCard[] } | { state: "failed"; message: string };

/** The home page's makers: one card per stall, each linking to it. */
export function MakerStalls() {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getSellers({ signal: controller.signal })
      .then((sellers) => setLoad({ state: "loaded", sellers }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setLoad({ state: "failed", message: errorMessage(error) });
      });
    return () => controller.abort();
  }, [attempt]);

  if (load.state === "loading") {
    return (
      <ul aria-label="Loading the makers" aria-busy="true" className="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2].map((key) => (
          <li key={key} className="overflow-hidden rounded-2xl border border-border bg-background">
            <div className="aspect-[4/3] animate-pulse bg-border/60" />
            <div className="space-y-2 p-4">
              <div className="h-4 w-1/3 animate-pulse rounded bg-border/80" />
              <div className="h-3 w-2/3 animate-pulse rounded bg-border/60" />
            </div>
          </li>
        ))}
      </ul>
    );
  }
  if (load.state === "failed") {
    return (
      <div role="alert" className="mt-6 rounded-xl border border-border bg-background p-5">
        <p className="font-medium">The makers could not be loaded.</p>
        <p className="mt-1 text-sm text-muted">{load.message}</p>
        <button
          type="button"
          onClick={() => {
            setLoad({ state: "loading" });
            setAttempt((count) => count + 1);
          }}
          className="mt-4 inline-flex min-h-11 items-center rounded-full border border-border px-5 text-sm font-semibold hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Try again
        </button>
      </div>
    );
  }
  if (load.sellers.length === 0) {
    return <p className="mt-6 text-muted">No stalls are open yet.</p>;
  }
  return (
    <ul className="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
      {load.sellers.map((seller) => (
        <li key={seller.id}>
          <MakerCard seller={seller} />
        </li>
      ))}
    </ul>
  );
}

function MakerCard({ seller }: { seller: SellerCard }) {
  const where = place(seller.city, seller.country);
  return (
    <Link
      href={`/stall/${seller.id}`}
      className="group block overflow-hidden rounded-2xl border border-border bg-background transition-shadow hover:shadow-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      <div className="relative aspect-[4/3] overflow-hidden bg-border/40">
        {seller.cover_photo ? (
          // Photos come from the API host; plain <img> keeps that simple and needs no image proxy.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={mediaUrl(seller.cover_photo)}
            alt=""
            className="size-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
          />
        ) : null}
        {seller.data_source === "seeded_demo" ? (
          <span className="absolute top-3 left-3">
            <Badge tone="warning">Seeded demo</Badge>
          </span>
        ) : null}
      </div>
      <div className="p-4">
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="text-lg font-semibold">{seller.name}</h3>
          <p className="text-sm text-muted">from {formatUsd(seller.from_price_usd)}</p>
        </div>
        {where ? <p className="text-sm text-muted">{where}</p> : null}
        <p className="mt-2 text-sm leading-6">{seller.headline}</p>
      </div>
    </Link>
  );
}
