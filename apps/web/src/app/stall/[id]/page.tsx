import type { Metadata } from "next";
import { Suspense } from "react";

import { StallSkeleton, StallView } from "@/components/stall-view";

export const metadata: Metadata = { title: "Seller stall" };

export default function StallPage() {
  return (
    <section className="mx-auto max-w-5xl px-4 py-10 sm:px-6 sm:py-14">
      {/* StallView reads the stall's id from the URL, which is only known per request. */}
      <Suspense fallback={<StallSkeleton />}>
        <StallView />
      </Suspense>
    </section>
  );
}
