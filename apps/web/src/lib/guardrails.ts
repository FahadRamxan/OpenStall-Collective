import { apiGet, apiPost } from "@/lib/api";
import { TOKEN_HEADER } from "@/lib/demo";

/** One attack the guardrail panel can try, and what refuses it (GET /api/guardrails). */
export type Attack = { key: string; name: string; guard: string };

/** refused: the guardrail held. got_through: it did not. not_tried: the demo world lacked what it needs. */
export type AttackResult = "refused" | "got_through" | "not_tried";

/** What one attack tried, and what happened. */
export type Outcome = Attack & { tried: string; result: AttackResult; reason: string };

function headers(token: string | null): RequestInit {
  return token ? { headers: { [TOKEN_HEADER]: token } } : {};
}

export function getAttacks(init: RequestInit = {}): Promise<Attack[]> {
  return apiGet<Attack[]>("/api/guardrails", init);
}

/** Tries every attack, one after the other. In sandbox mode the API asks for the demo token. */
export function runEveryAttack(token: string | null = null): Promise<Outcome[]> {
  return apiPost<Outcome[]>("/api/guardrails/run", {}, headers(token));
}

/** Tries one attack. */
export function runAttack(key: string, token: string | null = null): Promise<Outcome> {
  return apiPost<Outcome>(`/api/guardrails/${encodeURIComponent(key)}/run`, {}, headers(token));
}
