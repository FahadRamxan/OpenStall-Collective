import type { Metadata } from "next";

import { AgentSearches } from "@/components/agent-searches";
import { AllocationPanel } from "@/components/allocation-panel";
import { DemoControls } from "@/components/demo-controls";
import { LiveActivity } from "@/components/live-activity";
import { OfferRules } from "@/components/offer-rules";
import { OrderCard } from "@/components/order-card";
import { OffersGrid } from "@/components/offers-grid";
import { RequestCard } from "@/components/request-card";
import { EventStreamProvider } from "@/hooks/use-event-stream";

export const metadata: Metadata = { title: "Live demo" };

export default function DemoPage() {
  return (
    <section className="mx-auto max-w-5xl px-4 py-12 sm:px-6 sm:py-16">
      <div className="max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">Live demo</h1>
        <p className="mt-4 text-lg leading-8 text-muted">
          Watch one order happen live: a buyer agent&apos;s request, each seller agent&apos;s offer and how it is
          checked, the split across sellers, one PayPal approval, and each maker paid the moment she ships.
        </p>
        {/* Every live panel shares one event stream: one connection to the API, however many panels there are. */}
        <EventStreamProvider>
          <DemoControls />
          <RequestCard />
          <OfferRules />
          <AgentSearches />
          <OffersGrid />
          <AllocationPanel />
          <OrderCard />
          <LiveActivity />
        </EventStreamProvider>
      </div>
    </section>
  );
}
