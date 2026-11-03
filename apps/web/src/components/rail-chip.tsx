import { Badge, type BadgeTone } from "@/components/badge";
import type { OrderPart } from "@/lib/orders";

/**
 * How a maker is paid once her share is captured (spec 3.5a): "Paid to PayPal (simulated)", "Paid to Venmo
 * (simulated)", or "Payout rail not connected yet (Pakistan)". The words come from the API, which knows the mode.
 * A tick shows once PayPal confirmed her payout; in fake mode it says the confirmation is simulated.
 */
export function RailChip({ part }: { part: OrderPart }) {
  const simulated = part.confirmation_source === "simulated";
  const tone: BadgeTone =
    part.payout_rail === "unavailable" ? "warning" : part.payout_confirmed ? "success" : "neutral";
  return (
    <span data-rail={part.payout_rail} className="inline-flex max-w-full">
      <Badge tone={tone} wrap>
        <span>{part.payout_label}</span>
        {part.payout_confirmed ? (
          <>
            <svg
              aria-hidden="true"
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              className="size-3.5 shrink-0"
            >
              <path d="M4.5 10.5l3.5 3.5 7.5-8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="sr-only">
              {simulated ? ", payout confirmed by simulated PayPal" : ", payout confirmed by PayPal"}
            </span>
          </>
        ) : null}
      </Badge>
    </span>
  );
}
