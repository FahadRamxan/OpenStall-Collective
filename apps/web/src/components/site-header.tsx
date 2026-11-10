import Link from "next/link";
import { Suspense } from "react";

import { LogoMark } from "@/components/logo-mark";
import { NavLinks, SiteNav } from "@/components/site-nav";

export function SiteHeader() {
  return (
    // Pinned on wider screens, frosted so the page shows through as it scrolls; on phones it scrolls away.
    <header className="z-40 border-b border-border/70 bg-surface/85 backdrop-blur-md backdrop-saturate-150 sm:sticky sm:top-0">
      <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-6 sm:px-6">
        <Link
          href="/"
          className="group inline-flex items-center gap-2 self-start rounded-md text-lg font-semibold tracking-tight focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:self-auto"
        >
          <LogoMark className="size-8 shrink-0 transition-transform duration-300 group-hover:-rotate-6 group-hover:scale-105" />
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
