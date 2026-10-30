import Link from "next/link";

// The people in the system (spec section 1).
const AUDIENCES = [
  {
    who: "Sellers",
    example: "For example, a home embroiderer",
    uses: "WhatsApp only",
    wants: "Orders, without a website or an app.",
  },
  {
    who: "Buyer agents",
    example: "AI agents shopping for a person or a business",
    uses: "Our MCP server",
    wants: "To find, check and buy from sellers they can trust.",
  },
  {
    who: "The people behind the agents",
    example: "Whoever pays for the order",
    uses: "An approval page and PayPal",
    wants: "To stay in control of their money.",
  },
  {
    who: "Demo viewers and judges",
    example: "Anyone trying OpenStall",
    uses: "The live demo and the seller chat page",
    wants: "To see the whole flow happen, and try it.",
  },
];

export default function HomePage() {
  return (
    <>
      <section className="mx-auto max-w-5xl px-4 pb-14 pt-12 sm:px-6 sm:pb-20 sm:pt-20">
        {/* The header already shows the name, so this line says what the site is. */}
        <p className="text-sm font-semibold uppercase tracking-wide text-accent">PayPal AI Hackathon demo</p>
        <h1 className="mt-3 max-w-3xl text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
          Small sellers on WhatsApp, selling to AI shopping agents
        </h1>
        <p className="mt-6 max-w-3xl text-lg leading-8 text-muted">
          OpenStall Collective lets small sellers who only use WhatsApp sell to AI shopping agents. A seller sends
          photos and a voice note, and AI turns them into listings that any agent can read and buy from. Each seller
          has an agent that negotiates within limits the seller sets. When an order is too big for one seller, the
          system splits it across several sellers, and one PayPal checkout pays them all. Every delivery adds to a
          signed trust record, and searches that find nothing become tips telling sellers what to make.
        </p>
        <div className="mt-8">
          <Link
            href="/demo"
            className="inline-flex min-h-12 items-center justify-center rounded-full bg-accent px-6 text-base font-semibold text-accent-foreground transition-colors hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            See the live demo
          </Link>
        </div>
      </section>

      <section aria-labelledby="audiences" className="border-t border-border bg-surface">
        <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6 sm:py-16">
          <h2 id="audiences" className="text-2xl font-semibold tracking-tight">
            Who it is for
          </h2>
          <ul className="mt-6 grid gap-4 sm:grid-cols-2">
            {AUDIENCES.map(({ who, example, uses, wants }) => (
              <li key={who} className="rounded-xl border border-border bg-background p-5">
                <h3 className="text-lg font-semibold">{who}</h3>
                <p className="mt-1 text-sm text-muted">{example}</p>
                <dl className="mt-4 space-y-2 text-sm">
                  <div>
                    <dt className="font-medium">Uses</dt>
                    <dd className="text-muted">{uses}</dd>
                  </div>
                  <div>
                    <dt className="font-medium">Wants</dt>
                    <dd className="text-muted">{wants}</dd>
                  </div>
                </dl>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </>
  );
}
