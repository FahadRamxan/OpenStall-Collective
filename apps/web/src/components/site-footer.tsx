import Link from "next/link";

import { ApiStatus } from "@/components/api-status";

export function SiteFooter() {
  return (
    <footer className="border-t border-border bg-surface/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-6 text-sm text-muted sm:flex-row sm:items-start sm:justify-between sm:gap-6 sm:px-6">
        <p className="font-medium text-foreground">No real money moves: PayPal&apos;s sandbox, or simulated PayPal in test mode.</p>
        <div className="flex flex-wrap items-start gap-x-5 gap-y-2">
          <ApiStatus />
          {/* The padding gives a 44px touch target; the negative margin keeps the line its normal height. */}
          <Link
            href="/status"
            className="-my-3 inline-flex items-center rounded-sm py-3 font-medium text-accent underline underline-offset-4 hover:text-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            System status
          </Link>
        </div>
      </div>
    </footer>
  );
}
