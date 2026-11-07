import { apiGet, apiPost } from "@/lib/api";
import { TOKEN_HEADER } from "@/lib/demo";

/** One of PayPal's MCP server's tools: whether it only reads, and whether the ops agent is offered it. */
export type OpsTool = { name: string; reads: boolean; offered: boolean };

export type OpsTools = { server: string; tools: OpsTool[] };

/** One line of the check: OpenStall's record beside what PayPal says. */
export type OpsFinding = { check: string; ok: boolean; ours: string; paypal: string };

export type OpsCheck = {
  order_id: string;
  paypal_order_id: string | null;
  server: string;
  agrees: boolean;
  findings: OpsFinding[];
};

export type OpsStep = { tool: string; arguments: Record<string, unknown>; ok: boolean; summary: string };

export type OpsAnswer = {
  agent: string;
  server: string;
  question: string;
  steps: OpsStep[];
  answer: string;
  refused: string[];
};

function headers(token: string | null) {
  return token ? { headers: { [TOKEN_HEADER]: token } } : {};
}

/** PayPal's MCP server's tools, and which the ops agent is offered (GET /api/paypal/ops/tools). */
export function getOpsTools(init: RequestInit = {}): Promise<OpsTools> {
  return apiGet<OpsTools>("/api/paypal/ops/tools", init);
}

/** OpenStall's records for the latest order beside PayPal's, through PayPal's MCP server. */
export function checkWithPayPal(token: string | null = null): Promise<OpsCheck> {
  return apiPost<OpsCheck>("/api/paypal/ops/check", {}, headers(token));
}

/** The ops agent's answer to an operator's question, from PayPal's read tools only. */
export function askOpsAgent(question: string, token: string | null = null): Promise<OpsAnswer> {
  return apiPost<OpsAnswer>("/api/paypal/ops/ask", { question }, headers(token));
}
