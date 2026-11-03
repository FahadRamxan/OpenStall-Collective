import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SiteFooter } from "@/components/site-footer";

// The API check has its own tests; here it would only make network calls.
vi.mock("@/components/api-status", () => ({ ApiStatus: () => null }));

describe("SiteFooter", () => {
  it("says the app runs in the PayPal sandbox and moves no real money", () => {
    render(<SiteFooter />);

    expect(screen.getByRole("contentinfo")).toHaveTextContent("No real money moves: PayPal's sandbox, or simulated PayPal in test mode.");
  });

  it("links to the system status page", () => {
    render(<SiteFooter />);

    expect(screen.getByRole("link", { name: "System status" })).toHaveAttribute("href", "/status");
  });
});
