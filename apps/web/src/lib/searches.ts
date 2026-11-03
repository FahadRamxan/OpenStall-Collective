import { apiGet } from "@/lib/api";
import { formatUsd } from "@/lib/catalog";
import type { FeedEvent } from "@/lib/events";
import { formatDay } from "@/lib/orders";

/** The filters a buyer agent gave search_products. Only the ones it gave are there. */
export type SearchFilters = {
  /** Highest unit price in USD, in whole cents, as a string such as "30.00". */
  max_price?: string;
  quantity?: number;
  /** The date the goods must arrive by, YYYY-MM-DD. */
  deadline?: string;
  ship_to?: string;
};

/** One search_products call, as GET /api/searches and the search.logged event describe it. */
export type AgentSearch = {
  id: string;
  query: string;
  filters: SearchFilters;
  result_count: number;
  created_at: string;
};

/** The most recent searches, newest first. */
export function getRecentSearches(limit = 20, init: RequestInit = {}): Promise<AgentSearch[]> {
  return apiGet<AgentSearch[]>(`/api/searches?limit=${limit}`, init);
}

/** The search a search.logged event describes, or null for any other event (or one missing its details). */
export function searchFromEvent(event: FeedEvent): AgentSearch | null {
  if (event.type !== "search.logged" || !event.entity_id) return null;
  const { query, filters, result_count: resultCount } = event.payload;
  if (typeof query !== "string" || typeof resultCount !== "number") return null;
  return {
    id: event.entity_id,
    query,
    filters: filters !== null && typeof filters === "object" ? (filters as SearchFilters) : {},
    result_count: resultCount,
    created_at: event.created_at,
  };
}

/** Each filter in words: "At most $30.00 each", "40 units", "By December 10, 2026", "To Chicago". */
export function filterWords(filters: SearchFilters): string[] {
  const words: string[] = [];
  if (typeof filters.max_price === "string") words.push(`At most ${formatUsd(filters.max_price)} each`);
  if (typeof filters.quantity === "number") {
    words.push(filters.quantity === 1 ? "1 unit" : `${filters.quantity.toLocaleString("en-US")} units`);
  }
  if (typeof filters.deadline === "string") words.push(`By ${formatDay(filters.deadline)}`);
  if (typeof filters.ship_to === "string" && filters.ship_to) words.push(`To ${filters.ship_to}`);
  return words;
}

/** "No results", "1 result", "12 results". */
export function resultWords(count: number): string {
  if (count === 0) return "No results";
  return count === 1 ? "1 result" : `${count.toLocaleString("en-US")} results`;
}

/** What a screen reader says when a search arrives: "New search for “ceramic mugs”: no results." */
export function arrivalWords(search: AgentSearch): string {
  const found = resultWords(search.result_count);
  return `New search for “${search.query}”: ${found.charAt(0).toLowerCase()}${found.slice(1)}.`;
}
