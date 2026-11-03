import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OfferRules } from "@/components/offer-rules";
import type { EventStreamState } from "@/hooks/use-event-stream";
import type { FeedEvent } from "@/lib/events";
import type { Limits, MakerLimits } from "@/lib/limits";

const stream: EventStreamState = { events: [], connected: true, error: null };

vi.mock("@/hooks/use-event-stream", async (original) => ({
  ...(await original<typeof import("@/hooks/use-event-stream")>()),
  useEventStream: () => stream,
}));

function maker(overrides: Partial<MakerLimits>): MakerLimits {
  return {
    seller_id: "s_amina",
    seller_name: "Amina",
    city: "Lahore",
    product_id: "p_amina_cushion",
    product_title: "Hand-embroidered cushion cover",
    list_price_usd: "18.00",
    floor_price_usd: "15.00",
    max_discount_pct: "15",
    lowest_price_usd: "15.30",
    capacity_per_week: 4,
    ship_days: 9,
    min_lead_days: 5,
    committed_units: 0,
    capacity_by_deadline: 12,
    data_source: "seeded_demo",
    ...overrides,
  };
}

function limits(overrides: Partial<Limits> = {}): Limits {
  return {
    today: "2026-11-10",
    deadline: "2026-12-10",
    makers: [
      maker({}),
      maker({
        seller_id: "s_noor",
        seller_name: "Noor",
        city: "Manchester",
        product_id: "p_noor_cushion",
        list_price_usd: "31.00",
        floor_price_usd: "28.50",
        lowest_price_usd: "28.50",
        capacity_per_week: 3,
        ship_days: 5,
        capacity_by_deadline: 10,
      }),
    ],
    unreadable: [],
    ...overrides,
  };
}

function event(id: number, type: string): FeedEvent {
  return { id, type, entity_id: "op_1", summary: type, payload: {}, created_at: "2026-11-10T10:00:00Z" };
}

function mockLimits(...bodies: Limits[]) {
  const fetch = vi.fn();
  for (const body of bodies) fetch.mockResolvedValueOnce(Response.json(body));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

async function row(sellerName: string) {
  const table = await screen.findByRole("table");
  return within(table).getByRole("row", { name: new RegExp(`^${sellerName}`) });
}

beforeEach(() => {
  stream.events = [];
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("OfferRules", () => {
  it("lists each maker's lowest price and what she can make by the deadline", async () => {
    const fetch = mockLimits(limits());

    render(<OfferRules />);

    expect(screen.getByRole("heading", { name: "Offer rules" })).toBeInTheDocument();
    expect(screen.getByText(/the model only proposes a price/)).toBeInTheDocument();
    const amina = await row("Amina");
    expect(within(amina).getByRole("rowheader")).toHaveTextContent("Lahore · Hand-embroidered cushion cover");
    const [lowest, capacity] = within(amina).getAllByRole("cell");
    expect(lowest).toHaveTextContent("$15.30");
    expect(lowest).toHaveTextContent("List $18.00 · floor $15.00 · up to 15% off");
    expect(capacity).toHaveTextContent("12 units");
    expect(capacity).toHaveTextContent("4 a week · ships in 9 days");
    expect(within(await row("Noor")).getAllByRole("cell")[0]).toHaveTextContent("$28.50");
    expect(screen.getByRole("table")).toHaveAccessibleName(
      "Each maker's limits for an order due December 10, 2026, 30 days from today.",
    );
    expect(screen.getByRole("columnheader", { name: "Can make by Dec 10" })).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/demo/limits", expect.anything());
  });

  it("marks seeded makers as demo data, and live makers not", async () => {
    mockLimits(limits({ makers: [maker({}), maker({ seller_id: "s_zara", seller_name: "Zara", data_source: "live" })] }));

    render(<OfferRules />);

    expect(within(await row("Amina")).getByText("Seeded demo")).toBeInTheDocument();
    expect(within(await row("Zara")).queryByText("Seeded demo")).not.toBeInTheDocument();
  });

  it("says how many units a maker has already promised to reserved orders", async () => {
    mockLimits(limits({ makers: [maker({ committed_units: 12, capacity_by_deadline: 0 })] }));

    render(<OfferRules />);

    const [, capacity] = within(await row("Amina")).getAllByRole("cell");
    expect(capacity).toHaveTextContent("0 units");
    expect(capacity).toHaveTextContent("4 a week · ships in 9 days · 12 already promised");
  });

  it("loads again when a share is reserved, paid or released, and not for other events", async () => {
    const fetch = mockLimits(
      limits(),
      limits({ makers: [maker({ committed_units: 12, capacity_by_deadline: 0 })] }),
    );
    const view = render(<OfferRules />);
    await row("Amina");
    expect(fetch).toHaveBeenCalledTimes(1);

    stream.events = [event(7, "search.logged")];
    view.rerender(<OfferRules />);
    expect(fetch).toHaveBeenCalledTimes(1);

    stream.events = [event(8, "part.reserved"), ...stream.events];
    view.rerender(<OfferRules />);

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await waitFor(async () => expect(within(await row("Amina")).getAllByRole("cell")[1]).toHaveTextContent("0 units"));
  });

  it("names the makers whose limits cannot be checked", async () => {
    mockLimits(
      limits({ unreadable: ["Noor's limits cannot be checked: seller s_noor's policy is missing floor_price_usd."] }),
    );

    render(<OfferRules />);

    const list = await screen.findByRole("list", { name: "Makers whose limits cannot be checked" });
    expect(list).toHaveTextContent("Noor's limits cannot be checked: seller s_noor's policy is missing floor_price_usd.");
  });

  it("says so when no maker has a live listing", async () => {
    mockLimits(limits({ makers: [] }));

    render(<OfferRules />);

    expect(await screen.findByText(/No maker has a live listing yet/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("shows loading, then the error in words when the limits cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(<OfferRules />);

    expect(screen.getByText("Loading the makers' limits…")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("The makers' limits could not be loaded");
    expect(screen.queryByText("Loading the makers' limits…")).not.toBeInTheDocument();
  });
});
