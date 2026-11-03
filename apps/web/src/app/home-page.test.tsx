import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import HomePage from "@/app/page";

// The makers grid loads from the API; it has its own tests.
vi.mock("@/components/maker-stalls", () => ({ MakerStalls: () => <p>The makers grid</p> }));

describe("home page", () => {
  it("says what OpenStall is", () => {
    render(<HomePage />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Many small makers. One big order. One PayPal checkout.",
    );
    expect(screen.getByText(/each maker is paid the moment she sends a photo of her shipping receipt/)).toBeInTheDocument();
  });

  it("introduces the makers", () => {
    render(<HomePage />);

    expect(screen.getByRole("heading", { level: 2, name: "Meet the makers" })).toBeInTheDocument();
    expect(screen.getByText("The makers grid")).toBeInTheDocument();
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
