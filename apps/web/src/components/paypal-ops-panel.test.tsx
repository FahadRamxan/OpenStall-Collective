import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PayPalOpsPanel, SAMPLE_QUESTION } from "@/components/paypal-ops-panel";

const TOOLS = {
  server: "Test mode's stand-in for PayPal's MCP server",
  tools: [
    { name: "get_order", reads: true, offered: true },
    { name: "list_disputes", reads: true, offered: true },
    { name: "create_refund", reads: false, offered: false },
    { name: "pay_order", reads: false, offered: false },
  ],
};
const CHECK = {
  order_id: "ord_demo",
  paypal_order_id: "FAKE-0123456789ABCDEF",
  server: TOOLS.server,
  agrees: false,
  findings: [
    { check: "The amount", ok: true, ours: "$815.00", paypal: "$815.00" },
    { check: "Priya's capture", ok: false, ours: "CAP-1, $176.00", paypal: "no such capture" },
  ],
};
const ANSWER = {
  agent: "Test mode's stand-in for the ops agent",
  server: TOOLS.server,
  question: SAMPLE_QUESTION,
  steps: [
    { tool: "get_order", arguments: { id: "FAKE-0123456789ABCDEF" }, ok: true, summary: "Answered" },
    { tool: "list_disputes", arguments: {}, ok: true, summary: "Answered" },
  ],
  answer: "PayPal says order FAKE-0123456789ABCDEF is COMPLETED, for $815.00. 0 disputes are open at PayPal.",
  refused: [],
};

function route(url: string) {
  if (url.endsWith("/api/paypal/ops/tools")) return TOOLS;
  if (url.endsWith("/api/paypal/ops/check")) return CHECK;
  if (url.endsWith("/api/paypal/ops/ask")) return ANSWER;
  throw new Error(`unexpected ${url}`);
}

afterEach(() => vi.unstubAllGlobals());

function stubFetch() {
  const fetch = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) =>
      new Response(JSON.stringify(route(String(input))), { headers: { "x-method": init?.method ?? "GET" } }),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("PayPalOpsPanel", () => {
  it("names the server, the tools the agent is offered, and the ones that write it never gets", async () => {
    stubFetch();
    render(<PayPalOpsPanel />);

    expect(await screen.findByText("Test mode's stand-in for PayPal's MCP server.")).toBeInTheDocument();
    expect(screen.getByText("get_order")).toBeInTheDocument();
    expect(
      screen.getByText("Never offered: 2 tools that change something at PayPal (create_refund, pay_order)."),
    ).toBeInTheDocument();
  });

  it("checks the latest order with PayPal and says plainly where PayPal differs", async () => {
    const fetch = stubFetch();
    render(<PayPalOpsPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Check the latest order with PayPal" }));

    const lines = await screen.findByRole("list", { name: "OpenStall beside PayPal" });
    expect(screen.getByText("PayPal differs on a line below.", { exact: false })).toBeInTheDocument();
    const [amount, capture] = within(lines).getAllByRole("listitem");
    expect(amount).toHaveTextContent("AgreesThe amountOpenStall: $815.00. PayPal: $815.00.");
    expect(capture).toHaveTextContent("DiffersPriya's captureOpenStall: CAP-1, $176.00. PayPal: no such capture.");
    expect(fetch.mock.calls.some(([url, init]) => String(url).endsWith("/check") && init?.method === "POST")).toBe(true);
  });

  it("asks the ops agent and shows what it read and what it said", async () => {
    const fetch = stubFetch();
    render(<PayPalOpsPanel />);

    fireEvent.click(screen.getByRole("button", { name: "Ask the ops agent" }));

    const read = await screen.findByRole("list", { name: "What the agent read" });
    expect(within(read).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "get_order Answered",
      "list_disputes Answered",
    ]);
    expect(screen.getByText(ANSWER.answer, { exact: false })).toBeInTheDocument();
    const [, init] = fetch.mock.calls.find(([url]) => String(url).endsWith("/ask")) ?? [];
    expect(JSON.parse(String(init?.body))).toEqual({ question: SAMPLE_QUESTION });
  });
});
