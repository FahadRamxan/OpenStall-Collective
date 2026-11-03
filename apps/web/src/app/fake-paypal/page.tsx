import type { Metadata } from "next";
import { Suspense } from "react";

import { FakePayPalView } from "@/components/fake-paypal-view";

export const metadata: Metadata = { title: "Simulated PayPal (test mode)" };

export default function FakePayPalPage() {
  return (
    <section className="px-4 py-10 sm:px-6 sm:py-14">
      {/* The checkout token is in the query string, which is only known per request. */}
      <Suspense fallback={null}>
        <FakePayPalView />
      </Suspense>
    </section>
  );
}
