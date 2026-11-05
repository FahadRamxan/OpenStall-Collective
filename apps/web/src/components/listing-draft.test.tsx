import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ListingDraftCard } from "@/components/listing-draft";
import type { ListingDraft } from "@/lib/chats";

const DRAFT: ListingDraft = {
  title: "Hand-embroidered cushion cover",
  description: "A cotton cushion cover embroidered by hand.",
  category: "home textiles",
  variants: ["red", "teal", "mustard"],
  price_usd: "18.00",
  capacity_per_week: 4,
  ship_days: null,
  ship_from_city: null,
  photos: ["/media/uploads/abc.png"],
  floor_price_usd: null,
  min_lead_days: null,
  words: { price_usd: "اٹھارہ ڈالر", capacity_per_week: "ہفتے میں چار" },
  missing: ["ship_days", "ship_from_city", "floor_price_usd", "min_lead_days"],
  asked: "ship_days",
};

function field(name: string): HTMLElement {
  const term = screen.getByText(name, { selector: "dt" });
  return term.nextElementSibling as HTMLElement;
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

describe("ListingDraftCard", () => {
  it("shows each field read so far, with her own words for each number", () => {
    render(<ListingDraftCard draft={DRAFT} mine={false} />);

    expect(screen.getByRole("heading", { name: /Her listing so far/ })).toHaveTextContent("Draft, not live yet");
    expect(field("What it is")).toHaveTextContent("Hand-embroidered cushion cover");
    expect(field("Colours or styles")).toHaveTextContent("red, teal, mustard");
    expect(field("Price")).toHaveTextContent("$18.00 each");
    expect(field("Price")).toHaveTextContent("In her words: اٹھارہ ڈالر");
    expect(within(field("Price")).getByText("اٹھارہ ڈالر")).toHaveAttribute("dir", "auto");
    expect(field("How many a week")).toHaveTextContent("4 a week");
    expect(within(field("Photos")).getByRole("img", { name: "A listing photo" })).toHaveAttribute(
      "src",
      "http://api.test/media/uploads/abc.png",
    );
  });

  it("marks the one question asked now, says what is still to ask, and never shows a number for it", () => {
    render(<ListingDraftCard draft={DRAFT} mine={false} />);

    expect(field("Delivery time")).toHaveTextContent("Asking now");
    expect(field("Ships from")).toHaveTextContent("Still to ask");
    expect(field("Lowest price")).toHaveTextContent("Still to ask");
    expect(field("Days to make an order")).toHaveTextContent("Still to ask");
    expect(screen.getAllByText("Asking now")).toHaveLength(1);
  });

  it("shows her limits apart from the listing, as not shown to buyers", () => {
    render(
      <ListingDraftCard
        draft={{
          ...DRAFT,
          ship_days: 9,
          ship_from_city: "Lahore",
          floor_price_usd: "15.00",
          min_lead_days: 5,
          words: { ...DRAFT.words, floor_price_usd: "15", min_lead_days: "5" },
          missing: [],
          asked: null,
        }}
        mine={false}
      />,
    );

    expect(screen.getByRole("heading", { name: "Her limits" })).toBeInTheDocument();
    expect(screen.getByText(/Not shown to buyers/)).toBeInTheDocument();
    expect(field("Lowest price")).toHaveTextContent("$15.00 each, for a big order");
    expect(field("Lowest price")).toHaveTextContent("In her words: 15");
    expect(field("Days to make an order")).toHaveTextContent("5 days at least");
    expect(screen.queryByText("Still to ask")).not.toBeInTheDocument();
    expect(screen.queryByText("Asking now")).not.toBeInTheDocument();
    expect(screen.queryByText(/Waiting for her yes/)).not.toBeInTheDocument();
  });

  it("says when it only waits for her yes", () => {
    render(<ListingDraftCard draft={{ ...DRAFT, missing: [], asked: null, confirming: true }} mine={false} />);

    expect(screen.getByText(/Waiting for her yes/)).toHaveTextContent("Only a yes publishes it.");
    expect(screen.getByRole("heading", { name: /Her listing so far/ })).toHaveTextContent("Draft, not live yet");
  });

  it("on your own phone it says your", () => {
    render(
      <ListingDraftCard
        draft={{ ...DRAFT, ship_days: 9, missing: ["ship_from_city", "floor_price_usd", "min_lead_days"] }}
        mine
      />,
    );

    expect(screen.getByRole("heading", { name: /Your listing so far/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Your limits" })).toBeInTheDocument();
    expect(field("Price")).toHaveTextContent("In your words");
    expect(field("Delivery time")).toHaveTextContent("9 days to arrive");
  });
});
