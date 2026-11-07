import type { Metadata } from "next";

import { DashboardView } from "@/components/dashboard-view";
import { PayPalOpsPanel } from "@/components/paypal-ops-panel";
import { EventStreamProvider } from "@/hooks/use-event-stream";

export const metadata: Metadata = { title: "Dashboard" };

/**
 * The dashboard (spec 3.9): AG Grid tables of orders, payouts, tracking, trust passports and Demand Radar, which follow
 * the live feed.
 */
export default function DashboardPage() {
  return (
    <section className="mx-auto max-w-7xl px-4 py-12 sm:px-6 sm:py-16">
      <div className="max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">Dashboard</h1>
        <p className="mt-4 text-lg leading-8 text-muted">
          Every order, each maker&apos;s payout and tracking, the trust passports, and what buyers&apos; agents searched
          for and could not find, as it happens.
        </p>
      </div>
      <EventStreamProvider>
        <DashboardView />
        <PayPalOpsPanel />
      </EventStreamProvider>
    </section>
  );
}
