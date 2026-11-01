import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import StatusPage, { metadata } from "@/app/status/page";

// The panel has its own tests; here it would only make network calls.
vi.mock("@/components/status-panel", () => ({ StatusPanel: () => <p>The status panel</p> }));

describe("status page", () => {
  it("says what the page shows and holds the status panel", () => {
    render(<StatusPage />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("System status");
    expect(screen.getByText(/on stand-ins or on the real sandboxes/)).toBeInTheDocument();
    expect(screen.getByText("The status panel")).toBeInTheDocument();
  });

  it("has a title that follows the site's pattern", () => {
    // The layout's template turns this into "System status · OpenStall Collective".
    expect(metadata.title).toBe("System status");
  });
});
