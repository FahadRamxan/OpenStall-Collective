"use client";

import { useState } from "react";

import type { Plan } from "@/lib/plans";
import { shareWords } from "@/lib/plans";

/** The categorical slots, in fixed order (globals.css, validated in light and dark). Five makers at most per plan. */
const SLOTS = 5;

type Segment = { key: string; label: string; units: number; color: string | null };

/**
 * One horizontal bar: each maker's share of the requested quantity, in the plan's order (cheapest first), and a
 * hatched "Short" segment when the plan cannot fill it. The legend under it names each share with its units, so no
 * share is told by colour alone; the table below it has every number. Hovering or focusing a share shows it.
 */
export function ShareBar({ plan }: { plan: Plan }) {
  const [active, setActive] = useState<number | null>(null);
  const of = plan.requested_quantity;
  const segments: Segment[] = plan.lines.map((line, index) => ({
    key: line.seller_id,
    label: line.seller_name,
    units: line.quantity,
    color: `var(--series-${(index % SLOTS) + 1})`,
  }));
  if (plan.shortfall > 0) segments.push({ key: "short", label: "Short", units: plan.shortfall, color: null });
  const shown = active === null ? null : segments[active];

  return (
    <figure className="mt-5">
      <div className="relative">
        <ul aria-label={`Each maker's share of the ${of}`} className="flex h-6 w-full gap-0.5">
          {segments.map((segment, index) => (
            <li
              key={segment.key}
              tabIndex={0}
              onPointerEnter={() => setActive(index)}
              onPointerLeave={() => setActive((current) => (current === index ? null : current))}
              onFocus={() => setActive(index)}
              onBlur={() => setActive((current) => (current === index ? null : current))}
              className={`h-full min-w-1 outline-offset-2 focus-visible:outline-2 focus-visible:outline-accent ${
                index === segments.length - 1 ? "rounded-r" : ""
              } ${active !== null && active !== index ? "opacity-60" : ""}`}
              style={{
                flex: `${segment.units} 1 0`,
                background:
                  segment.color ??
                  "repeating-linear-gradient(45deg, var(--muted) 0 1.5px, transparent 1.5px 6px), var(--surface)",
              }}
            >
              <span className="sr-only">
                {segment.label}: {segment.units} {segment.units === 1 ? "unit" : "units"}
              </span>
            </li>
          ))}
        </ul>
        {shown ? (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute bottom-full left-0 mb-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm shadow-sm"
          >
            <strong className="font-semibold tabular-nums">
              {shown.units} {shown.units === 1 ? "unit" : "units"}
            </strong>{" "}
            <span className="text-muted">
              {shown.label} · {shareWords(shown.units, of)} of {of}
            </span>
          </div>
        ) : null}
      </div>
      <figcaption aria-hidden="true">
        <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm">
          {segments.map((segment) => (
            <li key={segment.key} className="inline-flex items-center gap-1.5">
              <span
                className="inline-block size-2.5 rounded-sm"
                style={{
                  background:
                    segment.color ??
                    "repeating-linear-gradient(45deg, var(--muted) 0 1px, transparent 1px 3px), var(--surface)",
                }}
              />
              <span>{segment.label}</span>
              <span className="text-muted tabular-nums">{segment.units}</span>
            </li>
          ))}
        </ul>
      </figcaption>
    </figure>
  );
}
