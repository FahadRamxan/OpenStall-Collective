import { AgentIcon, ChatIcon, CheckIcon, WalletIcon } from "@/components/icons";

const MAKERS = [
  { initial: "A", color: "bg-[#c2410c]" },
  { initial: "P", color: "bg-[#1d4ed8]" },
  { initial: "L", color: "bg-[#047857]" },
  { initial: "G", color: "bg-[#7c3aed]" },
];

/**
 * The home page's picture of the story, in three floating cards: a maker's voice note on WhatsApp, a buyer's AI agent
 * asking for a quote, and PayPal holding the money until each maker ships. A drawing of the flow, not live data, so
 * it is hidden from screen readers (the page's text tells the same story).
 */
export function HeroScene() {
  return (
    <div aria-hidden="true" className="relative mx-auto w-full max-w-md select-none lg:max-w-none">
      <div className="absolute -inset-8 -z-10 rounded-[3rem] bg-[radial-gradient(closest-side,var(--glow),transparent)]" />

      {/* The maker, on WhatsApp. */}
      <div className="animate-float relative rounded-2xl border border-border bg-surface p-4 shadow-md">
        <div className="flex items-center gap-2.5">
          <span className="grid size-9 place-items-center rounded-full bg-[#c2410c] text-sm font-semibold text-white">A</span>
          <div className="min-w-0">
            <p className="text-sm font-semibold">Amina · Lahore</p>
            <p className="flex items-center gap-1 text-xs text-muted">
              <ChatIcon className="size-3.5" /> WhatsApp voice note, in Urdu
            </p>
          </div>
        </div>
        <div className="mt-3 rounded-2xl rounded-tl-sm bg-accent-soft px-3 py-2">
          <div className="flex h-6 items-end gap-[3px]">
            {[8, 14, 20, 11, 22, 16, 9, 18, 24, 12, 7, 15, 21, 10, 17, 13, 8, 19].map((height, index) => (
              <span key={index} className="w-1 rounded-full bg-accent/70" style={{ height }} />
            ))}
          </div>
          <p dir="rtl" lang="ur" className="mt-1.5 text-sm">
            میں ہاتھ سے کشن کور بناتی ہوں، 18 ڈالر کا ایک
          </p>
          <p className="mt-1 border-t border-accent/20 pt-1 text-xs text-muted">
            In English: I hand-embroider cushion covers, $18 each
          </p>
        </div>
      </div>

      {/* The buyer's AI agent. */}
      <div className="animate-float-slow relative z-10 -mt-3 ml-8 rounded-2xl border border-border bg-surface p-4 shadow-md [animation-delay:-3s] sm:ml-16">
        <p className="flex items-center gap-2 text-sm font-semibold">
          <span className="grid size-8 place-items-center rounded-lg bg-[#1d4ed8]/10 text-[#1d4ed8] dark:text-[#93b4ff]">
            <AgentIcon className="size-4.5" />
          </span>
          A buyer&apos;s AI agent
        </p>
        <p className="mt-2 rounded-lg bg-background px-3 py-2 font-mono text-xs leading-5">
          request_quote(<span className="text-accent">40</span> cushion covers, at most{" "}
          <span className="text-accent">$30</span>)
        </p>
        <p className="mt-2 flex items-center gap-1.5 text-xs text-muted">
          <span className="flex gap-0.5">
            <span className="size-1.5 animate-bounce rounded-full bg-muted" />
            <span className="size-1.5 animate-bounce rounded-full bg-muted [animation-delay:0.15s]" />
            <span className="size-1.5 animate-bounce rounded-full bg-muted [animation-delay:0.3s]" />
          </span>
          5 makers&apos; agents are offering
        </p>
      </div>

      {/* PayPal, holding the money. */}
      <div className="animate-float relative -mt-3 mr-6 rounded-2xl border border-border bg-surface p-4 shadow-md [animation-delay:-5s]">
        <div className="flex items-center justify-between gap-3">
          <p className="flex items-center gap-2 text-sm font-semibold">
            <span className="grid size-8 place-items-center rounded-lg bg-accent-soft text-accent">
              <WalletIcon className="size-4.5" />
            </span>
            PayPal is holding $815.00
          </p>
          <div className="flex -space-x-2">
            {MAKERS.map(({ initial, color }) => (
              <span
                key={initial}
                className={`grid size-7 place-items-center rounded-full border-2 border-surface text-xs font-semibold text-white ${color}`}
              >
                {initial}
              </span>
            ))}
          </div>
        </div>
        <div className="mt-3 flex h-2 overflow-hidden rounded-full bg-background">
          <span className="w-[29%] bg-[var(--series-1)]" />
          <span className="w-[27%] bg-[var(--series-2)]" />
          <span className="w-[27%] bg-[var(--series-3)]" />
          <span className="w-[17%] bg-[var(--series-4)]" />
        </div>
        <p className="mt-2.5 flex items-center gap-1.5 text-xs font-medium text-success">
          <CheckIcon className="size-4" /> Each maker paid the moment she ships
        </p>
      </div>
    </div>
  );
}
