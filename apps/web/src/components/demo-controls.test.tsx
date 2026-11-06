import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DemoControls } from "@/components/demo-controls";
import type { EventStreamState } from "@/hooks/use-event-stream";
import { stepsDone } from "@/lib/demo";
import type { FeedEvent } from "@/lib/events";

const stream: EventStreamState = { events: [], connected: true, error: null };

vi.mock("@/hooks/use-event-stream", async (original) => ({
  ...(await original<typeof import("@/hooks/use-event-stream")>()),
  useEventStream: () => stream,
}));

const RUN = {
  steps: ["1. Searched"],
  request_id: "q_1",
  order_id: "ord_9",
  total_usd: "815.00",
  shares: [["Priya", 11]],
  approval_url: "http://localhost:3000/approve/ord_9",
};

/** Events newest first, as the stream keeps them. */
function events(...types: string[]): FeedEvent[] {
  return types
    .map((type, index) => ({ id: index + 1, type, entity_id: null, summary: type, payload: {}, created_at: "2026-11-10T10:00:00Z" }))
    .reverse();
}

function states(): string[] {
  const steps = screen.getByRole("list", { name: "The buyer agent's steps" });
  return within(steps)
    .getAllByRole("listitem")
    .map((item) => item.getAttribute("data-state") ?? "");
}

beforeEach(() => {
  stream.events = [];
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("DemoControls", () => {
  it("runs the story and links the drafted order's approval page", async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json(RUN));
    vi.stubGlobal("fetch", fetch);

    render(<DemoControls />);
    fireEvent.click(screen.getByRole("button", { name: "Run the demo request" }));

    expect(await screen.findByRole("link", { name: "Open its approval page" })).toHaveAttribute("href", "/approve/ord_9");
    expect(screen.getByRole("status")).toHaveTextContent("Order ord_9 drafted: $815.00.");
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/demo/run", expect.objectContaining({ method: "POST" }));
  });

  it("runs it with an AI agent: the tools it chose, its answer, and the order's approval page", async () => {
    const agentRun = {
      agent: "test mode's stand-in for Claude",
      request: "Please buy 40 hand-embroidered cushion covers for corporate gifts",
      steps: [
        { tool: "search_products", arguments: {}, ok: true, summary: "12 listings found" },
        { tool: "request_quote", arguments: {}, ok: true, summary: "Quote q_2: 4 valid offers" },
        { tool: "create_collective_order", arguments: {}, ok: true, summary: "Order ord_10 drafted: $815.00" },
        { tool: "checkout", arguments: {}, ok: true, summary: "Approval link for the person" },
      ],
      said: ["I'll look first.", "Order ord_10 is drafted. Approve it here: http://localhost:3000/approve/ord_10"],
      finished: true,
      request_id: "q_2",
      order_id: "ord_10",
      total_usd: "815.00",
      approval_url: "http://localhost:3000/approve/ord_10",
    };
    const fetch = vi.fn().mockResolvedValue(Response.json(agentRun));
    vi.stubGlobal("fetch", fetch);

    render(<DemoControls />);
    fireEvent.click(screen.getByRole("button", { name: "Run it with an AI agent" }));

    expect(await screen.findByRole("link", { name: "Open its approval page" })).toHaveAttribute("href", "/approve/ord_10");
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("The buyer's AI agent (test mode's stand-in for Claude) chose 4 tools:");
    const tools = within(status).getByRole("list", { name: "The tools the AI agent chose" });
    expect(within(tools).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "search_products: 12 listings found",
      "request_quote: Quote q_2: 4 valid offers",
      "create_collective_order: Order ord_10 drafted: $815.00",
      "checkout: Approval link for the person",
    ]);
    expect(status).toHaveTextContent("Order ord_10 is drafted. Approve it here: http://localhost:3000/approve/ord_10");
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/demo/run-agent", expect.objectContaining({ method: "POST" }));
  });

  it("asks before resetting, and says when it is done", async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ sellers: 5, products: 5, passports: 5, order_id: "ord_demo" }));
    vi.stubGlobal("fetch", fetch);
    render(<DemoControls />);

    fireEvent.click(screen.getByRole("button", { name: "Reset demo" }));
    expect(screen.getByRole("group", { name: "Confirm the reset" })).toHaveTextContent("Remove every order, quote and offer?");
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Yes, reset" }));

    expect(await screen.findByText(/The demo is reset/)).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith("http://api.test/api/demo/reset", expect.objectContaining({ method: "POST" }));
  });

  it("asks for the demo token when the API needs one, and sends it", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ detail: "The demo controls need the X-Demo-Run-Token header." }, { status: 401 }))
      .mockResolvedValueOnce(Response.json(RUN));
    vi.stubGlobal("fetch", fetch);
    render(<DemoControls />);

    fireEvent.click(screen.getByRole("button", { name: "Run the demo request" }));
    const field = await screen.findByLabelText("Demo token (sandbox mode)");
    expect(screen.getByRole("alert")).toHaveTextContent("The demo controls need the X-Demo-Run-Token header.");
    fireEvent.change(field, { target: { value: "s3cret" } });
    fireEvent.click(screen.getByRole("button", { name: "Run the demo request" }));

    expect(await screen.findByRole("link", { name: "Open its approval page" })).toBeInTheDocument();
    const sent = new Headers((fetch.mock.calls[1][1] as RequestInit).headers);
    expect(sent.get("X-Demo-Run-Token")).toBe("s3cret");
  });

  it("follows the latest run on the stepper", () => {
    stream.events = events("demo.run", "search.logged", "quote.requested");
    render(<DemoControls />);

    expect(states()).toEqual(["done", "done", "now", "waiting", "waiting"]);
  });
});

describe("stepsDone", () => {
  it("counts the steps done since the latest run, and starts over after a reset", () => {
    expect(stepsDone(events())).toBeNull();
    expect(stepsDone(events("search.logged"))).toBeNull();
    expect(stepsDone(events("demo.run"))).toBe(0);
    expect(
      stepsDone(events("demo.run", "search.logged", "quote.requested", "offer.accepted", "allocation.planned", "checkout.link_issued")),
    ).toBe(5);
    // Steps from an earlier run do not count.
    expect(stepsDone(events("search.logged", "quote.requested", "demo.run", "search.logged"))).toBe(1);
    expect(stepsDone(events("demo.run", "search.logged", "demo.reset"))).toBeNull();
    // A buyer's AI agent's run is followed the same way.
    expect(stepsDone(events("demo.run", "search.logged", "agent.started", "search.logged", "quote.requested"))).toBe(2);
  });
});
