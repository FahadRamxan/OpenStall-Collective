import Link from "next/link";

import { Badge } from "@/components/badge";
import { formatUsd } from "@/lib/catalog";
import { ORDER_STATUS_LABELS, type Order, type OrderPart, type TopUp } from "@/lib/orders";

/** A top-up waits for a person's approval in these statuses. */
const WAITING = new Set(["draft", "awaiting_approval"]);

/** "Noor", "Noor and Priya", "Amina, Noor and Priya". */
function names(list: string[]): string {
  return list.length <= 1 ? (list[0] ?? "") : `${list.slice(0, -1).join(", ")} and ${list.at(-1)}`;
}

/**
 * The order heals itself (prompt 39): each maker who dropped out of this order, and the top-up order that took her
 * units from other makers, which a person approves like any order. On the receipt (`you`) and in /demo's Payments.
 */
export function TopUps({ order, you = false }: { order: Order; you?: boolean }) {
  const dropped = order.parts.filter((part) => part.drop?.state === "dropped");
  const topUps = order.top_ups ?? [];
  const others = topUps.filter((topUp) => !dropped.some((part) => part.drop?.top_up_order_id === topUp.id));
  if (dropped.length === 0 && topUps.length === 0) return null;
  return (
    <section aria-label="The order heals itself" className="mt-5 rounded-xl border border-border bg-background p-4">
      <h3 className="font-semibold">The order heals itself</h3>
      <ul className="mt-2 space-y-3 text-sm leading-6">
        {dropped.map((part) => (
          <li key={part.id}>
            <Dropped part={part} topUp={topUps.find((topUp) => topUp.id === part.drop?.top_up_order_id)} you={you} />
          </li>
        ))}
        {others.map((topUp) => (
          <li key={topUp.id}>
            <TopUpLine topUp={topUp} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function Dropped({ part, topUp, you }: { part: OrderPart; topUp: TopUp | undefined; you: boolean }) {
  return (
    <>
      <p>
        <span className="font-semibold">{part.seller.name}</span> could not make her {part.quantity} units: her{" "}
        {formatUsd(part.amount_usd)} share went back to {you ? "you" : "the buyer"}, never charged.
      </p>
      {topUp ? (
        <TopUpLine topUp={topUp} />
      ) : part.drop?.replan_failed ? (
        <p className="text-muted">No other maker could take them: {part.drop.replan_failed}.</p>
      ) : (
        <p aria-busy="true" className="text-muted">
          OpenStall is asking the other makers&apos; agents for her units…
        </p>
      )}
    </>
  );
}

function TopUpLine({ topUp }: { topUp: TopUp }) {
  const waiting = WAITING.has(topUp.status);
  const needed = topUp.replaces?.quantity ?? topUp.units;
  const share = topUp.units < needed ? `${topUp.units} of the ${needed}` : `all ${topUp.units}`;
  const href = `/approve/${encodeURIComponent(topUp.id)}${waiting ? "" : "/return"}`;
  return (
    <div className="mt-1">
      <p>
        {names(topUp.parts.map((part) => part.seller.name))} can make {share}: top-up order{" "}
        <span className="font-mono">{topUp.id}</span>,{" "}
        <span className="font-semibold tabular-nums">{formatUsd(topUp.total_usd)}</span>.{" "}
        <Badge tone={waiting ? "warning" : "accent"}>{ORDER_STATUS_LABELS[topUp.status]}</Badge>
      </p>
      <Link
        href={href}
        className="mt-2 inline-flex min-h-11 items-center rounded-full bg-accent px-4 text-sm font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        {waiting ? "Approve the top-up" : "Open the top-up's receipt"}
      </Link>
    </div>
  );
}
