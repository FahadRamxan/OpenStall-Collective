import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StallView } from "@/components/stall-view";
import type { SellerDetail } from "@/lib/catalog";

// The buy box talks to PayPal; it has its own tests.
vi.mock("@/components/stall-buy", () => ({ StallBuy: () => null }));

const params = { id: "s_noor" };
vi.mock("next/navigation", () => ({ useParams: () => params }));

const NOOR: SellerDetail = {
  id: "s_noor",
  name: "Noor",
  city: "Manchester",
  country: "GB",
  language: "ur",
  data_source: "seeded_demo",
  products: [
    {
      id: "p_noor_cushion",
      seller_id: "s_noor",
      title: "Chain-stitch embroidered cushion cover",
      description: "Cotton cover, 16 by 16 inches, with paisleys in fine chain stitch.",
      category: "home textiles",
      variants: ["rose", "forest"],
      price_usd: "31.00",
      capacity_per_week: 3,
      ship_days: 5,
      ship_from_city: "Manchester",
      photos: ["/media/seed/noor-cushion-1.svg", "/media/seed/noor-cushion-2.svg"],
      data_source: "seeded_demo",
    },
  ],
  trust: {
    orders_delivered: 25,
    on_time_rate: 0.96,
    dispute_rate: 0,
    photo_originality: 0.94,
    score: "0.97",
    data_source: "seeded_demo",
    issued_at: "2026-11-01T00:00:00Z",
  },
};

beforeEach(() => {
  params.id = "s_noor";
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("StallView", () => {
  it("shows the maker, where she is, the language she speaks, and that she is seeded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(NOOR)));

    render(<StallView />);

    expect(await screen.findByRole("heading", { level: 1, name: "Noor" })).toBeInTheDocument();
    expect(screen.getByText("Manchester, United Kingdom · Speaks Urdu")).toBeInTheDocument();
    expect(screen.getByText("Seeded demo seller")).toBeInTheDocument();
    await waitFor(() => expect(document.title).toBe("Noor's stall · OpenStall Collective"));
  });

  it("shows each listing with its price, colours and facts", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(NOOR)));

    render(<StallView />);

    const listing = await screen.findByRole("article", { name: "Chain-stitch embroidered cushion cover" });
    expect(listing).toHaveTextContent("$31.00");
    expect(within(listing).getByRole("list", { name: "Colours" })).toHaveTextContent("roseforest");
    expect(within(listing).getByText("3 a week")).toBeInTheDocument();
    expect(within(listing).getByText("5 days")).toBeInTheDocument();
    expect(within(listing).getByText("Home textiles")).toBeInTheDocument();
    // Sentence case, not every word capitalised.
    expect(within(listing).getByText("3 a week")).not.toHaveClass("capitalize");
    expect(within(listing).getByRole("img", { name: /photo 1/ })).toHaveAttribute(
      "src",
      "http://api.test/media/seed/noor-cushion-1.svg",
    );
  });

  it("switches to another photo", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(NOOR)));
    render(<StallView />);

    fireEvent.click(await screen.findByRole("button", { name: "Show photo 2" }));

    expect(screen.getByRole("img", { name: /photo 2/ })).toHaveAttribute(
      "src",
      "http://api.test/media/seed/noor-cushion-2.svg",
    );
    expect(screen.getByRole("button", { name: "Show photo 2" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows the trust record and says the numbers are seeded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(NOOR)));

    render(<StallView />);

    const trust = await screen.findByRole("region", { name: "Noor's trust record" });
    expect(trust).toHaveTextContent("0.97");
    expect(trust).toHaveTextContent("25 orders delivered");
    expect(trust).toHaveTextContent("96%");
    expect(trust).toHaveTextContent("These are seeded demo numbers, not real sales.");
    // OpenStall signs it, and agents can check it (prompt 35).
    expect(trust).toHaveTextContent("signed by OpenStall so an agent can check that nothing was changed.");
  });

  it("says how many of her orders came through OpenStall once her record is signed again", async () => {
    const updated = {
      ...NOOR,
      trust: { ...NOOR.trust, orders_delivered: 26, live_deliveries: 1, issued_at: "2026-12-01T15:00:00Z" },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(updated)));

    render(<StallView />);

    const trust = await screen.findByRole("region", { name: "Noor's trust record" });
    expect(trust).toHaveTextContent("26 orders delivered");
    expect(trust).toHaveTextContent(
      "1 of these orders came through OpenStall, and her record was signed again on December 1, 2026.",
    );
    expect(trust).toHaveTextContent("The rest are seeded demo numbers, not real sales.");
  });

  it("has a For AI agents box linking to her catalog entry and trust card on the API", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(NOOR)));

    render(<StallView />);

    const agents = await screen.findByRole("region", { name: "For AI agents" });
    // Only what agents can do today: read and search, not order.
    expect(agents).toHaveTextContent(
      "Buyer agents can read Noor's stall as JSON, or search it through OpenStall's MCP server.",
    );
    expect(
      within(agents).getByRole("link", { name: "Catalog entry: Chain-stitch embroidered cushion cover" }),
    ).toHaveAttribute("href", "http://api.test/catalog/p_noor_cushion.json");
    expect(within(agents).getByRole("link", { name: "Trust card: Noor's passport" })).toHaveAttribute(
      "href",
      "http://api.test/passport/s_noor",
    );
    expect(within(agents).getByText("Signed")).toBeInTheDocument();
    expect(within(agents).getByRole("link", { name: "Check its signature" })).toHaveAttribute(
      "href",
      "http://api.test/passport/s_noor/verify",
    );
    // The addresses themselves, for people setting up an agent.
    expect(within(agents).getByText("http://api.test/catalog/p_noor_cushion.json")).toBeInTheDocument();
    expect(within(agents).getByRole("group", { name: "MCP server address" })).toHaveTextContent("http://api.test/mcp");
    expect(within(agents).getByRole("link", { name: "catalog.json" })).toHaveAttribute(
      "href",
      "http://api.test/catalog.json",
    );
    expect(within(agents).getByRole("link", { name: "llms.txt" })).toHaveAttribute("href", "http://api.test/llms.txt");
    expect(agents).toHaveTextContent("no agent tool can move money");
  });

  it("copies the MCP server address with one click", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(NOOR)));
    render(<StallView />);
    const agents = await screen.findByRole("region", { name: "For AI agents" });

    await act(async () => {
      fireEvent.click(within(agents).getByRole("button", { name: "Copy the MCP server address" }));
    });

    expect(writeText).toHaveBeenCalledWith("http://api.test/mcp");
    expect(within(agents).getByRole("status")).toHaveTextContent("Copied");
    Reflect.deleteProperty(navigator, "clipboard");
  });

  it("links her listings but no trust card for a maker who has no passport yet", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...NOOR, trust: null })));

    render(<StallView />);

    const agents = await screen.findByRole("region", { name: "For AI agents" });
    expect(within(agents).getAllByRole("listitem")).toHaveLength(1);
    expect(
      within(agents).getByRole("link", { name: "Catalog entry: Chain-stitch embroidered cushion cover" }),
    ).toHaveAttribute("href", "http://api.test/catalog/p_noor_cushion.json");
    expect(within(agents).queryByRole("link", { name: /^Trust card/ })).not.toBeInTheDocument();
    expect(within(agents).queryByText("Signed")).not.toBeInTheDocument();
    expect(agents).toHaveTextContent("Buyer agents can read Noor's stall as JSON, or search it");
  });

  it("links only her trust card when she has nothing listed", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...NOOR, products: [] })));

    render(<StallView />);

    const agents = await screen.findByRole("region", { name: "For AI agents" });
    const [card] = within(agents).getAllByRole("listitem");
    expect(within(agents).getAllByRole("listitem")).toHaveLength(1);
    expect(within(card).getByRole("link", { name: "Trust card: Noor's passport" })).toHaveAttribute(
      "href",
      "http://api.test/passport/s_noor",
    );
    expect(within(card).getByText("Signed")).toBeInTheDocument();
    expect(within(agents).queryByRole("link", { name: /^Catalog entry/ })).not.toBeInTheDocument();
    expect(agents).toHaveTextContent(
      "Noor has nothing listed right now, so agents can read only her trust card. OpenStall's MCP server and " +
        "catalog.json have the other makers' listings.",
    );
    expect(agents).not.toHaveTextContent("read Noor's stall as JSON");
  });

  it("says a maker with nothing listed and no passport has nothing for agents yet", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...NOOR, products: [], trust: null })));

    render(<StallView />);

    const agents = await screen.findByRole("region", { name: "For AI agents" });
    expect(within(agents).queryByRole("link", { name: /^Trust card/ })).not.toBeInTheDocument();
    expect(within(agents).queryByRole("link", { name: /^Catalog entry/ })).not.toBeInTheDocument();
    expect(within(agents).queryByRole("list")).not.toBeInTheDocument();
    // It does not promise JSON or a search of hers; the MCP server and the catalog are for the other makers.
    expect(agents).toHaveTextContent(
      "Noor has nothing for agents to read yet: no live listing and no trust card. OpenStall's MCP server and " +
        "catalog.json have the other makers' listings.",
    );
    expect(agents).not.toHaveTextContent("read Noor's stall as JSON");
    expect(within(agents).getByRole("button", { name: "Copy the MCP server address" })).toBeInTheDocument();
  });

  it("says there is no stall when the API does not know the id", async () => {
    params.id = "s_nobody";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json({ detail: "There is no stall called 's_nobody'." }, { status: 404 })),
    );

    render(<StallView />);

    expect(await screen.findByRole("heading", { name: "No stall here" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See all the makers" })).toHaveAttribute("href", "/#makers");
  });

  it("says when the stall cannot be loaded, and loads it on Try again", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(Response.json(NOOR));
    vi.stubGlobal("fetch", fetchMock);

    render(<StallView />);

    expect(await screen.findByRole("alert")).toHaveTextContent("This stall could not be loaded");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Noor" })).toBeInTheDocument();
  });
});
