import type { Metadata } from "next";
import { Suspense } from "react";

import { ReturnView } from "@/components/return-view";

export const metadata: Metadata = { title: "Approved at PayPal" };

export default function ReturnPage() {
  return (
    <section className="mx-auto max-w-5xl px-4 py-10 sm:px-6 sm:py-14">
      {/* ReturnView reads the order id from the URL, which is only known per request. */}
      <Suspense fallback={null}>
        <ReturnView />
      </Suspense>
    </section>
  );
}
