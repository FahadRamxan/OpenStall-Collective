import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AllocationPanel } from "@/components/allocation-panel";
import type { EventStreamState } from "@/hooks/use-event-stream";
import type { FeedEvent } from "@/lib/events";
import { planHeadline, shareWords, type Plan } from "@/lib/plans";
import type { Quote } from "@/lib/quotes";

const stream: EventStreamState = { events: [], connected: true, error: null };

vi.mock("@/hooks/use-event-stream", async (original) => ({
  ...(await original<typeof import("@/hooks/use-event-stream")>()),
  useEventStream: () => stream,
}));

const QUOTE: Quote = {
  id: "q_story",
  queries: ["40 hand-embroidered cushion covers for corporate gifts"],
  quantity: 40,
  max_unit_price: "30.00",
  deadline: "2026-12-10",
  ship_to: "Chicago",
  created_at: "2026-11-10T10:00:00Z",
  rounds: 1,
  completed_at: "2026-11-10T10:00:02Z",
  asked: 5,
  valid_offers: 5,
  total_capacity: 54,
};

function line(seller: string, quantity: number, price: string, total: string) {
  return {
    seller_id: `s_${seller.toLowerCase()}`,
    seller_name: seller,
    offer_id: `off_${seller.toLowerCase()}`,
    quantity,
    unit_price: price,
    line_total: total,
    delivery_date: "2026-12-10",
  };
}

const STORY: Plan = {
  request_id: "q_story",
  requested_quantity: 40,
  total_quantity: 40,
  total_cost: "815.00",
  complete: true,
  shortfall: 0,
  reason: null,
  lines: [
    line("Priya", 11, "16.00", "176.00"),
    line("Amina", 12, "18.00", "216.00"),
    line("Lucía", 10, "22.00", "220.00"),
    line("Grace", 7, "29.00", "203.00"),
  ],
  explanation:
    "Priya, Amina, Lucía and Grace made the cheapest valid offers, so the 40 units go to them in that order: " +
    "11, 12, 10 and 7. Together that is $815.00, all delivered by December 10, 2026.",
  explanation_source: "model",
  explanation_by: "Written by the stand-in model of test mode; every number checked against the plan.",
};

const SHORT: Plan = {
  ...STORY,
  total_quantity: 14,
  total_cost: "411.00",
  complete: false,
  shortfall: 26,
  reason: "Only 14 of 40 units can be supplied by 2026-12-10.",
  lines: [line("Grace", 4, "29.00", "116.00"), line("Noor", 10, "29.50", "295.00")],
};

/** The API's answers in order: the latest quote, then its plan (null for a 404). */
function mockApi(...answers: (Quote[] | Plan | null)[]) {
  const fetch = vi.fn();
  for (const answer of answers) {
    fetch.mockResolvedValueOnce(
      answer === null
        ? Response.json({ detail: "Quote request 'q_story' has no plan yet: its rounds are not done." }, { status: 404 })
        : Response.json(answer),
    );
  }
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function event(id: number, type: string): FeedEvent {
  return { id, type, entity_id: "q_story", summary: type, payload: {}, created_at: "2026-11-10T10:00:00Z" };
}

/** The plan table's rows, as text. */
async function planRows() {
  const grid = await screen.findByRole("grid");
  await waitFor(() => expect(within(grid).getAllByRole("row").length).toBeGreaterThan(2));
  return within(grid)
    .getAllByRole("row")
    .filter((row) => row.getAttribute("row-id"))
    .map((row) => row.textContent ?? "");
}

beforeEach(() => {
  stream.events = [];
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("AllocationPanel", () => {
  it("shows the latest quote's plan: each maker's share, the lines and the total", async () => {
    const fetch = mockApi([QUOTE], STORY);

    render(<AllocationPanel />);

    expect(screen.getByRole("heading", { name: "Allocation" })).toBeInTheDocument();
    expect(await screen.findByText("All 40 from 4 makers, $815.00")).toBeInTheDocument();
    expect(screen.getByText("Complete")).toBeInTheDocument();
    const shares = screen.getByRole("list", { name: "Each maker's share of the 40" });
    expect(within(shares).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Priya: 11 units",
      "Amina: 12 units",
      "Lucía: 10 units",
      "Grace: 7 units",
    ]);
    const rows = await planRows();
    expect(rows.find((row) => row.startsWith("Priya"))).toContain("$176.00");
    expect(rows.find((row) => row.startsWith("Total"))).toContain("$815.00");
    expect(fetch).toHaveBeenNthCalledWith(2, "http://api.test/api/quotes/q_story/plan", expect.anything());
  });

  it("explains the plan in words and says who wrote them", async () => {
    mockApi([QUOTE], STORY);

    render(<AllocationPanel />);

    const words = await screen.findByLabelText("The plan in words");
    expect(words).toHaveTextContent("so the 40 units go to them in that order: 11, 12, 10 and 7");
    expect(
      screen.getByText("Written by the stand-in model of test mode; every number checked against the plan."),
    ).toBeInTheDocument();
  });

  it("shows no words for a plan without an explanation", async () => {
    mockApi([QUOTE], { ...STORY, explanation: null, explanation_source: null, explanation_by: null });

    render(<AllocationPanel />);

    expect(await screen.findByText("All 40 from 4 makers, $815.00")).toBeInTheDocument();
    expect(screen.queryByLabelText("The plan in words")).not.toBeInTheDocument();
  });

  it("says how many are possible, and why, when the plan is short", async () => {
    mockApi([QUOTE], SHORT);

    render(<AllocationPanel />);

    expect(await screen.findByText("Only 14 of 40 possible")).toBeInTheDocument();
    expect(screen.getByText("Only 14 of 40 units can be supplied by 2026-12-10.")).toBeInTheDocument();
    const shares = screen.getByRole("list", { name: "Each maker's share of the 40" });
    expect(within(shares).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Grace: 4 units",
      "Noor: 10 units",
      "Short: 26 units",
    ]);
  });

  it("shows a share's units and part of the whole on hover or focus", async () => {
    mockApi([QUOTE], STORY);
    render(<AllocationPanel />);
    const shares = await screen.findByRole("list", { name: "Each maker's share of the 40" });
    const [priya, amina] = within(shares).getAllByRole("listitem");

    fireEvent.pointerEnter(priya);
    expect(screen.getByText("Priya · 28% of 40")).toBeInTheDocument();
    fireEvent.pointerLeave(priya);
    expect(screen.queryByText("Priya · 28% of 40")).not.toBeInTheDocument();

    fireEvent.focus(amina);
    expect(screen.getByText("Amina · 30% of 40")).toBeInTheDocument();
  });

  it("waits for a plan while the quote runs, and loads it when allocation.planned arrives", async () => {
    const fetch = mockApi([QUOTE], null, [QUOTE], STORY);
    const view = render(<AllocationPanel />);
    expect(await screen.findByText(/No plan yet/)).toBeInTheDocument();

    stream.events = [event(3, "offer.accepted")];
    view.rerender(<AllocationPanel />);
    expect(fetch).toHaveBeenCalledTimes(2);

    stream.events = [event(4, "allocation.planned"), ...stream.events];
    view.rerender(<AllocationPanel />);

    expect(await screen.findByText("All 40 from 4 makers, $815.00")).toBeInTheDocument();
  });

  it("says when there is no quote, and when the plan cannot be loaded", async () => {
    mockApi([]);
    const view = render(<AllocationPanel />);
    expect(await screen.findByText(/No plan yet/)).toBeInTheDocument();
    view.unmount();

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    render(<AllocationPanel />);
    expect(await screen.findByRole("alert")).toHaveTextContent("The allocation could not be loaded");
  });
});

describe("plan words", () => {
  it("heads a complete plan with its makers and cost, and a short one with what is possible", () => {
    expect(planHeadline(STORY)).toBe("All 40 from 4 makers, $815.00");
    expect(planHeadline(SHORT)).toBe("Only 14 of 40 possible");
    expect(planHeadline({ ...STORY, lines: [STORY.lines[0]] })).toBe("All 40 from 1 maker, $815.00");
    expect(shareWords(7, 40)).toBe("18%");
  });
});
