import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import NotFound, { metadata } from "@/app/not-found";

describe("not-found page", () => {
  it("says the page does not exist and links home", () => {
    render(<NotFound />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Page not found");
    expect(screen.getByRole("link", { name: "Go to the home page" })).toHaveAttribute("href", "/");
  });

  it("has a title that follows the site's pattern", () => {
    // The layout's template turns this into "Page not found · OpenStall Collective".
    expect(metadata.title).toBe("Page not found");
  });
});
