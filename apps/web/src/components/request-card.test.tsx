import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RequestCard } from "@/components/request-card";
import type { EventStreamState } from "@/hooks/use-event-stream";
import type { FeedEvent } from "@/lib/events";
import { progressWords, termWords, type Quote } from "@/lib/quotes";

const stream: EventStreamState = { events: [], connected: true, error: null };

vi.mock("@/hooks/use-event-stream", async (original) => ({
  ...(await original<typeof import("@/hooks/use-event-stream")>()),
  useEventStream: () => stream,
}));

function quote(overrides: Partial<Quote> = {}): Quote {
  return {
    id: "q_story",
    queries: ["40 hand-embroidered cushion covers for corporate gifts"],
    quantity: 40,
    max_unit_price: "30.00",
    deadline: "2026-12-10",
    ship_to: "Chicago",
    created_at: "2026-11-10T10:00:00Z",
    rounds: 1,
    completed_at: "2026-11-10T10:00:02Z",
    asked: 5,
    valid_offers: 5,
    total_capacity: 54,
    ...overrides,
  };
}

function event(id: number, type: string): FeedEvent {
  return { id, type, entity_id: "q_story", summary: type, payload: {}, created_at: "2026-11-10T10:00:00Z" };
}

function mockQuotes(...bodies: Quote[][]) {
  const fetch = vi.fn();
  for (const body of bodies) fetch.mockResolvedValueOnce(Response.json(body));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

beforeEach(() => {
  stream.events = [];
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("RequestCard", () => {
  it("shows what the buyer asked for and how the negotiation went", async () => {
    const fetch = mockQuotes([quote()]);

    render(<RequestCard />);

    expect(screen.getByRole("heading", { name: "Request" })).toBeInTheDocument();
    expect(await screen.findByText("“40 hand-embroidered cushion covers for corporate gifts”")).toBeInTheDocument();
    const terms = screen.getByRole("list", { name: "What the buyer asked for" });
    expect(within(terms).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "40 units",
      "At most $30.00 each",
      "By December 10, 2026",
      "To Chicago",
    ]);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Done after 1 round: 5 valid offers from 5 makers, for 54 units against 40 asked for.",
    );
    expect(screen.getByText("Offers in")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/quotes?limit=1", expect.anything());
  });

  it("loads the latest quote again when a round or a quote ends, and not for other events", async () => {
    const fetch = mockQuotes([quote({ rounds: 0, completed_at: null })], [quote()]);
    const view = render(<RequestCard />);
    expect(await screen.findByText("Negotiating")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Asking 5 makers' agents for offers: round 1 of 3.");

    stream.events = [event(4, "offer.accepted")];
    view.rerender(<RequestCard />);
    expect(fetch).toHaveBeenCalledTimes(1);

    stream.events = [event(5, "quote.completed"), ...stream.events];
    view.rerender(<RequestCard />);

    await waitFor(() => expect(screen.getByText("Offers in")).toBeInTheDocument());
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("says when no buyer agent has asked yet, and when the request cannot be loaded", async () => {
    mockQuotes([]);
    const view = render(<RequestCard />);
    expect(await screen.findByText(/No buyer agent has asked for a quote yet/)).toBeInTheDocument();
    view.unmount();

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    render(<RequestCard />);
    expect(screen.getByText("Loading the latest request…")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("The latest request could not be loaded");
  });
});

describe("quote words", () => {
  it("says each term of the request", () => {
    expect(termWords(quote({ quantity: 1 }))[0]).toBe("1 unit");
    expect(termWords(quote({ quantity: 1200 }))[0]).toBe("1,200 units");
  });

  it("says where the negotiation stands", () => {
    expect(progressWords(quote({ rounds: 1, completed_at: null }))).toBe(
      "Round 2 of 3: asking again those without a valid offer.",
    );
    expect(progressWords(quote({ rounds: 3, valid_offers: 3, total_capacity: 31 }))).toBe(
      "Done after 3 rounds: 3 valid offers from 5 makers, for 31 units against 40 asked for, 9 short.",
    );
    expect(progressWords(quote({ asked: 0, valid_offers: 0, total_capacity: 0 }))).toBe(
      "No maker's listing matches this request, so no agent was asked.",
    );
    expect(progressWords(quote({ asked: 1, valid_offers: 1, total_capacity: 12 }))).toBe(
      "Done after 1 round: 1 valid offer from 1 maker, for 12 units against 40 asked for, 28 short.",
    );
  });
});
