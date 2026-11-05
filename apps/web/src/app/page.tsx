import Link from "next/link";

import { CopyField } from "@/components/copy-field";
import { HomeNumbers } from "@/components/home-numbers";
import { MakerStalls } from "@/components/maker-stalls";
import { catalogUrl, llmsTxtUrl, mcpUrl } from "@/lib/agent-urls";
import { apiBaseUrl } from "@/lib/api";
import { REPO_URL } from "@/lib/links";

const LINK =
  "font-semibold text-accent underline underline-offset-4 hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

// The story (spec section 2), each step where it can be seen working.
const STEPS = [
  {
    title: "A maker lists by WhatsApp",
    text: "She sends photos and a voice note in her own language. AI drafts her listing, asks one question at a time for what it misses, and publishes it only when she says yes.",
    href: "/seller-chat",
    link: "Try it as a seller",
  },
  {
    title: "A buyer's AI agent asks",
    text: "Through OpenStall's MCP storefront it searches, reads each maker's trust record, and asks for a quote: 40 cushion covers, at most $30 each, in 30 days.",
    href: "/demo#request-heading",
    link: "See the request",
  },
  {
    title: "Seller agents negotiate within her limits",
    text: "Each maker's agent offers a price and a line to the buyer. Code checks every price against her floor: no words from a buyer can talk it lower.",
    href: "/demo#offers-heading",
    link: "See the offers",
  },
  {
    title: "Plain code splits the order",
    text: "The cheapest valid offers fill it across makers, and the split is explained in plain words. A person approves one PayPal checkout, which only reserves the money.",
    href: "/demo#allocation-heading",
    link: "See the split",
  },
  {
    title: "Each maker is paid on proof",
    text: "She photographs her courier receipt and her share is captured and paid, with her tracking on the PayPal order. If she cannot deliver, her share goes back and the order heals itself.",
    href: "/demo#payments-heading",
    link: "See the payments",
  },
  {
    title: "Trust and demand build up",
    text: "Every delivery signs her trust passport again, which any agent can check. Searches that found nothing become tips telling makers what to make next.",
    href: "/dashboard",
    link: "Open the dashboard",
  },
];

// The PayPal pieces OpenStall uses, as the README lists them.
const PAYPAL = [
  ["Orders v2, intent AUTHORIZE", "one approval reserves the whole collective order"],
  ["Payments", "a partial capture of each maker's share on proof, a final capture on the last, a void of the rest"],
  ["Payouts", "each maker paid on her own rail: PayPal, or Venmo for a US maker"],
  ["Order tracking", "each maker's courier and tracking number on her capture"],
  ["Webhooks", "every event verified with PayPal and applied exactly once"],
  ["APIMatic's PayPal SDK", "every Orders and Payments call"],
];

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
          Many small makers. One big order. One PayPal checkout.
        </h1>
        <p className="mt-6 max-w-3xl text-lg leading-8 text-muted">
          OpenStall Collective turns home makers who only use WhatsApp into one supplier that AI shopping agents can
          order from in bulk. A maker sends photos and a voice note, and AI turns them into a listing any agent can
          read. When an order is too big for one maker, plain code splits it across several, one PayPal approval
          reserves the money, and each maker is paid the moment she sends a photo of her shipping receipt.
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link
            href="/demo"
            className="inline-flex min-h-12 items-center justify-center rounded-full bg-accent px-6 text-base font-semibold text-accent-foreground transition-colors hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            See the live demo
          </Link>
          <Link
            href="/seller-chat"
            className="inline-flex min-h-12 items-center justify-center rounded-full border border-border px-6 text-base font-semibold transition-colors hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            Try it as a seller
          </Link>
        </div>
      </section>

      <section aria-labelledby="numbers-heading" className="border-t border-border bg-surface">
        <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6 sm:py-16">
          <h2 id="numbers-heading" className="text-2xl font-semibold tracking-tight">
            Right now on OpenStall
          </h2>
          <HomeNumbers />
        </div>
      </section>

      <section aria-labelledby="how-heading" className="border-t border-border">
        <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6 sm:py-16">
          <h2 id="how-heading" className="text-2xl font-semibold tracking-tight">
            How it works
          </h2>
          <ol className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {STEPS.map(({ title, text, href, link }, index) => (
              <li key={title} className="flex flex-col rounded-xl border border-border bg-surface p-5">
                <p aria-hidden="true" className="text-sm font-semibold text-accent">
                  {index + 1}
                </p>
                <h3 className="mt-1 text-lg font-semibold">{title}</h3>
                <p className="mt-2 flex-1 leading-7 text-muted">{text}</p>
                <Link href={href} className={`mt-4 self-start ${LINK}`}>
                  {link}
                </Link>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="makers" aria-labelledby="makers-heading" className="border-t border-border bg-surface">
        <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6 sm:py-16">
          <h2 id="makers-heading" className="text-2xl font-semibold tracking-tight">
            Meet the makers
          </h2>
          <p className="mt-2 max-w-3xl leading-7 text-muted">
            Each one sells only on WhatsApp. Together they can fill an order none of them could fill alone.
          </p>
          <MakerStalls />
        </div>
      </section>

      <section aria-labelledby="agents-heading" className="border-t border-border">
        <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6 sm:py-16">
          <h2 id="agents-heading" className="text-2xl font-semibold tracking-tight">
            For AI agents
          </h2>
          <p className="mt-2 max-w-3xl leading-7 text-muted">
            Connect any MCP client to the storefront: search, products, trust cards, quotes, a draft collective order and
            an approval link for its human. No tool can move money. Agents without MCP can read the feeds.
          </p>
          <div className="mt-6 max-w-3xl">
            <CopyField label="MCP storefront (Streamable HTTP)" value={mcpUrl()} />
          </div>
          <ul className="mt-4 flex flex-wrap gap-x-6 gap-y-2">
            <li>
              <a href={catalogUrl()} className={LINK}>
                catalog.json
              </a>
            </li>
            <li>
              <a href={llmsTxtUrl()} className={LINK}>
                llms.txt
              </a>
            </li>
            <li>
              <a href={`${apiBaseUrl()}/passport/public-key`} className={LINK}>
                The trust passports&apos; public key
              </a>
            </li>
          </ul>
        </div>
      </section>

      <section aria-labelledby="paypal-heading" className="border-t border-border bg-surface">
        <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6 sm:py-16">
          <h2 id="paypal-heading" className="text-2xl font-semibold tracking-tight">
            Built on PayPal
          </h2>
          <p className="mt-2 max-w-3xl leading-7 text-muted">
            Pay-on-proof on the payouts path, proven step by step on PayPal&apos;s real sandbox. The site runs in the
            sandbox, or with a simulated PayPal in test mode: no real money moves.
          </p>
          <dl className="mt-6 grid gap-4 sm:grid-cols-2">
            {PAYPAL.map(([name, use]) => (
              <div key={name} className="rounded-xl border border-border bg-background p-4">
                <dt className="font-semibold">{name}</dt>
                <dd className="mt-1 text-sm leading-6 text-muted">{use}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-6">
            <a href={REPO_URL} className={LINK}>
              Read the code on GitHub
            </a>
          </p>
        </div>
      </section>

      <section aria-labelledby="audiences" className="border-t border-border">
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
