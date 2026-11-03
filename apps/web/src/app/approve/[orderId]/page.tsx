import type { Metadata } from "next";
import { Suspense } from "react";

import { ApprovalSkeleton, ApprovalView } from "@/components/approval-view";

export const metadata: Metadata = { title: "Approve your order" };

export default function ApprovePage() {
  return (
    <section className="mx-auto max-w-5xl px-4 py-10 sm:px-6 sm:py-14">
      {/* ApprovalView reads the order id from the URL, which is only known per request. */}
      <Suspense fallback={<ApprovalSkeleton />}>
        <ApprovalView />
      </Suspense>
    </section>
  );
}
