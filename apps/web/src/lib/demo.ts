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

function headers(token: string | null): RequestInit {
  return token ? { headers: { [TOKEN_HEADER]: token } } : {};
}

/** Runs the story's request with the scripted buyer agent, through the MCP storefront. */
export function runDemo(token: string | null = null): Promise<DemoRun> {
  return apiPost<DemoRun>("/api/demo/run", {}, headers(token));
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

/**
 * How far the latest run has got: the number of steps done, from the events since the newest demo.run (events come
 * newest first). Null before any run, or after a reset.
 */
export function stepsDone(events: FeedEvent[]): number | null {
  const start = events.findIndex((event) => event.type === "demo.run" || event.type === "demo.reset");
  if (start === -1 || events[start].type === "demo.reset") return null;
  const since = new Set(events.slice(0, start).map((event) => event.type));
  let done = 0;
  for (const step of STEPS) {
    if (!since.has(step.done)) break;
    done += 1;
  }
  return done;
}
