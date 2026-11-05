import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LiveListingCard } from "@/components/live-listing";
import type { LiveListing } from "@/lib/chats";

const LISTING: LiveListing = {
  product_id: "p_web",
  title: "Hand-embroidered cushion cover",
  price_usd: "18.00",
  stall_path: "/stall/s_web",
};

describe("LiveListingCard", () => {
  it("says her listing is live, what it is, and links her stall", () => {
    render(<LiveListingCard listing={LISTING} mine={false} />);

    expect(screen.getByRole("heading", { name: /Her listing is live/ })).toHaveTextContent("Live");
    expect(screen.getByRole("region", { name: /Her listing is live/ })).toHaveTextContent(
      "Hand-embroidered cushion cover, $18.00 each.",
    );
    expect(screen.getByRole("link", { name: "Open her stall" })).toHaveAttribute("href", "/stall/s_web");
  });

  it("on your own phone it says your", () => {
    render(<LiveListingCard listing={LISTING} mine />);

    expect(screen.getByRole("heading", { name: /Your listing is live/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open your stall" })).toBeInTheDocument();
  });
});
