"use client";

import { Badge } from "@/components/badge";
import { useLiveList, type LiveListSource } from "@/hooks/use-live-list";
import { clockTime } from "@/lib/events";
import {
  arrivalWords,
  filterWords,
  getRecentSearches,
  resultWords,
  searchFromEvent,
  type AgentSearch,
} from "@/lib/searches";

/** The most searches the panel shows. */
export const RECENT_SEARCHES = 20;

const SEARCHES: LiveListSource<AgentSearch> = {
  load: (init) => getRecentSearches(RECENT_SEARCHES, init),
  fromEvent: searchFromEvent,
  key: (search) => search.id,
  time: (search) => search.created_at,
  limit: RECENT_SEARCHES,
};

/**
 * The /demo page's "Agent searches" panel: what buyer agents asked the MCP storefront for, newest first, as it
 * happens. A search that found nothing is amber and says so: demand that no maker meets yet.
 */
export function AgentSearches() {
  const { rows, loading, error, arrived } = useLiveList(SEARCHES);
  return (
    <section aria-labelledby="searches-heading" className="mt-10">
      <h2 id="searches-heading" className="text-xl font-semibold tracking-tight">
        Agent searches
      </h2>
      <p className="mt-1 leading-7 text-muted">
        What buyer agents look for in the storefront. A search that finds nothing shows in amber: something buyers
        want that no maker offers yet.
      </p>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-danger">
          Earlier searches could not be loaded: {error}
        </p>
      ) : null}
      {rows.length > 0 ? (
        <ol
          aria-label="Agent searches, newest first"
          className="mt-4 divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface"
        >
          {rows.map((search) => (
            <SearchRow key={search.id} search={search} />
          ))}
        </ol>
      ) : loading ? (
        <p aria-busy="true" className="mt-4 text-muted">
          Loading searches…
        </p>
      ) : error ? null : (
        // Only when the load answered: after a failed load nobody knows whether an agent has searched.
        <p className="mt-4 rounded-xl border border-dashed border-border p-6 leading-7 text-muted">
          No agent has searched yet. Each search an agent makes through the MCP storefront appears here as it happens.
        </p>
      )}
      {/* Always in the page, so screen readers hear each new search. The ones loaded at first are not read out. */}
      <div role="status" className="sr-only">
        {arrived ? <span key={arrived.id}>{arrivalWords(arrived)}</span> : null}
      </div>
    </section>
  );
}

/** On a phone the time and the result count share the first line and the search gets the full width under them. */
function SearchRow({ search }: { search: AgentSearch }) {
  const nothingFound = search.result_count === 0;
  const filters = filterWords(search.filters);
  return (
    <li
      data-results={nothingFound ? "none" : "some"}
      className={`grid grid-cols-[auto_1fr] items-start gap-x-3 gap-y-1 px-4 py-3 sm:grid-cols-[auto_1fr_auto] sm:gap-x-4 sm:px-5 ${
        nothingFound ? "bg-warning-soft" : ""
      }`}
    >
      <time dateTime={search.created_at} className="pt-0.5 font-mono text-xs text-muted tabular-nums">
        {clockTime(search.created_at)}
      </time>
      <div className="col-span-2 row-start-2 min-w-0 sm:col-span-1 sm:col-start-2 sm:row-start-1">
        <p className="leading-6 font-medium break-words">“{search.query}”</p>
        <p className="text-sm leading-6 break-words text-muted">
          {filters.length > 0 ? filters.join(" · ") : "No filters"}
        </p>
      </div>
      <div className="col-start-2 row-start-1 justify-self-end sm:col-start-3">
        {/* On the amber row an amber-filled badge would vanish into it: outlined, it keeps its shape. */}
        <Badge tone={nothingFound ? "warning" : "neutral"} outline={nothingFound}>
          {resultWords(search.result_count)}
        </Badge>
      </div>
    </li>
  );
}
