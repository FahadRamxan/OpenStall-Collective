"use client";

import { useEffect, useState } from "react";

/** The panels of /demo in the story's order, by their headings' ids. */
export const STORY_SECTIONS: [string, string][] = [
  ["controls-heading", "Run the story"],
  ["request-heading", "Request"],
  ["rules-heading", "Offer rules"],
  ["offers-heading", "Offers"],
  ["allocation-heading", "Split"],
  ["order-heading", "Order"],
  ["payments-heading", "Payments"],
  ["phones-heading", "Makers' phones"],
  ["tamper-heading", "Trust passports"],
  ["guardrails-heading", "Try to break it"],
  ["activity-heading", "Live activity"],
];

/** The step being read: the first panel whose heading is in the top half of the screen, below the pinned bars. */
function useCurrentStep(): string | null {
  const [current, setCurrent] = useState<string | null>(null);
  useEffect(() => {
    if (!("IntersectionObserver" in window)) return;
    const headings = STORY_SECTIONS.map(([id]) => document.getElementById(id)).filter(
      (heading): heading is HTMLElement => heading !== null,
    );
    const inView = new Map<string, boolean>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) inView.set(entry.target.id, entry.isIntersecting);
        const first = STORY_SECTIONS.find(([id]) => inView.get(id));
        if (first) setCurrent(first[0]);
      },
      { rootMargin: "-120px 0px -50% 0px" },
    );
    for (const heading of headings) observer.observe(heading);
    return () => observer.disconnect();
  }, []);
  return current;
}

/**
 * The story on /demo, as links to each panel, so a judge can jump to any step. Pinned under the header on wider
 * screens, with the step being read marked as it scrolls by.
 */
export function DemoNav() {
  const current = useCurrentStep();
  return (
    <nav
      aria-label="The story on this page"
      className="z-30 -mx-4 mt-6 border-b border-border/70 bg-background/85 px-4 py-2.5 backdrop-blur-md sm:sticky sm:top-[57px] sm:-mx-6 sm:px-6"
    >
      <ol className="flex gap-2 overflow-x-auto text-sm [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {STORY_SECTIONS.map(([id, name], index) => {
          const here = current === id;
          return (
            <li key={id} className="shrink-0">
              <a
                href={`#${id}`}
                aria-current={here ? "location" : undefined}
                className={`inline-flex min-h-9 items-center gap-1.5 rounded-full border px-3 transition-all duration-300 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                  here
                    ? "border-accent bg-accent-soft font-semibold text-accent"
                    : "border-border bg-surface hover:border-accent/50 hover:bg-background"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`grid size-5 place-items-center rounded-full text-xs tabular-nums transition-colors ${
                    here ? "bg-accent text-accent-foreground" : "bg-background text-muted"
                  }`}
                >
                  {index + 1}
                </span>
                {name}
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
