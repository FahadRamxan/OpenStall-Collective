"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_LINKS = [
  { href: "/", label: "Home" },
  { href: "/demo", label: "Demo" },
  { href: "/seller-chat", label: "Seller chat" },
  { href: "/dashboard", label: "Dashboard" },
] as const;

/** A section counts as current on its own path and on every page below it, except Home. */
export function isCurrentPath(href: string, pathname: string | null): boolean {
  if (!pathname) return false;
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** The main navigation. `currentPath` is null while the current page is not known yet. */
export function NavLinks({ currentPath }: { currentPath: string | null }) {
  return (
    <nav aria-label="Main">
      {/* On phones: 44px-tall touch targets, packed tighter so all four still fit on one row at 320px. */}
      <ul className="flex flex-wrap items-center sm:gap-1">
        {NAV_LINKS.map(({ href, label }) => {
          const current = isCurrentPath(href, currentPath);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={current ? "page" : undefined}
                className={`inline-flex min-h-11 items-center rounded-full px-2 py-2 text-sm font-medium transition-all duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:min-h-0 sm:px-3.5 ${
                  current
                    ? "bg-accent-soft text-accent shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--accent)_25%,transparent)]"
                    : "text-muted hover:bg-border/60 hover:text-foreground"
                }`}
              >
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** The main navigation with the current page marked. */
export function SiteNav() {
  return <NavLinks currentPath={usePathname()} />;
}
