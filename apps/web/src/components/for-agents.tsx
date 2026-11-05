import type { ReactNode } from "react";

import { Badge } from "@/components/badge";
import { CopyField } from "@/components/copy-field";
import { catalogEntryUrl, catalogUrl, llmsTxtUrl, mcpUrl, trustCardCheckUrl, trustCardUrl } from "@/lib/agent-urls";
import type { SellerDetail } from "@/lib/catalog";

/**
 * A stall's "For AI agents" box: each of her listings as its catalog entry and her trust card, as the JSON agents read
 * (the same as the MCP tools get_product and get_trust_card give), and the MCP server's address to copy. Every link
 * is on the API's public address. A maker with no trust passport yet has no trust card to link to.
 */
export function ForAgents({ seller }: { seller: SellerDetail }) {
  const linkClass =
    "font-semibold text-accent underline underline-offset-4 hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
  return (
    <section aria-labelledby="agents-heading" className="mt-10 rounded-2xl border border-border bg-surface p-5 sm:p-7">
      <h2 id="agents-heading" className="text-xl font-semibold tracking-tight">
        For AI agents
      </h2>
      <p className="mt-2 text-sm leading-6 text-muted">
        {whatAgentsCanRead(seller)} Reading spends nothing, and no agent tool can move money: a person approves every
        payment.
      </p>

      {seller.products.length > 0 || seller.trust ? (
        <ul className="mt-5 grid gap-3 sm:grid-cols-2">
          {seller.products.map((product) => (
            <AgentLink
              key={product.id}
              kind="Catalog entry"
              title={product.title}
              href={catalogEntryUrl(product.id)}
              linkClass={linkClass}
            >
              This listing as agents read it: the same as the MCP tool get_product.
            </AgentLink>
          ))}
          {seller.trust ? (
            <AgentLink
              kind="Trust card"
              title={`${seller.name}'s passport`}
              href={trustCardUrl(seller.id)}
              linkClass={linkClass}
              badge={<Badge tone="success">Signed</Badge>}
            >
              Her trust record as JSON, the same as get_trust_card, signed by OpenStall with Ed25519.{" "}
              <a href={trustCardCheckUrl(seller.id)} className={linkClass}>
                Check its signature
              </a>
            </AgentLink>
          ) : null}
        </ul>
      ) : null}

      <div className="mt-6">
        <CopyField label="MCP server address" value={mcpUrl()} />
      </div>

      <p className="mt-2 text-sm leading-6 text-muted">
        Agents without MCP can read every listing at{" "}
        <a href={catalogUrl()} className={linkClass}>
          catalog.json
        </a>
        , and a short guide for language models at{" "}
        <a href={llmsTxtUrl()} className={linkClass}>
          llms.txt
        </a>
        .
      </p>
    </section>
  );
}

/**
 * What agents can read of hers, and only that: agents can search and read listings, not order yet (prompt 27). A
 * maker with nothing live and no passport yet (a new WhatsApp maker) has nothing for them.
 */
function whatAgentsCanRead(seller: SellerDetail): string {
  const others = "OpenStall's MCP server and catalog.json have the other makers' listings.";
  if (seller.products.length > 0) {
    return `Buyer agents can read ${seller.name}'s stall as JSON, or search it through OpenStall's MCP server.`;
  }
  if (seller.trust) {
    return `${seller.name} has nothing listed right now, so agents can read only her trust card. ${others}`;
  }
  return `${seller.name} has nothing for agents to read yet: no live listing and no trust card. ${others}`;
}

/** One JSON address: what it is, the link (named with what it is, for screen readers), the address itself, a note. */
function AgentLink({
  kind,
  title,
  href,
  linkClass,
  badge,
  children,
}: {
  kind: string;
  title: string;
  href: string;
  linkClass: string;
  badge?: ReactNode;
  children: ReactNode;
}) {
  return (
    <li className="min-w-0 rounded-xl border border-border bg-background px-4 py-3">
      {/* As tall as the badge, so a card with one and a card without line up side by side. */}
      <div className="flex min-h-6 flex-wrap items-center justify-between gap-2">
        <p aria-hidden="true" className="text-xs font-medium tracking-wide text-muted uppercase">
          {kind}
        </p>
        {badge}
      </div>
      <a href={href} className={`mt-1 inline-block ${linkClass}`}>
        <span className="sr-only">{kind}:</span> {title}
      </a>
      <p className="mt-1 font-mono text-xs break-all text-muted">{href}</p>
      <p className="mt-2 text-sm leading-6 text-muted">{children}</p>
    </li>
  );
}
