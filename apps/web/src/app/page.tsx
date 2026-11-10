import Link from "next/link";

import { CopyField } from "@/components/copy-field";
import { HeroScene } from "@/components/hero-scene";
import { HomeNumbers } from "@/components/home-numbers";
import {
  AgentIcon,
  ArrowRightIcon,
  ChatIcon,
  PlugIcon,
  RadarIcon,
  ReceiptIcon,
  ScaleIcon,
  ShieldIcon,
  SparkIcon,
  SplitIcon,
  WalletIcon,
} from "@/components/icons";
import { MakerStalls } from "@/components/maker-stalls";
import { catalogUrl, llmsTxtUrl, mcpUrl } from "@/lib/agent-urls";
import { apiBaseUrl } from "@/lib/api";
import { REPO_URL } from "@/lib/links";

const LINK =
  "font-semibold text-accent underline decoration-accent/40 underline-offset-4 transition-colors hover:decoration-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

const PRIMARY =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-full bg-accent px-6 text-base font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";
const SECONDARY =
  "inline-flex min-h-12 items-center justify-center gap-2 rounded-full border border-border bg-surface px-6 text-base font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

// The story (spec section 2), each step where it can be seen working.
const STEPS = [
  {
    title: "A maker lists by WhatsApp",
    text: "She sends photos and a voice note in her own language. AI drafts her listing, asks one question at a time for what it misses, and publishes it only when she says yes.",
    href: "/seller-chat",
    link: "Try it as a seller",
    Icon: ChatIcon,
  },
  {
    title: "A buyer's AI agent asks",
    text: "Through OpenStall's MCP storefront it searches, reads each maker's trust record, and asks for a quote: 40 cushion covers, at most $30 each, in 30 days.",
    href: "/demo#request-heading",
    link: "See the request",
    Icon: AgentIcon,
  },
  {
    title: "Seller agents negotiate within her limits",
    text: "Each maker's agent offers a price and a line to the buyer. Code checks every price against her floor: no words from a buyer can talk it lower.",
    href: "/demo#offers-heading",
    link: "See the offers",
    Icon: ScaleIcon,
  },
  {
    title: "Plain code splits the order",
    text: "The cheapest valid offers fill it across makers, and the split is explained in plain words. A person approves one PayPal checkout, which only reserves the money.",
    href: "/demo#allocation-heading",
    link: "See the split",
    Icon: SplitIcon,
  },
  {
    title: "Each maker is paid on proof",
    text: "She photographs her courier receipt and her share is captured and paid, with her tracking on the PayPal order. If she cannot deliver, her share goes back and the order heals itself.",
    href: "/demo#payments-heading",
    link: "See the payments",
    Icon: ReceiptIcon,
  },
  {
    title: "Trust and demand build up",
    text: "Every delivery signs her trust passport again, which any agent can check. Searches that found nothing become tips telling makers what to make next.",
    href: "/dashboard",
    link: "Open the dashboard",
    Icon: RadarIcon,
  },
];

// The PayPal pieces OpenStall uses, as the README lists them.
const PAYPAL = [
  ["Orders v2, intent AUTHORIZE", "one approval reserves the whole collective order"],
  ["Payments", "a partial capture of each maker's share on proof, a final capture on the last, a void of the rest"],
  [
    "Payouts",
    "each maker paid on her own rail: PayPal, Venmo for a US maker, or her bank through Hyperwallet in Pakistan " +
      "(simulated)",
  ],
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
    Icon: ChatIcon,
  },
  {
    who: "Buyer agents",
    example: "AI agents shopping for a person or a business",
    uses: "Our MCP server",
    wants: "To find, check and buy from sellers they can trust.",
    Icon: AgentIcon,
  },
  {
    who: "The people behind the agents",
    example: "Whoever pays for the order",
    uses: "An approval page and PayPal",
    wants: "To stay in control of their money.",
    Icon: ShieldIcon,
  },
  {
    who: "Demo viewers and judges",
    example: "Anyone trying OpenStall",
    uses: "The live demo and the seller chat page",
    wants: "To see the whole flow happen, and try it.",
    Icon: SparkIcon,
  },
];

function Eyebrow({ children }: { children: React.ReactNode }) {
  return <p className="text-sm font-semibold uppercase tracking-wider text-accent">{children}</p>;
}

export default function HomePage() {
  return (
    <>
      {/* Clipped, so the picture's glow never makes a phone scroll sideways. */}
      <section className="relative overflow-hidden">
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 pb-16 pt-10 sm:px-6 sm:pt-16 lg:grid-cols-[1.05fr_0.95fr] lg:gap-16 lg:pb-24">
          <div>
            {/* The header already shows the name, so this line says what the site is. */}
            <p className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-sm font-semibold text-accent">
              <span className="live-dot size-2 rounded-full bg-accent" />
              PayPal AI Hackathon demo
            </p>
            <h1 className="mt-5 text-4xl font-semibold tracking-tight text-balance sm:text-5xl lg:text-6xl">
              Many small makers. <span className="text-gradient">One big order.</span> One PayPal checkout.
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-muted">
              OpenStall Collective turns home makers who only use WhatsApp into one supplier that AI shopping agents can
              order from in bulk. A maker sends photos and a voice note, and AI turns them into a listing any agent can
              read. When an order is too big for one maker, plain code splits it across several, one PayPal approval
              reserves the money, and each maker is paid the moment she sends a photo of her shipping receipt.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link href="/demo" className={PRIMARY}>
                See the live demo
                <ArrowRightIcon className="size-4.5" />
              </Link>
              <Link href="/seller-chat" className={SECONDARY}>
                Try it as a seller
              </Link>
            </div>
            <ul className="mt-8 flex flex-wrap gap-x-5 gap-y-2 text-sm text-muted">
              <li className="flex items-center gap-1.5">
                <ShieldIcon className="size-4 text-accent" /> No real money moves
              </li>
              <li className="flex items-center gap-1.5">
                <WalletIcon className="size-4 text-accent" /> PayPal sandbox
              </li>
              <li className="flex items-center gap-1.5">
                <SparkIcon className="size-4 text-accent" /> Open source, MIT
              </li>
            </ul>
          </div>
          <HeroScene />
        </div>
      </section>

      <section aria-labelledby="numbers-heading" className="border-y border-border bg-surface/70">
        <div className="mx-auto max-w-6xl px-4 py-12 sm:px-6 sm:py-16">
          <h2 id="numbers-heading" className="text-2xl font-semibold tracking-tight sm:text-3xl">
            Right now on OpenStall
          </h2>
          <HomeNumbers />
        </div>
      </section>

      <section aria-labelledby="how-heading">
        <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6 sm:py-20">
          <Eyebrow>From a voice note to a paid order</Eyebrow>
          <h2 id="how-heading" className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
            How it works
          </h2>
          <ol className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {STEPS.map(({ title, text, href, link, Icon }, index) => (
              <li
                key={title}
                className="reveal lift group relative flex flex-col overflow-hidden rounded-2xl border border-border bg-surface p-6"
              >
                <span
                  aria-hidden="true"
                  className="absolute -right-3 -top-6 text-8xl font-bold tracking-tighter text-accent/[0.07] transition-transform duration-500 group-hover:-translate-y-1"
                >
                  {index + 1}
                </span>
                <span className="grid size-11 place-items-center rounded-xl bg-accent-soft text-accent transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-3">
                  <Icon className="size-5.5" />
                </span>
                <p aria-hidden="true" className="mt-4 text-sm font-semibold text-accent">
                  Step {index + 1}
                </p>
                <h3 className="mt-1 text-lg font-semibold">{title}</h3>
                <p className="mt-2 flex-1 leading-7 text-muted">{text}</p>
                <Link href={href} className={`mt-5 inline-flex items-center gap-1 self-start ${LINK}`}>
                  {link}
                  <ArrowRightIcon className="size-4 transition-transform group-hover:translate-x-0.5" />
                </Link>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section id="makers" aria-labelledby="makers-heading" className="border-y border-border bg-surface/70">
        <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6 sm:py-20">
          <Eyebrow>Five makers, four countries</Eyebrow>
          <h2 id="makers-heading" className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
            Meet the makers
          </h2>
          <p className="mt-2 max-w-3xl leading-7 text-muted">
            Each one sells only on WhatsApp. Together they can fill an order none of them could fill alone.
          </p>
          <MakerStalls />
        </div>
      </section>

      <section aria-labelledby="agents-heading">
        <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 sm:px-6 sm:py-20 lg:grid-cols-[1fr_1.1fr] lg:items-center">
          <div>
            <Eyebrow>Model Context Protocol</Eyebrow>
            <h2 id="agents-heading" className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
              For AI agents
            </h2>
            <p className="mt-3 max-w-xl leading-7 text-muted">
              Connect any MCP client to the storefront: search, products, trust cards, quotes, a draft collective order
              and an approval link for its human. No tool can move money. Agents without MCP can read the feeds.
            </p>
          </div>
          <div className="reveal rounded-2xl border border-border bg-surface p-5 sm:p-6">
            <p className="flex items-center gap-2 text-sm font-semibold">
              <span className="grid size-8 place-items-center rounded-lg bg-accent-soft text-accent">
                <PlugIcon className="size-4.5" />
              </span>
              Plug an agent in
            </p>
            <div className="mt-4">
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
        </div>
      </section>

      <section aria-labelledby="paypal-heading" className="border-y border-border bg-surface/70">
        <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6 sm:py-20">
          <Eyebrow>Pay-on-proof</Eyebrow>
          <h2 id="paypal-heading" className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
            Built on PayPal
          </h2>
          <p className="mt-3 max-w-3xl leading-7 text-muted">
            Pay-on-proof on the payouts path, proven step by step on PayPal&apos;s real sandbox. The site runs in the
            sandbox, or with a simulated PayPal in test mode: no real money moves.
          </p>
          <dl className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {PAYPAL.map(([name, use]) => (
              <div key={name} className="reveal lift rounded-2xl border border-border bg-background p-5">
                <dt className="flex items-center gap-2 font-semibold">
                  <span aria-hidden="true" className="size-2 rounded-full bg-warm" />
                  {name}
                </dt>
                <dd className="mt-1.5 text-sm leading-6 text-muted">{use}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-8 flex flex-wrap gap-x-6 gap-y-2">
            <Link href="/status#paypal-products" className={LINK}>
              Every PayPal product, and how far it has got
            </Link>
            <a href={REPO_URL} className={LINK}>
              Read the code on GitHub
            </a>
          </p>
        </div>
      </section>

      <section aria-labelledby="audiences">
        <div className="mx-auto max-w-6xl px-4 py-14 sm:px-6 sm:py-20">
          <h2 id="audiences" className="text-2xl font-semibold tracking-tight sm:text-3xl">
            Who it is for
          </h2>
          <ul className="mt-8 grid gap-4 sm:grid-cols-2">
            {AUDIENCES.map(({ who, example, uses, wants, Icon }) => (
              <li key={who} className="reveal lift flex gap-4 rounded-2xl border border-border bg-surface p-6">
                <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-accent-soft text-accent">
                  <Icon className="size-5.5" />
                </span>
                <div>
                  <h3 className="text-lg font-semibold">{who}</h3>
                  <p className="mt-0.5 text-sm text-muted">{example}</p>
                  <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
                    <div>
                      <dt className="font-medium">Uses</dt>
                      <dd className="text-muted">{uses}</dd>
                    </div>
                    <div>
                      <dt className="font-medium">Wants</dt>
                      <dd className="text-muted">{wants}</dd>
                    </div>
                  </dl>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section aria-labelledby="start-heading" className="px-4 pb-16 sm:px-6 sm:pb-24">
        <div className="relative mx-auto max-w-6xl overflow-hidden rounded-[2rem] bg-accent px-6 py-12 text-accent-foreground sm:px-12 sm:py-16">
          <div
            aria-hidden="true"
            className="animate-float-slow pointer-events-none absolute -right-24 -top-28 size-72 rounded-full bg-warm/25 blur-3xl"
          />
          <div
            aria-hidden="true"
            className="animate-float pointer-events-none absolute -bottom-32 -left-20 size-64 rounded-full bg-sun/20 blur-3xl"
          />
          <div className="relative max-w-2xl">
            <h2 id="start-heading" className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">
              Watch one order happen, start to finish.
            </h2>
            <p className="mt-3 text-lg leading-8">
              A buyer&apos;s agent asks, makers&apos; agents bid, PayPal holds the money, and each maker is paid when
              she ships. It takes about a minute.
            </p>
            <Link
              href="/demo"
              className="mt-7 inline-flex min-h-12 items-center gap-2 rounded-full bg-surface px-6 text-base font-semibold text-foreground transition-transform hover:-translate-y-0.5 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-surface"
            >
              Run the story on /demo
              <ArrowRightIcon className="size-4.5" />
            </Link>
          </div>
        </div>
      </section>
    </>
  );
}
