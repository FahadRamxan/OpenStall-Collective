"use client";

import { useEffect, useId, useRef, useState } from "react";

/** How long "Copied" stays on screen. */
export const COPIED_SHOWN_MS = 4_000;

type Copy = { state: "idle" } | { state: "copied" | "blocked"; attempt: number };

/**
 * A value to copy, such as the MCP server's address, with a Copy button. The Clipboard API copies it, and a visible
 * status says "Copied", which screen readers hear too. Where the browser will not copy (no Clipboard API outside a
 * secure page, or permission refused), the value is selected instead and the status says how to copy it.
 */
export function CopyField({ label, value }: { label: string; value: string }) {
  const id = useId();
  const valueRef = useRef<HTMLElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [copy, setCopy] = useState<Copy>({ state: "idle" });

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  async function copyValue() {
    let copied = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
        copied = true;
      }
    } catch {
      // Refused: fall back to selecting it below.
    }
    if (timer.current) clearTimeout(timer.current);
    if (copied) {
      timer.current = setTimeout(() => setCopy({ state: "idle" }), COPIED_SHOWN_MS);
    } else if (valueRef.current) {
      window.getSelection()?.selectAllChildren(valueRef.current);
    }
    setCopy((previous) => ({
      state: copied ? "copied" : "blocked",
      attempt: previous.state === "idle" ? 1 : previous.attempt + 1,
    }));
  }

  return (
    <div role="group" aria-labelledby={`${id}-label`}>
      <p id={`${id}-label`} className="text-sm font-semibold">
        {label}
      </p>
      {/* On a phone the button goes under the value, so a long address keeps the full width. */}
      <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
        <code
          ref={valueRef}
          className="block min-w-0 rounded-lg border border-border bg-background px-3 py-2.5 font-mono text-sm break-all sm:flex-1"
        >
          {value}
        </code>
        <button
          type="button"
          onClick={copyValue}
          aria-label={`Copy the ${label}`}
          className="inline-flex min-h-11 shrink-0 items-center self-start rounded-full bg-accent px-5 text-sm font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent sm:self-auto"
        >
          Copy
        </button>
      </div>
      {/* Always in the page, so screen readers hear each change. A new key reads "Copied" out again on a second copy. */}
      <p role="status" className="mt-2 min-h-5 text-sm font-medium">
        {copy.state === "copied" ? (
          <span key={copy.attempt} className="inline-flex items-center gap-1.5 text-success">
            <svg
              aria-hidden="true"
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              className="size-4 shrink-0"
            >
              <path d="M4.5 10.5l3.5 3.5 7.5-8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Copied
          </span>
        ) : copy.state === "blocked" ? (
          <span key={copy.attempt} className="text-warning">
            This browser did not let the page copy, so the text is selected: press Ctrl+C (⌘C on a Mac) to copy it, or
            on a phone, press and hold it, then choose Copy.
          </span>
        ) : null}
      </p>
    </div>
  );
}
