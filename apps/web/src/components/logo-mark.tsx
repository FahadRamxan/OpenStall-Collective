/** The OpenStall mark: a market stall with a warm, scalloped awning. Our own drawing, no third-party art. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" focusable="false" className={className}>
      <rect width="32" height="32" rx="9" className="fill-accent" />
      <path
        d="M6 8h20v4a3.33 3.33 0 0 1-6.67 0 3.33 3.33 0 0 1-6.66 0A3.33 3.33 0 0 1 6 12z"
        className="fill-warm"
      />
      <path d="M12.67 8h6.66v4a3.33 3.33 0 0 1-6.66 0z" className="fill-accent-foreground" />
      <path
        d="M8.5 16.5V25h15v-8.5M8.5 20.5h15"
        fill="none"
        strokeWidth="2"
        strokeLinejoin="round"
        className="stroke-accent-foreground"
      />
    </svg>
  );
}
