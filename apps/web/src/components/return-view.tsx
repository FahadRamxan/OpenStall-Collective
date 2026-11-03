"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

/** Where PayPal sends the human after they approve. Reserving the money here comes in the next build step. */
export function ReturnView() {
  const { orderId } = useParams<{ orderId: string }>();
  return (
    <div className="max-w-2xl">
      <p className="text-sm font-semibold text-accent">
        <span className="tracking-wide uppercase">Order</span> <span className="font-mono">{orderId}</span>
      </p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">You approved the order at PayPal</h1>
      <p className="mt-4 text-lg leading-8 text-muted">
        PayPal has your approval. OpenStall reserves the total next, and nothing is taken until each maker ships.
      </p>
      <Link
        href={`/approve/${encodeURIComponent(orderId)}`}
        className="mt-6 inline-block font-semibold text-accent underline underline-offset-4"
      >
        Back to the order
      </Link>
    </div>
  );
}
