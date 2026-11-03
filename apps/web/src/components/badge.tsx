import type { ReactNode } from "react";

export type BadgeTone = "accent" | "success" | "warning" | "danger" | "neutral";

const TONES: Record<BadgeTone, { background: string; text: string }> = {
  accent: { background: "bg-accent-soft", text: "text-accent" },
  success: { background: "bg-success-soft", text: "text-success" },
  warning: { background: "bg-warning-soft", text: "text-warning" },
  danger: { background: "bg-danger-soft", text: "text-danger" },
  neutral: { background: "bg-border", text: "text-muted" },
};

const SIZE_CLASSES = {
  sm: { badge: "gap-1.5 px-2.5 py-0.5 text-xs", dot: "size-1.5" },
  lg: { badge: "gap-2 px-3 py-1 text-base", dot: "size-2" },
};

/**
 * A small coloured label. The words carry the meaning; the colour only repeats it. `wrap` lets a long label break
 * over lines instead of running off a phone screen. `outline` draws it as a ring on the surface colour, for a badge
 * on a background tinted in its own tone, where the soft fill would not show.
 */
export function Badge({
  tone,
  size = "sm",
  wrap = false,
  outline = false,
  children,
}: {
  tone: BadgeTone;
  size?: "sm" | "lg";
  wrap?: boolean;
  outline?: boolean;
  children: ReactNode;
}) {
  const sizes = SIZE_CLASSES[size];
  const shape = wrap ? "max-w-full rounded-2xl text-left" : "whitespace-nowrap rounded-full";
  const { background, text } = TONES[tone];
  const fill = outline ? "bg-surface ring-1 ring-current ring-inset" : background;
  return (
    <span className={`inline-flex items-center font-semibold ${shape} ${sizes.badge} ${fill} ${text}`}>
      <span aria-hidden="true" className={`shrink-0 rounded-full bg-current ${sizes.dot}`} />
      {children}
    </span>
  );
}
