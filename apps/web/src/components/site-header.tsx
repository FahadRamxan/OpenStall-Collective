import Link from "next/link";
import { Suspense } from "react";

import { LogoMark } from "@/components/logo-mark";
import { NavLinks, SiteNav } from "@/components/site-nav";

export function SiteHeader() {
  return (
    <header className="border-b border-border bg-surface">
      <div className="mx-auto flex max-w-5xl flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-6 sm:px-6">
        <Link
          href="/"
          className="inline-flex items-center gap-2 self-start rounded-md text-lg font-semibold tracking-tight focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:self-auto"
        >
          <LogoMark className="size-7 shrink-0" />
          <span>
            OpenStall <span className="font-normal text-muted">Collective</span>
          </span>
        </Link>
        {/* With Cache Components, usePathname() suspends on pages whose dynamic params are only known
            at request time, so the fallback shows the same links without the current-page mark. */}
        <Suspense fallback={<NavLinks currentPath={null} />}>
          <SiteNav />
        </Suspense>
      </div>
    </header>
  );
}
