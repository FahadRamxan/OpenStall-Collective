import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import HomePage from "@/app/page";

describe("home page", () => {
  it("says what OpenStall is", () => {
    render(<HomePage />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Small sellers on WhatsApp, selling to AI shopping agents",
    );
    expect(screen.getByText(/one PayPal checkout pays them all/)).toBeInTheDocument();
  });

  it("does not repeat the name the header already shows", () => {
    render(<HomePage />);

    expect(screen.getByText("PayPal AI Hackathon demo")).toBeInTheDocument();
    expect(screen.queryByText("OpenStall Collective")).not.toBeInTheDocument();
  });

  it("links to the live demo", () => {
    render(<HomePage />);

    expect(screen.getByRole("link", { name: "See the live demo" })).toHaveAttribute("href", "/demo");
  });

  it("says who it is for", () => {
    render(<HomePage />);

    expect(screen.getByRole("heading", { level: 2, name: "Who it is for" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual([
      "Sellers",
      "Buyer agents",
      "The people behind the agents",
      "Demo viewers and judges",
    ]);
  });
});
