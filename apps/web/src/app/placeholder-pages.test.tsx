import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import DashboardPage from "@/app/dashboard/page";
import DemoPage from "@/app/demo/page";
import SellerChatPage from "@/app/seller-chat/page";

describe.each([
  ["/demo", DemoPage, "Live demo"],
  ["/seller-chat", SellerChatPage, "Seller chat"],
  ["/dashboard", DashboardPage, "Dashboard"],
])("%s", (_path, Page, title) => {
  it("says it is coming soon", () => {
    render(<Page />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(title);
    expect(screen.getByText("Coming soon")).toBeInTheDocument();
  });
});
