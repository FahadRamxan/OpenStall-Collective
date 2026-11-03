"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/badge";
import { ApiError, errorMessage } from "@/lib/api";
import {
  formatUsd,
  getSeller,
  languageName,
  mediaUrl,
  percent,
  place,
  swatch,
  type Product,
  type SellerDetail,
  type TrustSummary,
} from "@/lib/catalog";

type Load =
  | { state: "loading" }
  | { state: "loaded"; seller: SellerDetail }
  | { state: "missing" }
  | { state: "failed"; message: string };

/** One maker's stall: who she is, what she makes, and her trust record. */
export function StallView() {
  const { id } = useParams<{ id: string }>();
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getSeller(id, { signal: controller.signal })
      .then((seller) => setLoad({ state: "loaded", seller }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 404) setLoad({ state: "missing" });
        else setLoad({ state: "failed", message: errorMessage(error) });
      });
    return () => controller.abort();
  }, [id, attempt]);

  useEffect(() => {
    if (load.state === "loaded") document.title = `${load.seller.name}'s stall · OpenStall Collective`;
  }, [load]);

  if (load.state === "loading") return <StallSkeleton />;
  if (load.state === "missing") {
    return (
      <div className="max-w-2xl">
        <h1 className="text-3xl font-semibold tracking-tight">No stall here</h1>
        <p className="mt-4 text-lg leading-8 text-muted">
          There is no maker at this address. The stall may have closed, or the link may be wrong.
        </p>
        <Link href="/#makers" className="mt-6 inline-block font-semibold text-accent underline underline-offset-4">
          See all the makers
        </Link>
      </div>
    );
  }
  if (load.state === "failed") {
    return (
      <div role="alert" className="max-w-2xl rounded-xl border border-border bg-surface p-6">
        <h1 className="text-2xl font-semibold tracking-tight">This stall could not be loaded</h1>
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
  return <Stall seller={load.seller} />;
}

function Stall({ seller }: { seller: SellerDetail }) {
  const where = place(seller.city, seller.country);
  const language = languageName(seller.language);
  const seeded = seller.data_source === "seeded_demo";
  return (
    <>
      <Link href="/#makers" className="text-sm font-medium text-accent underline-offset-4 hover:underline">
        ← All makers
      </Link>
      <header className="mt-4">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-4xl font-semibold tracking-tight">{seller.name}</h1>
          {seeded ? <Badge tone="warning">Seeded demo seller</Badge> : null}
        </div>
        <p className="mt-2 text-lg text-muted">
          {[where, language ? `Speaks ${language}` : null].filter(Boolean).join(" · ")}
        </p>
      </header>

      <section aria-labelledby="listings-heading" className="mt-10">
        <h2 id="listings-heading" className="sr-only">
          What {seller.name} makes
        </h2>
        {seller.products.length === 0 ? (
          <p className="text-muted">{seller.name} has nothing listed right now.</p>
        ) : (
          <ul className="space-y-10">
            {seller.products.map((product) => (
              <li key={product.id}>
                <ProductPanel product={product} />
              </li>
            ))}
          </ul>
        )}
      </section>

      {seller.trust ? <TrustRecord name={seller.name} trust={seller.trust} /> : null}
    </>
  );
}

function ProductPanel({ product }: { product: Product }) {
  const [shown, setShown] = useState(0);
  const photo = product.photos[shown];
  return (
    <article aria-labelledby={`${product.id}-title`} className="grid gap-6 md:grid-cols-2 md:gap-10">
      <div>
        <div className="aspect-square overflow-hidden rounded-2xl border border-border bg-surface">
          {photo ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={mediaUrl(photo)} alt={`${product.title}, photo ${shown + 1}`} className="size-full object-cover" />
          ) : null}
        </div>
        {product.photos.length > 1 ? (
          <div className="mt-3 flex gap-3">
            {product.photos.map((path, index) => (
              <button
                key={path}
                type="button"
                aria-label={`Show photo ${index + 1}`}
                aria-pressed={index === shown}
                onClick={() => setShown(index)}
                className={`size-16 overflow-hidden rounded-lg border-2 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${index === shown ? "border-accent" : "border-transparent"}`}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={mediaUrl(path)} alt="" className="size-full object-cover" />
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <div>
        <h3 id={`${product.id}-title`} className="text-2xl font-semibold tracking-tight">
          {product.title}
        </h3>
        <p className="mt-2 text-3xl font-semibold tabular-nums">{formatUsd(product.price_usd)}</p>
        <p className="mt-4 leading-7 text-muted">{product.description}</p>

        {product.variants.length > 0 ? (
          <div className="mt-6">
            <h4 className="text-sm font-semibold">Colours</h4>
            <ul aria-label="Colours" className="mt-2 flex flex-wrap gap-2">
              {product.variants.map((variant) => (
                <li
                  key={variant}
                  className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-sm capitalize"
                >
                  {swatch(variant) ? (
                    <span
                      aria-hidden="true"
                      className="size-3.5 rounded-full border border-black/10"
                      style={{ backgroundColor: swatch(variant) ?? undefined }}
                    />
                  ) : null}
                  {variant}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <dl className="mt-6 grid grid-cols-2 gap-3">
          <Fact label="Makes" value={`${product.capacity_per_week} a week`} />
          <Fact label="Ships in" value={`${product.ship_days} days`} />
          <Fact label="From" value={product.ship_from_city} />
          <Fact label="Kind" value={sentenceCase(product.category)} />
        </dl>
      </div>
    </article>
  );
}

/** "Home textiles" from "home textiles". */
function sentenceCase(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-3">
      <dt className="text-xs font-medium tracking-wide text-muted uppercase">{label}</dt>
      <dd className="mt-1 font-semibold">{value}</dd>
    </div>
  );
}

function TrustRecord({ name, trust }: { name: string; trust: TrustSummary }) {
  const rates = [
    { label: "On time", value: trust.on_time_rate, good: true },
    { label: "Disputes", value: trust.dispute_rate, good: false },
    { label: "Original photos", value: trust.photo_originality, good: true },
  ];
  return (
    <section aria-labelledby="trust-heading" className="mt-14 rounded-2xl border border-border bg-surface p-5 sm:p-7">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="trust-heading" className="text-xl font-semibold tracking-tight">
          {name}&apos;s trust record
        </h2>
        <p className="text-sm text-muted">
          Score <span className="text-2xl font-semibold text-foreground tabular-nums">{trust.score}</span> / 1.00
        </p>
      </div>
      <p className="mt-2 text-sm leading-6 text-muted">
        {trust.orders_delivered} orders delivered. Every number is signed with OpenStall&apos;s passport key, so an
        AI agent can check it has not been changed.
        {trust.data_source === "seeded_demo" ? " These are seeded demo numbers, not real sales." : null}
      </p>
      <dl className="mt-6 grid gap-5 sm:grid-cols-3">
        {rates.map(({ label, value, good }) => (
          <div key={label}>
            <div className="flex items-baseline justify-between">
              <dt className="text-sm font-medium">{label}</dt>
              <dd className="font-semibold tabular-nums">{percent(value)}</dd>
            </div>
            <div aria-hidden="true" className="mt-2 h-2 overflow-hidden rounded-full bg-border">
              <div
                className={`h-full rounded-full ${good ? "bg-success" : "bg-warning"}`}
                style={{ width: percent(Math.max(value, good ? 0 : 0.02)) }}
              />
            </div>
          </div>
        ))}
      </dl>
    </section>
  );
}

export function StallSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading the stall">
      <div className="h-10 w-48 animate-pulse rounded bg-border/80" />
      <div className="mt-3 h-5 w-72 animate-pulse rounded bg-border/60" />
      <div className="mt-10 grid gap-6 md:grid-cols-2 md:gap-10">
        <div className="aspect-square animate-pulse rounded-2xl bg-border/60" />
        <div className="space-y-3">
          <div className="h-7 w-3/4 animate-pulse rounded bg-border/80" />
          <div className="h-9 w-24 animate-pulse rounded bg-border/80" />
          <div className="h-20 animate-pulse rounded bg-border/60" />
        </div>
      </div>
    </div>
  );
}
