"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Badge } from "@/components/badge";
import { useEventStream } from "@/hooks/use-event-stream";
import { useLatestOrder } from "@/hooks/use-latest-order";
import { errorMessage } from "@/lib/api";
import { languageName, mediaUrl, place } from "@/lib/catalog";
import { CHANNEL_LABELS, getConversation, messageTime, playSeller, type ChatMessage, type Conversation } from "@/lib/chats";
import type { OrderPart } from "@/lib/orders";

/** The most recent messages each phone shows. Her whole chat is one link away. */
export const PHONE_MESSAGES = 8;

/** "Yes" as each maker types it, for answering OpenStall's question about her tracking in test mode. */
export const YES_WORDS: Record<string, string> = { ur: "ہاں", hi: "हाँ", es: "Sí", en: "Yes" };

/**
 * The /demo page's phones: each maker of the latest order, as she sees OpenStall on her own phone. Her order arrives
 * in her language once PayPal holds it; then her courier receipt, OpenStall's question, and her payment. They follow
 * the event stream live. In test mode a maker with no phone of her own (the seeded makers) can be played from here:
 * send her courier receipt, then answer "yes" in her language.
 */
export function MakerPhones() {
  const { order } = useLatestOrder();
  const { events } = useEventStream();
  // The newest event about a chat or a tracking: when it changes, someone wrote, so look again.
  const lastMessage =
    events.find((event) => event.type.startsWith("message.") || event.type.startsWith("tracking."))?.id ?? 0;
  const parts = order?.parts ?? [];
  const sellerKey = parts.map((part) => part.seller.id).join(",");
  const [conversations, setConversations] = useState<Record<string, Conversation>>({});
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (!sellerKey) return;
    const controller = new AbortController();
    Promise.allSettled(sellerKey.split(",").map((id) => getConversation(id, { signal: controller.signal }))).then(
      (results) => {
        if (controller.signal.aborted) return;
        const loaded: Record<string, Conversation> = {};
        for (const result of results) {
          if (result.status === "fulfilled") loaded[result.value.seller.id] = result.value;
        }
        setConversations(loaded);
      },
    );
    return () => controller.abort();
  }, [sellerKey, lastMessage, version]);

  return (
    <section aria-labelledby="phones-heading" className="mt-10">
      <h2 id="phones-heading" className="text-xl font-semibold tracking-tight">
        The makers&apos; phones
      </h2>
      <p className="mt-1 leading-7 text-muted">
        Each maker of the latest order, as she sees OpenStall: her order in her own language once PayPal holds it, then
        her courier receipt and her payment.
      </p>
      {order === undefined ? (
        <p aria-busy="true" className="mt-4 text-muted">
          Loading the makers&apos; phones…
        </p>
      ) : parts.length === 0 ? (
        <p className="mt-4 rounded-xl border border-dashed border-border p-6 leading-7 text-muted">
          No order yet. Each maker&apos;s phone appears here with her order once a buyer agent drafts one.
        </p>
      ) : (
        <ul aria-label="The makers' phones" className="mt-4 grid gap-4 md:grid-cols-2">
          {parts.map((part) => (
            <li key={part.id} className="min-w-0">
              <Phone part={part} conversation={conversations[part.seller.id]} onPlayed={() => setVersion((v) => v + 1)} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Phone({
  part,
  conversation,
  onPlayed,
}: {
  part: OrderPart;
  conversation: Conversation | undefined;
  onPlayed: () => void;
}) {
  const name = part.seller.name;
  const messages = (conversation?.messages ?? []).slice(-PHONE_MESSAGES);
  const language = languageName(part.notice?.language ?? null);
  const channel = part.notice?.channel ?? messages.at(-1)?.channel ?? null;
  const list = useRef<HTMLOListElement>(null);
  const newest = messages.at(-1)?.id;

  // The newest message in view, by scrolling the phone itself: never the page, which the viewer is reading. Again
  // when a photo loads, since it makes the thread taller after the first scroll.
  const toNewest = useCallback(() => {
    const element = list.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, []);
  useEffect(() => {
    toNewest();
  }, [newest, toNewest]);

  return (
    <article
      aria-label={`${name}'s phone`}
      className="flex h-full flex-col overflow-hidden rounded-3xl border border-border bg-surface shadow-sm"
    >
      <header className="flex items-center gap-3 border-b border-border px-4 py-3">
        <span
          aria-hidden="true"
          className="grid size-9 shrink-0 place-items-center rounded-full bg-accent text-sm font-semibold text-accent-foreground"
        >
          O
        </span>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-sm font-semibold">
            {name}&apos;s phone
            <span className="font-normal text-muted"> · OpenStall</span>
          </h3>
          <p className="truncate text-xs text-muted">
            {[place(part.seller.city, part.seller.country), language ? `Speaks ${language}` : null]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        {channel ? <Badge tone={channel === "whatsapp" ? "success" : "accent"}>{CHANNEL_LABELS[channel]}</Badge> : null}
      </header>
      <ol
        ref={list}
        aria-label={`Messages on ${name}'s phone`}
        className="flex max-h-80 min-h-40 flex-1 flex-col gap-2 overflow-y-auto bg-background px-3 py-3"
      >
        {messages.length === 0 ? (
          <li className="m-auto max-w-56 text-center text-xs text-muted">
            {conversation ? "Nothing yet: she hears about her share once PayPal holds the order." : "Loading her chat…"}
          </li>
        ) : null}
        {messages.map((message) => (
          <Bubble key={message.id} message={message} name={name} onPhoto={toNewest} />
        ))}
      </ol>
      <footer className="space-y-2 border-t border-border px-4 py-3">
        {conversation?.playable ? <PlayButtons part={part} onPlayed={onPlayed} /> : null}
        <Link
          href={`/seller-chat?seller=${encodeURIComponent(part.seller.id)}`}
          className="inline-block text-xs font-semibold text-accent underline underline-offset-4 hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Open {name}&apos;s chat
        </Link>
      </footer>
    </article>
  );
}

/** On her own phone, her messages sit on the right and OpenStall's on the left. */
function Bubble({ message, name, onPhoto }: { message: ChatMessage; name: string; onPhoto: () => void }) {
  const hers = message.direction === "inbound";
  const photo = message.media.find((item) => item.url && item.content_type.startsWith("image/"));
  return (
    <li className={`flex flex-col ${hers ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[90%] rounded-2xl px-3 py-2 text-xs leading-5 shadow-xs ${
          hers ? "rounded-tr-sm bg-accent-soft" : "rounded-tl-sm bg-surface"
        }`}
      >
        <span className="sr-only">{hers ? `${name}: ` : "OpenStall: "}</span>
        {photo?.url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={mediaUrl(photo.url)}
            alt={`A photo ${name} sent`}
            onLoad={onPhoto}
            className="mb-1 max-h-28 w-auto rounded-lg border border-border"
          />
        ) : null}
        {message.text ? (
          <p dir="auto" className="break-words whitespace-pre-line">
            {message.text}
          </p>
        ) : null}
      </div>
      <time dateTime={message.created_at} className="mt-0.5 px-1 text-[0.7rem] text-muted">
        {messageTime(message.created_at)}
      </time>
    </li>
  );
}

/**
 * Test mode: answer as her. Her courier receipt while her share waits for proof; "yes" in her language while
 * OpenStall asks her to confirm what it read. Each takes the path a real message takes.
 */
function PlayButtons({ part, onPlayed }: { part: OrderPart; onPlayed: () => void }) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const asked = part.proof?.state === "awaiting_confirmation";
  const canSend = part.status === "authorized" && !part.tracking_number && !asked;
  const yes = YES_WORDS[part.notice?.language ?? "en"] ?? YES_WORDS.en;
  if (!canSend && !asked) return null;

  async function play(text: string, receipt: boolean) {
    setBusy(true);
    setProblem(null);
    try {
      await playSeller(part.seller.id, text, receipt);
      onPlayed();
    } catch (error) {
      setProblem(`Not sent: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        {canSend ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => play("", true)}
            className="inline-flex min-h-11 items-center gap-2 rounded-full border border-border px-3 text-xs font-semibold hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
          >
            Send {part.seller.name}&apos;s courier receipt
            <span className="rounded-full bg-warning-soft px-2 py-0.5 text-warning">Simulated</span>
          </button>
        ) : null}
        {asked ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => play(yes, false)}
            className="inline-flex min-h-11 items-center gap-2 rounded-full bg-accent px-3 text-xs font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
          >
            Reply &ldquo;<span dir="auto">{yes}</span>&rdquo; as {part.seller.name}
            <span className="rounded-full bg-warning-soft px-2 py-0.5 text-warning">Simulated</span>
          </button>
        ) : null}
      </div>
      {problem ? (
        <p role="alert" className="mt-1 text-xs font-semibold text-danger">
          {problem}
        </p>
      ) : null}
    </div>
  );
}
