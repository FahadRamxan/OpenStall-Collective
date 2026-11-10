"use client";

import { useSyncExternalStore } from "react";

const PIECES = 42;
const COLORS = ["var(--accent)", "var(--warm)", "var(--sun)", "var(--series-1)", "var(--series-5)", "var(--series-3)"];
const REDUCED = "(prefers-reduced-motion: reduce)";

function subscribe(onChange: () => void) {
  if (typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(REDUCED);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

/** Whether to celebrate: never on the server (the first render must match it), never for someone who asks for less
 * motion, nor where the browser cannot say (a test's stand-in page). */
function useCelebrate(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => typeof window.matchMedia === "function" && !window.matchMedia(REDUCED).matches,
    () => false,
  );
}

/** A repeatable "random" number in [0, 1) for piece `index`, so rendering stays pure. */
function noise(index: number, salt: number): number {
  const value = Math.sin(index * 12.9898 + salt * 78.233) * 43758.5453;
  return value - Math.floor(value);
}

/**
 * A short burst of confetti from the top of the screen, for a moment worth celebrating: PayPal holding the money, an
 * order complete. It plays once when it appears, never takes a click, and is hidden from screen readers.
 */
export function Confetti() {
  const celebrate = useCelebrate();
  if (!celebrate) return null;
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-50 overflow-hidden">
      {Array.from({ length: PIECES }, (_, index) => {
        const angle = (noise(index, 1) - 0.5) * Math.PI * 1.1;
        const distance = 220 + noise(index, 2) * 420;
        const size = 6 + Math.round(noise(index, 3) * 6);
        return (
          <span
            key={index}
            className="absolute left-1/2 top-[22%]"
            style={
              {
                width: size,
                height: noise(index, 4) > 0.5 ? size : size * 0.45,
                borderRadius: noise(index, 5) > 0.6 ? 9999 : 2,
                background: COLORS[index % COLORS.length],
                "--dx": `${Math.sin(angle) * distance}px`,
                "--dy": `${Math.cos(angle) * distance * 0.8 + 140}px`,
                "--spin": `${Math.round((noise(index, 6) - 0.5) * 1080)}deg`,
                animation: `confetti-fall ${1.1 + noise(index, 7) * 0.9}s cubic-bezier(0.15, 0.6, 0.35, 1) ${Math.round(noise(index, 8) * 160)}ms both`,
              } as React.CSSProperties
            }
          />
        );
      })}
    </div>
  );
}
