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
  words: { price_usd: "اٹھارہ ڈالر", capacity_per_week: "ہفتے میں چار" },
  missing: ["ship_days", "ship_from_city"],
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

  it("says what is still to ask, and never shows a number for it", () => {
    render(<ListingDraftCard draft={DRAFT} mine={false} />);

    expect(field("Delivery time")).toHaveTextContent("Still to ask");
    expect(field("Ships from")).toHaveTextContent("Still to ask");
  });

  it("on your own phone it says your", () => {
    render(<ListingDraftCard draft={{ ...DRAFT, ship_days: 9, missing: ["ship_from_city"] }} mine />);

    expect(screen.getByRole("heading", { name: /Your listing so far/ })).toBeInTheDocument();
    expect(field("Price")).toHaveTextContent("In your words");
    expect(field("Delivery time")).toHaveTextContent("9 days to arrive");
  });
});
