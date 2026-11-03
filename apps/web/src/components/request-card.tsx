"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/badge";
import { useEventStream } from "@/hooks/use-event-stream";
import { errorMessage } from "@/lib/api";
import { changesQuote, getLatestQuote, progressWords, termWords, type Quote } from "@/lib/quotes";

/**
 * The /demo page's "Request" card: what the buyer agent asked for (the items, quantity, maximum price, deadline and
 * city) and how far the negotiation has got. It loads the latest quote again whenever a round or a quote ends.
 */
export function RequestCard() {
  const { events } = useEventStream();
  // Events are newest first: the newest event about a quote.
  const lastChange = events.find(changesQuote)?.id ?? 0;
  const [quote, setQuote] = useState<Quote | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getLatestQuote({ signal: controller.signal })
      .then((latest) => {
        setQuote(latest);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(reason));
      });
    return () => controller.abort();
  }, [lastChange]);

  return (
    <section aria-labelledby="request-heading" className="mt-10">
      <h2 id="request-heading" className="text-xl font-semibold tracking-tight">
        Request
      </h2>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-danger">
          The latest request could not be loaded: {error}
        </p>
      ) : null}
      {quote ? (
        <div className="mt-4 rounded-xl border border-border bg-surface p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <p className="text-lg leading-7 font-semibold text-balance">
              {quote.queries.map((query) => `“${query}”`).join(", ")}
            </p>
            <Badge tone={quote.completed_at ? "success" : "accent"}>
              {quote.completed_at ? "Offers in" : "Negotiating"}
            </Badge>
          </div>
          <ul aria-label="What the buyer asked for" className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-muted">
            {termWords(quote).map((term) => (
              <li key={term}>{term}</li>
            ))}
          </ul>
          <p role="status" className="mt-4 border-t border-border pt-4 leading-7">
            {progressWords(quote)}
          </p>
        </div>
      ) : quote === null ? (
        <p className="mt-4 rounded-xl border border-dashed border-border p-6 leading-7 text-muted">
          No buyer agent has asked for a quote yet. When one does, its request appears here, and each matching
          maker&apos;s agent is asked for an offer.
        </p>
      ) : error ? null : (
        <p aria-busy="true" className="mt-4 text-muted">
          Loading the latest request…
        </p>
      )}
    </section>
  );
}
