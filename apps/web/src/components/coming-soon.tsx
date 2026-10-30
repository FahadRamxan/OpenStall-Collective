import type { ReactNode } from "react";

/** Placeholder for a page that a later build step fills in. */
export function ComingSoon({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mx-auto max-w-5xl px-4 py-16 sm:px-6 sm:py-24">
      <div className="max-w-2xl">
        <p className="inline-flex rounded-full bg-accent-soft px-3 py-1 text-sm font-medium text-accent">
          Coming soon
        </p>
        <h1 className="mt-4 text-3xl font-semibold tracking-tight text-balance sm:text-4xl">{title}</h1>
        <p className="mt-4 text-lg leading-8 text-muted">{children}</p>
      </div>
    </section>
  );
}
