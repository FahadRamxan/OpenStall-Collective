import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HomeNumbers } from "@/components/home-numbers";
import { tileUsd, type Overview } from "@/lib/overview";

const OVERVIEW: Overview = {
  makers: 5,
  listings: 5,
  orders_approved: 2,
  paid_usd: "382.50",
  makers_paid: 2,
  deliveries: 1,
  agent_searches: 14,
  simulated: true,
};

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

function tile(label: string): string {
  const term = screen.getByText(label);
  return term.parentElement?.textContent ?? "";
}

describe("HomeNumbers", () => {
  it("shows each number as a tile, and says when PayPal is simulated", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json(OVERVIEW));
    vi.stubGlobal("fetch", fetchMock);

    render(<HomeNumbers />);

    expect(await screen.findByText("Makers with a live listing")).toBeInTheDocument();
    expect(fetchMock.mock.calls[0][0]).toBe("http://api.test/api/overview");
    expect(tile("Makers with a live listing")).toBe("Makers with a live listing5");
    expect(tile("Orders approved")).toBe("Orders approved2");
    expect(tile("Paid to makers on proof")).toBe("Paid to makers on proof$382.50to 2 makers");
    expect(tile("Parcels delivered")).toBe("Parcels delivered1");
    expect(tile("Agent searches this week")).toBe("Agent searches this week14");
    expect(screen.getByText(/Test mode: PayPal is simulated/)).toBeInTheDocument();
  });

  it("says so when the numbers cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(<HomeNumbers />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The numbers could not be loaded");
  });
});

describe("tileUsd", () => {
  it("writes money the way a stat tile shows it", () => {
    expect(tileUsd("176.00")).toBe("$176");
    expect(tileUsd("206.50")).toBe("$206.50");
    expect(tileUsd("0.00")).toBe("$0");
    expect(tileUsd("12940.00")).toBe("$12.9K");
  });
});
