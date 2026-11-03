import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DashboardPage from "@/app/dashboard/page";

describe.each([
  ["/dashboard", DashboardPage, "Dashboard"],
])("%s", (_path, Page, title) => {
  it("says it is coming soon", () => {
    render(<Page />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(title);
    expect(screen.getByText("Coming soon")).toBeInTheDocument();
  });
});
