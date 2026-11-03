import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AgentSearches, RECENT_SEARCHES } from "@/components/agent-searches";
import { MAX_EVENTS, type EventStreamState } from "@/hooks/use-event-stream";
import type { FeedEvent } from "@/lib/events";
import type { AgentSearch } from "@/lib/searches";

const stream: EventStreamState = { events: [], connected: true, error: null };

vi.mock("@/hooks/use-event-stream", async (original) => ({
  ...(await original<typeof import("@/hooks/use-event-stream")>()),
  useEventStream: () => stream,
}));

function search(overrides: Partial<AgentSearch>): AgentSearch {
  return {
    id: "sr_1",
    query: "cushion covers",
    filters: {},
    result_count: 5,
    created_at: "2026-11-10T10:00:00Z",
    ...overrides,
  };
}

/** The search.logged event the API records with a search. */
function logged(id: number, found: AgentSearch): FeedEvent {
  return {
    id,
    type: "search.logged",
    entity_id: found.id,
    summary: `An agent searched for "${found.query}"`,
    payload: { query: found.query, filters: found.filters, result_count: found.result_count },
    created_at: found.created_at,
  };
}

function mockRecent(searches: AgentSearch[]) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(searches)));
}

async function rows() {
  return within(await screen.findByRole("list", { name: "Agent searches, newest first" })).getAllByRole("listitem");
}

beforeEach(() => {
  stream.events = [];
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("AgentSearches", () => {
  it("lists the recent searches newest first, with each query, its filters in words and its result count", async () => {
    mockRecent([
      search({
        id: "sr_2",
        query: "embroidered cushion covers",
        filters: { max_price: "30.00", quantity: 40, deadline: "2026-12-10", ship_to: "Chicago" },
        result_count: 3,
        created_at: "2026-11-10T10:05:00Z",
      }),
      search({ id: "sr_1", query: "linen", result_count: 1 }),
    ]);

    render(<AgentSearches />);

    expect(screen.getByRole("heading", { name: "Agent searches" })).toBeInTheDocument();
    const [newest, older] = await rows();
    expect(newest).toHaveTextContent("“embroidered cushion covers”");
    expect(newest).toHaveTextContent("At most $30.00 each · 40 units · By December 10, 2026 · To Chicago");
    expect(newest).toHaveTextContent("3 results");
    expect(newest.querySelector("time")).toHaveAttribute("datetime", "2026-11-10T10:05:00Z");
    expect(older).toHaveTextContent("“linen”");
    expect(older).toHaveTextContent("No filters");
    expect(older).toHaveTextContent("1 result");
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/searches?limit=20", expect.anything());
  });

  it("shows a search that found nothing in amber, and says No results in words", async () => {
    mockRecent([
      search({ id: "sr_2", query: "ceramic mugs", result_count: 0, created_at: "2026-11-10T10:05:00Z" }),
      search({ id: "sr_1" }),
    ]);

    render(<AgentSearches />);

    const [mugs, covers] = await rows();
    expect(mugs).toHaveTextContent("“ceramic mugs”");
    expect(within(mugs).getByText("No results")).toBeInTheDocument();
    expect(mugs).toHaveClass("bg-warning-soft");
    expect(mugs).toHaveAttribute("data-results", "none");
    // On the amber row the badge is outlined on the surface colour, so its pill still shows.
    expect(within(mugs).getByText("No results")).toHaveClass("bg-surface", "ring-1", "text-warning");
    expect(covers).not.toHaveClass("bg-warning-soft");
    expect(within(covers).queryByText("No results")).not.toBeInTheDocument();
    expect(within(covers).getByText("5 results")).toHaveClass("bg-border");
  });

  it("adds a new search from the event stream at the top, and shows a search it already loaded once", async () => {
    const loaded = search({ id: "sr_1", query: "linen" });
    mockRecent([loaded]);
    const { rerender } = render(<AgentSearches />);
    expect(await rows()).toHaveLength(1);

    const fresh = search({ id: "sr_2", query: "ceramic mugs", result_count: 0, created_at: "2026-11-10T10:07:00Z" });
    stream.events = [logged(9, fresh), logged(8, loaded)];
    rerender(<AgentSearches />);

    const [first, second, ...others] = await rows();
    expect(first).toHaveTextContent("“ceramic mugs”");
    expect(first).toHaveTextContent("No results");
    expect(second).toHaveTextContent("“linen”");
    expect(others).toHaveLength(0);
  });

  it("ignores other events, and search events without their details", async () => {
    mockRecent([search({ id: "sr_1", query: "linen" })]);
    const broken = logged(4, search({ id: "sr_9" }));
    stream.events = [
      { ...logged(7, search({ id: "sr_7" })), type: "demo.test" },
      { ...broken, entity_id: null },
      { ...broken, id: 5, payload: { filters: {}, result_count: 2 } },
      { ...broken, id: 6, payload: { query: "socks" } },
    ];

    render(<AgentSearches />);

    const [only, ...others] = await rows();
    expect(only).toHaveTextContent("“linen”");
    expect(others).toHaveLength(0);
  });

  it(`shows only the newest ${RECENT_SEARCHES} searches`, async () => {
    const at = (minute: number) => `2026-11-10T10:${String(minute).padStart(2, "0")}:00Z`;
    mockRecent(Array.from({ length: 15 }, (_, n) => search({ id: `sr_old_${n}`, query: `old ${n}`, created_at: at(n) })));
    stream.events = Array.from({ length: 10 }, (_, n) =>
      logged(n + 1, search({ id: `sr_new_${n}`, query: `new ${n}`, created_at: at(30 + n) })),
    );

    render(<AgentSearches />);

    const shown = await rows();
    expect(shown).toHaveLength(RECENT_SEARCHES);
    expect(shown[0]).toHaveTextContent("“new 9”");
    expect(shown.at(-1)).toHaveTextContent("“old 5”");
  });

  it("says when no agent has searched yet", async () => {
    mockRecent([]);

    render(<AgentSearches />);

    expect(await screen.findByText(/No agent has searched yet/)).toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("says it is loading until the recent searches arrive", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    render(<AgentSearches />);

    expect(screen.getByText("Loading searches…")).toHaveAttribute("aria-busy", "true");
  });

  it("says when earlier searches could not be loaded, and still shows new ones", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    stream.events = [logged(3, search({ id: "sr_3", query: "ceramic mugs", result_count: 0 }))];

    render(<AgentSearches />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Earlier searches could not be loaded: Could not reach the OpenStall API at http://api.test.",
    );
    const [only] = await rows();
    expect(only).toHaveTextContent("“ceramic mugs”");
  });

  it("does not claim no agent has searched when it could not load the searches", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(<AgentSearches />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Earlier searches could not be loaded");
    expect(screen.queryByText(/No agent has searched yet/)).not.toBeInTheDocument();
    expect(screen.queryByText("Loading searches…")).not.toBeInTheDocument();
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
  });

  it("keeps a search that streamed in after 200 newer events of other kinds", async () => {
    mockRecent([search({ id: "sr_1", query: "linen", created_at: "2026-11-10T09:00:00Z" })]);
    const { rerender } = render(<AgentSearches />);
    expect(await rows()).toHaveLength(1);
    const fresh = search({ id: "sr_2", query: "ceramic mugs", result_count: 0, created_at: "2026-11-10T10:07:00Z" });
    stream.events = [logged(1, fresh)];
    rerender(<AgentSearches />);
    expect(await rows()).toHaveLength(2);

    // The stream keeps only its latest MAX_EVENTS events: the search's own event drops off the end.
    stream.events = Array.from({ length: MAX_EVENTS }, (_, n) => ({
      ...logged(MAX_EVENTS + 1 - n, fresh),
      type: "message.received",
      entity_id: null,
    }));
    rerender(<AgentSearches />);

    const [first, second] = await rows();
    expect(first).toHaveTextContent("“ceramic mugs”");
    expect(second).toHaveTextContent("“linen”");
  });

  it("tells screen readers about each new search, but not the ones it loads when it opens", async () => {
    mockRecent([search({ id: "sr_1", query: "linen", result_count: 1 })]);
    const { rerender } = render(<AgentSearches />);
    expect(await rows()).toHaveLength(1);
    const announcement = screen.getByRole("status");
    expect(announcement).toBeEmptyDOMElement();

    const fresh = search({ id: "sr_2", query: "ceramic mugs", result_count: 0, created_at: "2026-11-10T10:07:00Z" });
    stream.events = [logged(5, fresh)];
    rerender(<AgentSearches />);

    expect(await screen.findByRole("status")).toHaveTextContent("New search for “ceramic mugs”: no results.");
    expect(screen.getByRole("status")).toBe(announcement); // the same live region, there from the start
    expect(announcement).toHaveClass("sr-only");
  });
});
