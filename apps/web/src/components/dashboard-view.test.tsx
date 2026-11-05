import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardView } from "@/components/dashboard-view";
import type { EventStreamState } from "@/hooks/use-event-stream";
import type { Dashboard, RadarGroup } from "@/lib/dashboard";

const stream: EventStreamState = { events: [], connected: true, error: null };
vi.mock("@/hooks/use-event-stream", async (original) => ({
  ...(await original<typeof import("@/hooks/use-event-stream")>()),
  useEventStream: () => stream,
}));

const MUGS: RadarGroup = {
  key: "ceramic-mug",
  label: "ceramic mugs",
  searches: 23,
  seeded: 23,
  queries: ["ceramic mugs", "handmade ceramic mug"],
  last_searched_at: "2026-11-06T09:00:00Z",
  maker: null,
  tip: "23 agents searched for ceramic mugs this week. Nobody sells them.",
  tipped_at: null,
};
const RUNNERS: RadarGroup = {
  key: "embroidered-runner-table",
  label: "embroidered table runner",
  searches: 9,
  seeded: 9,
  queries: ["embroidered table runner", "hand embroidered table runners"],
  last_searched_at: "2026-11-06T08:00:00Z",
  maker: {
    seller_id: "s_noor",
    name: "Noor",
    product_title: "Chain-stitch embroidered cushion cover",
    shared: ["embroidered"],
  },
  tip: "9 agents searched for embroidered table runner this week. Nobody sells them.",
  tipped_at: null,
};

function dashboard(radar: RadarGroup[] = [MUGS, RUNNERS]): Dashboard {
  return {
    simulated: true,
    orders: [
      {
        id: "ord_demo",
        status: "authorized",
        created_at: "2026-11-06T08:00:00Z",
        approved_at: "2026-11-06T08:05:00Z",
        total_usd: "815.00",
        paid_usd: "176.00",
        released_usd: "0.00",
        units: 40,
        makers: 4,
        top_up_of: null,
        requested_by_agent: true,
      },
    ],
    shares: [
      {
        part_id: "op_1",
        order_id: "ord_demo",
        reference_id: "op_002",
        seller_id: "s_priya",
        maker: "Priya",
        quantity: 11,
        amount_usd: "176.00",
        status: "captured",
        payout: "Paid to PayPal (simulated)",
        paid: true,
        carrier: "India Post",
        tracking_number: "EE123456789IN",
        tracking_on_paypal: true,
        ship_by: "2026-12-04",
        delivered_at: null,
        on_time: null,
        dropped_out: false,
      },
    ],
    passports: [
      {
        seller_id: "s_priya",
        name: "Priya",
        orders_delivered: 67,
        on_time_rate: 0.97,
        dispute_rate: 0.01,
        photo_originality: 0.93,
        score: 0.96,
        live_deliveries: 0,
        data_source: "seeded_demo",
        issued_at: "2026-11-01T00:00:00Z",
        signature_valid: true,
      },
    ],
    radar,
  };
}

function region(name: string) {
  return screen.getByRole("region", { name });
}

beforeEach(() => {
  stream.events = [];
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("DashboardView", () => {
  it("shows Radar's biggest tip on top, then each table", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(dashboard())));

    render(<DashboardView />);

    const tip = await screen.findByRole("region", { name: "Demand Radar tip" });
    expect(within(tip).getByText("23 agents searched for ceramic mugs this week. Nobody sells them.")).toBeInTheDocument();
    expect(within(tip).getByText("All these searches are seeded demo data.")).toBeInTheDocument();
    expect(await within(region("Orders")).findByRole("link", { name: "ord_demo" })).toHaveAttribute(
      "href",
      "/approve/ord_demo",
    );
    expect(within(region("Orders")).getByText("$815.00")).toBeInTheDocument();
    expect(within(region("Orders")).getByText("Drafted by an AI agent")).toBeInTheDocument();
    expect(within(region("Payouts")).getByText("Paid on proof of shipping")).toBeInTheDocument();
    expect(within(region("Tracking")).getByText("EE123456789IN")).toBeInTheDocument();
    expect(within(region("Trust passports")).getByRole("link", { name: "Priya" })).toHaveAttribute("href", "/stall/s_priya");
    expect(within(region("Trust passports")).getByText("Valid")).toBeInTheDocument();
    expect(screen.getByText("Test mode")).toBeInTheDocument();
  });

  it("sends a Radar group's tip to its maker, then shows it was sent", async () => {
    let tipped = false;
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST" && url.endsWith("/api/radar/embroidered-runner-table/tip")) {
        tipped = true;
        return Response.json({ ...RUNNERS, tipped_at: "2026-11-06T10:00:00Z" });
      }
      return Response.json(dashboard([MUGS, tipped ? { ...RUNNERS, tipped_at: "2026-11-06T10:00:00Z" } : RUNNERS]));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DashboardView />);

    const radar = await screen.findByRole("region", { name: "Demand Radar" });
    expect(within(radar).getByText("Nobody on OpenStall yet")).toBeInTheDocument();
    fireEvent.click(await within(radar).findByRole("button", { name: "Send the tip to Noor" }));

    await waitFor(() => expect(within(radar).getByText(/^Tipped /)).toBeInTheDocument());
    expect(within(radar).queryByRole("button", { name: "Send the tip to Noor" })).not.toBeInTheDocument();
  });

  it("asks for the demo token when sending a tip needs it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) =>
        init?.method === "POST"
          ? Response.json({ detail: "The demo controls need the X-Demo-Run-Token header." }, { status: 401 })
          : Response.json(dashboard()),
      ),
    );

    render(<DashboardView />);
    const radar = await screen.findByRole("region", { name: "Demand Radar" });
    fireEvent.click(await within(radar).findByRole("button", { name: "Send the tip to Noor" }));

    expect(await within(radar).findByRole("alert")).toHaveTextContent("The tip was not sent");
    expect(within(radar).getByLabelText("Demo token (sandbox mode)")).toBeInTheDocument();
  });

  it("says so when the dashboard cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: "down" }, { status: 503 })));

    render(<DashboardView />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The dashboard could not be loaded");
  });
});
