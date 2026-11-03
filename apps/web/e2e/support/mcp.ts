import { expect, type APIRequestContext } from "@playwright/test";

import { E2E_API_URL } from "../../playwright.config";

/**
 * A small MCP client for UI tests: it calls the e2e API's storefront at /mcp as a buyer agent's MCP client does,
 * with JSON-RPC over Streamable HTTP. The storefront is stateless with JSON responses (storefront.py), so each
 * request stands on its own: no session id, and the answer is plain JSON rather than an event stream.
 */

/** The newest MCP version that is reached through the initialize handshake, which is what most clients use. */
const PROTOCOL_VERSION = "2025-11-25";

/** One search_products result: the parts the UI tests read. */
export type FoundProduct = {
  product_id: string;
  seller_id: string;
  seller_name: string;
  title: string;
  price_usd: number;
  data_source: string;
  trust: { score: number; summary: string; data_source: string } | null;
  capacity_by_deadline: number;
  deadline: string;
};

/** What search_products takes besides the query. */
export type SearchFilters = { max_price?: number; quantity?: number; deadline?: string; ship_to?: string };

type ToolResult = { isError?: boolean; content: unknown[]; structuredContent?: { result: unknown } };

let nextId = 1;

async function rpc(request: APIRequestContext, method: string, params: object, handshake = false): Promise<unknown> {
  const headers: Record<string, string> = { Accept: "application/json, text/event-stream" };
  // After the handshake a client names the version it agreed on; the handshake itself carries it in the body.
  if (!handshake) headers["MCP-Protocol-Version"] = PROTOCOL_VERSION;
  const response = await request.post(`${E2E_API_URL}/mcp`, {
    headers,
    data: { jsonrpc: "2.0", id: nextId++, method, params },
  });
  expect(response.status(), `${method} over MCP`).toBe(200);
  const body = (await response.json()) as { result?: unknown; error?: unknown };
  expect(body.error, `${method} over MCP`).toBeUndefined();
  return body.result;
}

/** Connects as a buyer agent's MCP client does, then lists the storefront's tools. Returns their names. */
export async function connect(request: APIRequestContext): Promise<string[]> {
  const hello = (await rpc(
    request,
    "initialize",
    { protocolVersion: PROTOCOL_VERSION, capabilities: {}, clientInfo: { name: "openstall-e2e", version: "1" } },
    true,
  )) as { serverInfo: { name: string } };
  expect(hello.serverInfo.name).toBe("OpenStall Collective");
  const listed = (await rpc(request, "tools/list", {})) as { tools: { name: string }[] };
  return listed.tools.map((tool) => tool.name);
}

/** Calls search_products through the MCP endpoint and returns what it found. */
export async function searchProducts(
  request: APIRequestContext,
  query: string,
  filters: SearchFilters = {},
): Promise<FoundProduct[]> {
  const result = (await rpc(request, "tools/call", {
    name: "search_products",
    arguments: { query, ...filters },
  })) as ToolResult;
  expect(result.isError, JSON.stringify(result.content)).toBeFalsy();
  return result.structuredContent?.result as FoundProduct[];
}
