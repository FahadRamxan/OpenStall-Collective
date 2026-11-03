import { describe, expect, it } from "vitest";

import type { FeedEvent } from "@/lib/events";
import { arrivalWords, filterWords, resultWords, searchFromEvent, type SearchFilters } from "@/lib/searches";

function searchEvent(overrides: Partial<FeedEvent>): FeedEvent {
  return {
    id: 7,
    type: "search.logged",
    entity_id: "sr_1",
    summary: 'An agent searched for "ceramic mugs": no results.',
    payload: { query: "ceramic mugs", filters: { ship_to: "Chicago" }, result_count: 0 },
    created_at: "2026-11-10T10:00:00Z",
    ...overrides,
  };
}

describe("filterWords", () => {
  it("says each filter the agent gave, in the order a buyer would", () => {
    expect(filterWords({ ship_to: "Chicago", deadline: "2026-12-10", quantity: 1200, max_price: "29.5" })).toEqual([
      "At most $29.50 each",
      "1,200 units",
      "By December 10, 2026",
      "To Chicago",
    ]);
    expect(filterWords({ quantity: 1 })).toEqual(["1 unit"]);
    expect(filterWords({})).toEqual([]);
  });

  it("skips a filter of the wrong kind or an empty city", () => {
    const odd = { max_price: 30, quantity: "40", ship_to: "" } as unknown as SearchFilters;

    expect(filterWords(odd)).toEqual([]);
  });
});

describe("resultWords", () => {
  it("says the count in words", () => {
    expect([0, 1, 2, 1500].map(resultWords)).toEqual(["No results", "1 result", "2 results", "1,500 results"]);
  });
});

describe("arrivalWords", () => {
  it("says a new search in one sentence, for screen readers", () => {
    const search = { id: "sr_1", query: "ceramic mugs", filters: {}, result_count: 0, created_at: "2026-11-10T10:00Z" };

    expect(arrivalWords(search)).toBe("New search for “ceramic mugs”: no results.");
    expect(arrivalWords({ ...search, query: "linen", result_count: 3 })).toBe("New search for “linen”: 3 results.");
  });
});

describe("searchFromEvent", () => {
  it("reads a search from its search.logged event", () => {
    expect(searchFromEvent(searchEvent({}))).toEqual({
      id: "sr_1",
      query: "ceramic mugs",
      filters: { ship_to: "Chicago" },
      result_count: 0,
      created_at: "2026-11-10T10:00:00Z",
    });
  });

  it("gives null for other events and for search events missing their details", () => {
    expect(searchFromEvent(searchEvent({ type: "order.drafted" }))).toBeNull();
    expect(searchFromEvent(searchEvent({ entity_id: null }))).toBeNull();
    expect(searchFromEvent(searchEvent({ payload: { query: "mugs" } }))).toBeNull();
    expect(searchFromEvent(searchEvent({ payload: { result_count: 0 } }))).toBeNull();
    expect(searchFromEvent(searchEvent({ payload: { query: "mugs", result_count: 2, filters: null } }))?.filters).toEqual(
      {},
    );
  });
});
