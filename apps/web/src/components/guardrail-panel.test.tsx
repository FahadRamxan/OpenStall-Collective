import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GuardrailPanel } from "@/components/guardrail-panel";
import type { Attack, Outcome } from "@/lib/guardrails";

const ATTACKS: Attack[] = [
  { key: "below_floor", name: "Talk a maker's price down to $1.00", guard: "The offer check in code" },
  { key: "capture_tool", name: "An AI agent captures the payment through MCP", guard: "No tool moves money" },
];

function outcome(attack: Attack, result: Outcome["result"] = "refused"): Outcome {
  return { ...attack, tried: `Tried: ${attack.name}.`, result, reason: `Refused: ${attack.key}.` };
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("GuardrailPanel", () => {
  it("tries every attack and shows each refusal, with what was tried", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith("/api/guardrails/run") && init?.method === "POST") return Response.json(ATTACKS.map((a) => outcome(a)));
      if (url.endsWith("/api/guardrails")) return Response.json(ATTACKS);
      return Response.json({ detail: "not found" }, { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<GuardrailPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "Try every attack" }));

    expect(await screen.findByText("2 of 2 attacks refused")).toBeInTheDocument();
    const row = screen.getByRole("listitem", { name: "Talk a maker's price down to $1.00" });
    expect(within(row).getByText("Refused")).toBeInTheDocument();
    expect(within(row).getByText("Tried: Talk a maker's price down to $1.00.")).toBeInTheDocument();
    expect(within(row).getByText("Refused: below_floor.")).toBeInTheDocument();
  });

  it("tries one attack, and says so plainly if one ever got through", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.endsWith("/api/guardrails/capture_tool/run")) return Response.json(outcome(ATTACKS[1], "got_through"));
        return Response.json(ATTACKS);
      }),
    );

    render(<GuardrailPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "Try it: An AI agent captures the payment through MCP" }));

    const row = screen.getByRole("listitem", { name: "An AI agent captures the payment through MCP" });
    expect(await within(row).findByText("Got through")).toBeInTheDocument();
    expect(screen.getByText("0 of 1 attack refused")).toBeInTheDocument();
    expect(within(screen.getByRole("listitem", { name: "Talk a maker's price down to $1.00" })).queryByText("Refused")).toBeNull();
  });

  it("asks for the demo token when the API needs it", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const token = new Headers(init.headers).get("X-Demo-Run-Token");
        return token === "s3cret"
          ? Response.json(ATTACKS.map((a) => outcome(a)))
          : Response.json({ detail: "The demo controls need the X-Demo-Run-Token header." }, { status: 401 });
      }
      return Response.json(ATTACKS);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<GuardrailPanel />);
    fireEvent.click(await screen.findByRole("button", { name: "Try every attack" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Not tried: The demo controls need the X-Demo-Run-Token");
    fireEvent.change(screen.getByLabelText("Demo token (sandbox mode)"), { target: { value: "s3cret" } });
    fireEvent.click(screen.getByRole("button", { name: "Try every attack" }));
    expect(await screen.findByText("2 of 2 attacks refused")).toBeInTheDocument();
  });

  it("says so when the attacks cannot be loaded", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: "down" }, { status: 503 })));

    render(<GuardrailPanel />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The attacks could not be loaded");
  });
});
