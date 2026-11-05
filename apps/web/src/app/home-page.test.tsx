import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import HomePage from "@/app/page";

// The makers grid and the numbers load from the API; each has its own tests.
vi.mock("@/components/maker-stalls", () => ({ MakerStalls: () => <p>The makers grid</p> }));
vi.mock("@/components/home-numbers", () => ({ HomeNumbers: () => <p>The numbers</p> }));

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
    expect(screen.getAllByRole("link", { name: "Try it as a seller" })[0]).toHaveAttribute("href", "/seller-chat");
  });

  it("shows the numbers right now", () => {
    render(<HomePage />);

    const numbers = screen.getByRole("region", { name: "Right now on OpenStall" });
    expect(within(numbers).getByText("The numbers")).toBeInTheDocument();
  });

  it("says how it works, each step linking to where it can be seen", () => {
    render(<HomePage />);

    const steps = within(screen.getByRole("region", { name: "How it works" })).getAllByRole("listitem");
    expect(steps.map((step) => within(step).getByRole("heading", { level: 3 }).textContent)).toEqual([
      "A maker lists by WhatsApp",
      "A buyer's AI agent asks",
      "Seller agents negotiate within her limits",
      "Plain code splits the order",
      "Each maker is paid on proof",
      "Trust and demand build up",
    ]);
    expect(steps.map((step) => within(step).getByRole("link").getAttribute("href"))).toEqual([
      "/seller-chat",
      "/demo#request-heading",
      "/demo#offers-heading",
      "/demo#allocation-heading",
      "/demo#payments-heading",
      "/dashboard",
    ]);
  });

  it("gives AI agents the MCP address and the feeds", () => {
    render(<HomePage />);

    const agents = screen.getByRole("region", { name: "For AI agents" });
    expect(within(agents).getByText("http://localhost:8000/mcp")).toBeInTheDocument();
    expect(within(agents).getByRole("link", { name: "catalog.json" })).toHaveAttribute(
      "href",
      "http://localhost:8000/catalog.json",
    );
    expect(within(agents).getByRole("link", { name: "llms.txt" })).toHaveAttribute("href", "http://localhost:8000/llms.txt");
  });

  it("says which PayPal pieces it is built on, and links the code", () => {
    render(<HomePage />);

    const paypal = screen.getByRole("region", { name: "Built on PayPal" });
    expect(within(paypal).getByText("Orders v2, intent AUTHORIZE")).toBeInTheDocument();
    expect(within(paypal).getByText("APIMatic's PayPal SDK")).toBeInTheDocument();
    expect(within(paypal).getByRole("link", { name: "Read the code on GitHub" })).toHaveAttribute(
      "href",
      "https://github.com/FahadRamxan/OpenStall-Collective",
    );
  });

  it("says who it is for", () => {
    render(<HomePage />);

    const audiences = screen.getByRole("region", { name: "Who it is for" });
    expect(within(audiences).getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent)).toEqual([
      "Sellers",
      "Buyer agents",
      "The people behind the agents",
      "Demo viewers and judges",
    ]);
  });
});
