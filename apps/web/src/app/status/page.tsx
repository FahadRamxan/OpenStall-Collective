import type { Metadata } from "next";

import { StatusPanel } from "@/components/status-panel";

export const metadata: Metadata = { title: "System status" };

export default function StatusPage() {
  return (
    <section className="mx-auto max-w-5xl px-4 py-12 sm:px-6 sm:py-16">
      <div className="max-w-3xl">
        <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">System status</h1>
        <p className="mt-4 text-lg leading-8 text-muted">
          How the OpenStall API is running right now: on stand-ins or on the real sandboxes, and which outside
          services are ready to use.
        </p>
        <StatusPanel />
      </div>
    </section>
  );
}
