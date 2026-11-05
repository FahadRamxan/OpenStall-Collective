import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import DashboardPage from "@/app/dashboard/page";

vi.mock("@/hooks/use-event-stream", () => ({ EventStreamProvider: ({ children }: { children: ReactNode }) => children }));
vi.mock("@/components/dashboard-view", () => ({ DashboardView: () => <p>The dashboard&apos;s tables</p> }));

describe("/dashboard", () => {
  it("is the dashboard itself, following the live feed, not a placeholder", () => {
    render(<DashboardPage />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Dashboard");
    expect(screen.getByText("The dashboard's tables")).toBeInTheDocument();
    expect(screen.queryByText("Coming soon")).not.toBeInTheDocument();
  });
});
