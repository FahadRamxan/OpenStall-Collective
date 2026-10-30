import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SiteFooter } from "@/components/site-footer";

// The API check has its own tests; here it would only make network calls.
vi.mock("@/components/api-status", () => ({ ApiStatus: () => null }));

describe("SiteFooter", () => {
  it("says the app runs in the PayPal sandbox and moves no real money", () => {
    render(<SiteFooter />);

    expect(screen.getByRole("contentinfo")).toHaveTextContent("Runs in the PayPal sandbox. No real money moves.");
  });
});
