import { apiBaseUrl } from "@/lib/api";

/*
 * Where AI agents find OpenStall, all on the API's public address (NEXT_PUBLIC_API_BASE_URL): the MCP storefront, and
 * for agents without MCP the catalog feed, one listing's entry in it, a maker's trust card and llms.txt.
 */

/** The MCP storefront (Streamable HTTP), the address an agent's MCP client connects to. */
export function mcpUrl(): string {
  return `${apiBaseUrl()}/mcp`;
}

/** Every live listing as JSON. */
export function catalogUrl(): string {
  return `${apiBaseUrl()}/catalog.json`;
}

/** One listing's catalog entry: what the MCP tool get_product gives. */
export function catalogEntryUrl(productId: string): string {
  return `${apiBaseUrl()}/catalog/${encodeURIComponent(productId)}.json`;
}

/** A maker's trust card, her passport as JSON: what the MCP tool get_trust_card gives. */
export function trustCardUrl(sellerId: string): string {
  return `${apiBaseUrl()}/passport/${encodeURIComponent(sellerId)}`;
}

/** A short plain-text guide to OpenStall for language models. */
export function llmsTxtUrl(): string {
  return `${apiBaseUrl()}/llms.txt`;
}
