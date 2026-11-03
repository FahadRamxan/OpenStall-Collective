import type { ReactNode } from "react";

export type BadgeTone = "accent" | "success" | "warning" | "danger" | "neutral";

const TONE_CLASSES: Record<BadgeTone, string> = {
  accent: "bg-accent-soft text-accent",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  neutral: "bg-border text-muted",
};

const SIZE_CLASSES = {
  sm: { badge: "gap-1.5 px-2.5 py-0.5 text-xs", dot: "size-1.5" },
  lg: { badge: "gap-2 px-3 py-1 text-base", dot: "size-2" },
};

/**
 * A small coloured label. The words carry the meaning; the colour only repeats it. `wrap` lets a long label break
 * over lines instead of running off a phone screen.
 */
export function Badge({
  tone,
  size = "sm",
  wrap = false,
  children,
}: {
  tone: BadgeTone;
  size?: "sm" | "lg";
  wrap?: boolean;
  children: ReactNode;
}) {
  const sizes = SIZE_CLASSES[size];
  const shape = wrap ? "max-w-full rounded-2xl text-left" : "whitespace-nowrap rounded-full";
  return (
    <span className={`inline-flex items-center font-semibold ${shape} ${sizes.badge} ${TONE_CLASSES[tone]}`}>
      <span aria-hidden="true" className={`shrink-0 rounded-full bg-current ${sizes.dot}`} />
      {children}
    </span>
  );
}
