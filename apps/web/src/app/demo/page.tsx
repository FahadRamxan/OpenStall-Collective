import type { Metadata } from "next";

import { LiveActivity } from "@/components/live-activity";

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
        <LiveActivity />
      </div>
    </section>
  );
}
