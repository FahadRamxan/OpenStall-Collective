import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StallView } from "@/components/stall-view";
import type { SellerDetail } from "@/lib/catalog";

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
