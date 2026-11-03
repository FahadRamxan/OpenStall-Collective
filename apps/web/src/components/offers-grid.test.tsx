import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OffersGrid } from "@/components/offers-grid";
import type { EventStreamState } from "@/hooks/use-event-stream";
import type { FeedEvent } from "@/lib/events";
import { arrivalWords, offerFromEvent, roundWords, type AgentOffer } from "@/lib/offers";

const stream: EventStreamState = { events: [], connected: true, error: null };

vi.mock("@/hooks/use-event-stream", async (original) => ({
  ...(await original<typeof import("@/hooks/use-event-stream")>()),
  useEventStream: () => stream,
}));

function offer(overrides: Partial<AgentOffer>): AgentOffer {
  return {
    id: "off_1",
    request_id: "q_story",
    seller_id: "s_grace",
    seller_name: "Grace",
    product_id: "p_grace_cushion",
    round: 1,
    attempt: 1,
    unit_price: "32.00",
    quantity: 11,
    delivery_date: "2026-12-10",
    message: "Grace can make 11 by December 10 at $32.00 each.",
    is_valid: false,
    rejection_reason: "over_buyer_cap",
    why: "over the buyer's maximum of $30.00",
    created_at: "2026-11-10T10:00:00Z",
    ...overrides,
  };
}

const REFUSED = offer({});
const VALID = offer({
  id: "off_2",
  attempt: 2,
  unit_price: "29.00",
  message: "Grace can make 11 by December 10 at $29.00 each.",
  is_valid: true,
  rejection_reason: null,
  why: "valid",
  created_at: "2026-11-10T10:00:01Z",
});

function checked(id: number, found: AgentOffer): FeedEvent {
  return {
    id,
    type: found.is_valid ? "offer.accepted" : "offer.rejected",
    entity_id: found.id,
    summary: "Code checked an offer",
    payload: { summary: "Code checked an offer", ...found },
    created_at: found.created_at,
  };
}

function mockRecent(offers: AgentOffer[]) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(offers)));
}

/** The grid's body rows, by the seller and price they show. */
async function gridRows() {
  const grid = await screen.findByRole("grid");
  await waitFor(() => expect(within(grid).getAllByRole("row").length).toBeGreaterThan(1));
  return within(grid)
    .getAllByRole("row")
    .filter((row) => row.getAttribute("row-id"))
    .map((row) => row.textContent ?? "");
}

beforeEach(() => {
  stream.events = [];
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("OffersGrid", () => {
  it("shows each proposal with its round, price, quantity, delivery, the code's verdict and the agent's message", async () => {
    mockRecent([VALID, REFUSED]);

    render(<OffersGrid />);

    expect(screen.getByRole("heading", { name: "Offers" })).toBeInTheDocument();
    const rows = await gridRows();
    expect(rows).toHaveLength(2);
    const valid = rows.find((row) => row.includes("$29.00"));
    const refused = rows.find((row) => row.includes("$32.00"));
    expect(valid).toContain("Round 1, try 2");
    expect(valid).toContain("Valid");
    expect(valid).toContain("Dec 10");
    expect(valid).toContain("Grace can make 11 by December 10 at $29.00 each.");
    expect(refused).toContain("Refused");
    expect(refused).toContain("over the buyer's maximum of $30.00");
  });

  it("adds an offer live when the code checks it, and announces the verdict", async () => {
    mockRecent([REFUSED]);
    const view = render(<OffersGrid />);
    expect(await gridRows()).toHaveLength(1);

    stream.events = [checked(9, VALID)];
    view.rerender(<OffersGrid />);

    await waitFor(async () => expect(await gridRows()).toHaveLength(2));
    expect(screen.getByRole("status")).toHaveTextContent("Grace offered $29.00 each: valid.");
  });

  it("shows only the latest request's offers", async () => {
    mockRecent([offer({ id: "off_new", request_id: "q_new", created_at: "2026-11-10T11:00:00Z" }), REFUSED]);

    render(<OffersGrid />);

    expect(await gridRows()).toHaveLength(1);
  });

  it("says when no agent has made an offer yet, and when the earlier ones cannot be loaded", async () => {
    mockRecent([]);
    const view = render(<OffersGrid />);
    expect(await screen.findByText(/No seller agent has made an offer yet/)).toBeInTheDocument();
    view.unmount();

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    render(<OffersGrid />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Earlier offers could not be loaded");
  });
});

describe("offer helpers", () => {
  it("reads offers only from checked-offer events that carry a row", () => {
    expect(offerFromEvent(checked(1, VALID))).toMatchObject({ id: "off_2", unit_price: "29.00" });
    expect(offerFromEvent({ ...checked(2, REFUSED), type: "offer.proposed" })).toBeNull();
    // A try with no usable price is in the feed but has no row.
    expect(
      offerFromEvent({ ...checked(3, REFUSED), entity_id: null, payload: { summary: "No usable price", attempt: 1 } }),
    ).toBeNull();
  });

  it("says the round, and the try when it is a retry", () => {
    expect(roundWords(REFUSED)).toBe("Round 1");
    expect(roundWords(VALID)).toBe("Round 1, try 2");
    expect(arrivalWords(REFUSED)).toBe("Grace offered $32.00 each: refused, over the buyer's maximum of $30.00.");
  });
});
