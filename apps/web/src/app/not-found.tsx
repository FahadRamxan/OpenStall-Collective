import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Page not found" };

/** Shown for every address with no page, inside the site layout, instead of Next.js's unstyled default. */
export default function NotFound() {
  return (
    <section className="mx-auto max-w-5xl px-4 py-16 sm:px-6 sm:py-24">
      <div className="max-w-2xl">
        <p className="inline-flex rounded-full bg-accent-soft px-3 py-1 text-sm font-medium text-accent">Error 404</p>
        <h1 className="mt-4 text-3xl font-semibold tracking-tight text-balance sm:text-4xl">Page not found</h1>
        <p className="mt-4 text-lg leading-8 text-muted">
          There is no page at this address. Check the link, or start again from the home page.
        </p>
        <Link
          href="/"
          className="mt-8 inline-flex min-h-12 items-center justify-center rounded-full bg-accent px-6 text-base font-semibold text-accent-foreground transition-colors hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Go to the home page
        </Link>
      </div>
    </section>
  );
}
