import type { Metadata } from "next";

import { AgentSearches } from "@/components/agent-searches";
import { AllocationPanel } from "@/components/allocation-panel";
import { DemoControls } from "@/components/demo-controls";
import { DemoNav } from "@/components/demo-nav";
import { LiveActivity } from "@/components/live-activity";
import { MakerPhones } from "@/components/maker-phones";
import { OfferRules } from "@/components/offer-rules";
import { OrderCard } from "@/components/order-card";
import { OffersGrid } from "@/components/offers-grid";
import { PaymentsPanel } from "@/components/payments-panel";
import { RequestCard } from "@/components/request-card";
import { EventStreamProvider } from "@/hooks/use-event-stream";
import { LatestOrderProvider } from "@/hooks/use-latest-order";

export const metadata: Metadata = { title: "Live demo" };

/**
 * The whole story on one page (spec 3.9: request, offers, validation, allocation, payments, phones), in its order:
 * the buyer agent's request, the offer rules and each seller agent's checked offer, the split, the order and its one
 * PayPal approval, each maker's payment on proof, and the makers' own phones. The live feed sits beside it on a wide
 * screen and after it on a phone.
 */
export default function DemoPage() {
  return (
    <section className="mx-auto max-w-7xl px-4 py-12 sm:px-6 sm:py-16">
      <div className="max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">Live demo</h1>
        <p className="mt-4 text-lg leading-8 text-muted">
          Watch one order happen live: a buyer agent&apos;s request, each seller agent&apos;s offer and how it is
          checked, the split across sellers, one PayPal approval, and each maker paid the moment she ships.
        </p>
      </div>
      <DemoNav />
      {/* Every live panel shares one event stream (one connection to the API) and one copy of the latest order. */}
      <EventStreamProvider>
        <LatestOrderProvider>
          {/* Two columns only where the story keeps the width its tables were made for (48rem and more). */}
          <div className="xl:grid xl:grid-cols-[minmax(0,1fr)_22rem] xl:items-start xl:gap-10">
            <div className="max-w-3xl min-w-0 xl:max-w-none">
              <DemoControls />
              <RequestCard />
              <OfferRules />
              <AgentSearches />
              <OffersGrid />
              <AllocationPanel />
              <OrderCard />
              <PaymentsPanel />
              <MakerPhones />
            </div>
            <aside aria-label="The live feed" className="max-w-3xl min-w-0 xl:sticky xl:top-4 xl:max-w-none">
              <LiveActivity scroll />
            </aside>
          </div>
        </LatestOrderProvider>
      </EventStreamProvider>
    </section>
  );
}
