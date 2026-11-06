import { apiPost } from "@/lib/api";
import type { FeedEvent } from "@/lib/events";

/** The header that unlocks the demo controls in sandbox mode. */
export const TOKEN_HEADER = "X-Demo-Run-Token";

/** What the scripted buyer agent did, as POST /api/demo/run says. */
export type DemoRun = {
  steps: string[];
  request_id: string;
  order_id: string;
  total_usd: string;
  shares: [string, number][];
  approval_url: string;
};

export type DemoReset = { sellers: number; products: number; passports: number; order_id: string };

/** One tool a buyer's AI agent chose, and how it went. */
export type AgentStep = { tool: string; arguments: Record<string, unknown>; ok: boolean; summary: string };

/** What the buyer's AI agent did, as POST /api/demo/run-agent says. */
export type DemoAgentRun = {
  /** Claude and its model, or test mode's stand-in. */
  agent: string;
  request: string;
  steps: AgentStep[];
  /** What it said, turn by turn; the last is its answer to the person. */
  said: string[];
  finished: boolean;
  request_id: string | null;
  order_id: string | null;
  total_usd: string | null;
  approval_url: string | null;
};

function headers(token: string | null): RequestInit {
  return token ? { headers: { [TOKEN_HEADER]: token } } : {};
}

/** Runs the story's request with the scripted buyer agent, through the MCP storefront. */
export function runDemo(token: string | null = null): Promise<DemoRun> {
  return apiPost<DemoRun>("/api/demo/run", {}, headers(token));
}

/** Runs the story's request with a buyer's AI agent that chooses the storefront's tools itself. */
export function runAgent(token: string | null = null): Promise<DemoAgentRun> {
  return apiPost<DemoAgentRun>("/api/demo/run-agent", {}, headers(token));
}

/** Puts the demo world back as seeded. */
export function resetDemo(token: string | null = null): Promise<DemoReset> {
  return apiPost<DemoReset>("/api/demo/reset", {}, headers(token));
}

/** The buyer agent's steps, in order, and the event that says each one is done. */
export const STEPS = [
  { name: "Search", done: "search.logged" },
  { name: "Quote", done: "quote.requested" },
  { name: "Offers", done: "offer.accepted" },
  { name: "Allocation", done: "allocation.planned" },
  { name: "Approval", done: "checkout.link_issued" },
] as const;

/** The events that start a run: the scripted buyer agent's, or a buyer's AI agent's. */
const RUN_STARTS = new Set(["demo.run", "agent.started"]);

/**
 * How far the latest run has got: the number of steps done, from the events since the newest run started (events
 * come newest first). Null before any run, or after a reset.
 */
export function stepsDone(events: FeedEvent[]): number | null {
  const start = events.findIndex((event) => RUN_STARTS.has(event.type) || event.type === "demo.reset");
  if (start === -1 || events[start].type === "demo.reset") return null;
  const since = new Set(events.slice(0, start).map((event) => event.type));
  let done = 0;
  for (const step of STEPS) {
    if (!since.has(step.done)) break;
    done += 1;
  }
  return done;
}
