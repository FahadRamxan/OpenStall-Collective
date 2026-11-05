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

/** The story on /demo, as links to each panel, so a judge can jump to any step. */
export function DemoNav() {
  return (
    <nav aria-label="The story on this page" className="mt-6">
      <ol className="flex flex-wrap gap-2 text-sm">
        {STORY_SECTIONS.map(([id, name], index) => (
          <li key={id}>
            <a
              href={`#${id}`}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-full border border-border bg-surface px-3 hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              <span aria-hidden="true" className="text-xs text-muted tabular-nums">
                {index + 1}
              </span>
              {name}
            </a>
          </li>
        ))}
      </ol>
    </nav>
  );
}
