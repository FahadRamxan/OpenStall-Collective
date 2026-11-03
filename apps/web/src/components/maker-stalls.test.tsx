import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MakerStalls } from "@/components/maker-stalls";
import type { SellerCard } from "@/lib/catalog";

function card(overrides: Partial<SellerCard>): SellerCard {
  return {
    id: "s_priya",
    name: "Priya",
    city: "Jaipur",
    country: "IN",
    language: "hi",
    data_source: "seeded_demo",
    headline: "Mirror-work embroidered cushion cover",
    from_price_usd: "16.00",
    cover_photo: "/media/seed/priya-cushion-1.svg",
    ...overrides,
  };
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("MakerStalls", () => {
  it("shows placeholders while loading", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    render(<MakerStalls />);

    expect(screen.getByRole("list", { name: "Loading the makers" })).toHaveAttribute("aria-busy", "true");
  });

  it("shows one card per stall, each linking to it, with place, price and a seeded label", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json([card({}), card({ id: "s_noor", name: "Noor", data_source: "live" })])),
    );

    render(<MakerStalls />);

    const priya = await screen.findByRole("link", { name: /Priya/ });
    expect(priya).toHaveAttribute("href", "/stall/s_priya");
    expect(priya).toHaveTextContent("Jaipur, India");
    expect(priya).toHaveTextContent("from $16.00");
    expect(priya).toHaveTextContent("Mirror-work embroidered cushion cover");
    expect(within(priya).getByText("Seeded demo")).toBeInTheDocument();
    expect(priya.querySelector("img")).toHaveAttribute("src", "http://api.test/media/seed/priya-cushion-1.svg");
    expect(within(screen.getByRole("link", { name: /Noor/ })).queryByText("Seeded demo")).not.toBeInTheDocument();
  });

  it("says when no stalls are open", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json([])));

    render(<MakerStalls />);

    expect(await screen.findByText("No stalls are open yet.")).toBeInTheDocument();
  });

  it("says when the makers cannot be loaded, and loads them on Try again", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(Response.json([card({})]));
    vi.stubGlobal("fetch", fetchMock);

    render(<MakerStalls />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The makers could not be loaded.");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("link", { name: /Priya/ })).toBeInTheDocument();
  });
});
