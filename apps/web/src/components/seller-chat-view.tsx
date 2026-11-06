"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/badge";
import { ChatComposer } from "@/components/chat-composer";
import { ListingDraftCard } from "@/components/listing-draft";
import { LiveListingCard } from "@/components/live-listing";
import { VoiceTranscript } from "@/components/voice-transcript";
import { useEventStream } from "@/hooks/use-event-stream";
import { ApiError, errorMessage } from "@/lib/api";
import { languageName, mediaUrl, place } from "@/lib/catalog";
import {
  CHANNEL_LABELS,
  getChats,
  getConversation,
  getSamples,
  messageTime,
  playSeller,
  sendWebMessage,
  type ChatMedia,
  type ChatMessage,
  type ChatSamples,
  type ChatSummary,
  type Conversation,
} from "@/lib/chats";
import { newDemoPhoneId, saveDemoPhone, useDemoPhone } from "@/lib/demo-phone";

type Load<T> = { state: "loading" } | { state: "loaded"; value: T } | { state: "failed"; message: string };

/** A message on its way: shown at once, and replaced by the stored one when the conversation reloads. */
type Pending = { key: number; text: string; files: File[]; messageId: string | null };

/**
 * The sellers' side of OpenStall. In your own demo phone you are a seller: write, attach photos and record a voice
 * note, and OpenStall answers through the same handler as on WhatsApp. Other sellers' WhatsApp chats can be watched.
 * It follows the event log, so new messages appear without reloading.
 */
export function SellerChatView() {
  const chosen = useSearchParams().get("seller");
  const router = useRouter();
  const phone = useDemoPhone();
  const [chats, setChats] = useState<Load<ChatSummary[]>>({ state: "loading" });
  const [conversation, setConversation] = useState<Load<Conversation> | null>(null);
  const [pending, setPending] = useState<Pending[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [samples, setSamples] = useState<ChatSamples | null>(null);
  const nextKey = useRef(1);
  const { events } = useEventStream();
  // The newest message event: when it changes, someone wrote, so look again.
  const latestMessage = events.find((event) => event.type.startsWith("message."))?.id ?? 0;

  const mine = !chosen || chosen === phone?.sellerId;
  const sellerId = chosen ?? phone?.sellerId ?? null;

  useEffect(() => {
    const controller = new AbortController();
    getSamples({ signal: controller.signal })
      .then(setSamples)
      .catch(() => {
        // Without the samples the chat works the same: there is just no sample to attach.
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getChats({ signal: controller.signal })
      .then((value) => setChats({ state: "loaded", value }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setChats({ state: "failed", message: errorMessage(error) });
      });
    return () => controller.abort();
  }, [latestMessage, version]);

  useEffect(() => {
    if (!sellerId) return;
    const controller = new AbortController();
    getConversation(sellerId, { signal: controller.signal })
      .then((value) => {
        setConversation({ state: "loaded", value });
        setPending((list) => list.filter((item) => !value.messages.some((message) => message.id === item.messageId)));
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const message =
          error instanceof ApiError && error.status === 404
            ? "There is no seller at this address."
            : errorMessage(error);
        setConversation({ state: "failed", message });
      });
    return () => controller.abort();
  }, [sellerId, latestMessage, version]);

  async function send(text: string, files: File[]): Promise<boolean> {
    const current = phone ?? { id: newDemoPhoneId(), sellerId: null };
    const key = nextKey.current++;
    setProblem(null);
    setPending((list) => [...list, { key, text, files, messageId: null }]);
    try {
      const sent = await sendWebMessage(current.id, text, files);
      setPending((list) => list.map((item) => (item.key === key ? { ...item, messageId: sent.message_id } : item)));
      if (current.sellerId !== sent.seller_id) saveDemoPhone({ id: current.id, sellerId: sent.seller_id });
      setVersion((count) => count + 1);
      return true;
    } catch (error) {
      setPending((list) => list.filter((item) => item.key !== key));
      setProblem(`Not sent: ${errorMessage(error)}`);
      return false;
    }
  }

  function startOver() {
    saveDemoPhone(null);
    setConversation(null);
    setPending([]);
    setProblem(null);
    router.push("/seller-chat");
  }

  // Only the conversation of the seller being looked at: never the last one's while the next one loads.
  const loaded =
    conversation?.state === "loaded" && conversation.value.seller.id === sellerId ? conversation.value : null;
  return (
    <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
      <div className="min-w-0 space-y-6">
        <section aria-labelledby="phone-heading" className="rounded-2xl border border-border bg-surface p-4">
          <h2 id="phone-heading" className="font-semibold">
            Your demo phone
          </h2>
          <p className="mt-1 text-sm leading-6 text-muted">
            Be a seller: send a photo of something you make, and OpenStall answers as it would on WhatsApp.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {!mine ? (
              <Link
                href={phone?.sellerId ? `/seller-chat?seller=${encodeURIComponent(phone.sellerId)}` : "/seller-chat"}
                className="inline-flex min-h-11 items-center rounded-full bg-accent px-4 text-sm font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                Open your chat
              </Link>
            ) : null}
            <button
              type="button"
              onClick={startOver}
              className="inline-flex min-h-11 items-center rounded-full border border-border px-4 text-sm font-semibold hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
            >
              Start as a new seller
            </button>
          </div>
        </section>
        <section aria-labelledby="sellers-heading" className="min-w-0">
          <h2 id="sellers-heading" className="text-sm font-semibold tracking-wide text-muted uppercase">
            Sellers
          </h2>
          <SellerPicker chats={chats} selected={sellerId} mySellerId={phone?.sellerId ?? null} />
        </section>
      </div>
      <section aria-label="Conversation" className="min-w-0">
        {mine ? (
          <>
            <Phone
              title={loaded?.seller.name ?? "You"}
              subtitle="Web chat · your demo phone"
              messages={sellerId ? (loaded?.messages ?? []) : []}
              perspective="seller"
              pending={pending}
              loading={!!sellerId && !loaded && conversation?.state !== "failed"}
              empty="Send a photo of something you make, or tell OpenStall about it, to start."
              footer={
                <>
                  {problem ? (
                    <p role="alert" className="border-t border-border bg-danger-soft px-4 py-2 text-sm">
                      {problem}
                    </p>
                  ) : null}
                  <ChatComposer
                    onSend={send}
                    busy={pending.some((item) => item.messageId === null)}
                    samples={samples}
                  />
                </>
              }
            />
            {sellerId && loaded?.draft ? <ListingDraftCard draft={loaded.draft} mine /> : null}
            {sellerId && loaded?.listing ? <LiveListingCard listing={loaded.listing} mine /> : null}
          </>
        ) : conversation?.state === "failed" ? (
          <p role="alert" className="rounded-2xl border border-border bg-surface p-5 text-muted">
            {conversation.message}
          </p>
        ) : !loaded ? (
          <div aria-busy="true" aria-label="Loading the conversation" className="h-96 animate-pulse rounded-3xl bg-border/60" />
        ) : (
          <>
            <Phone
              title={loaded.seller.name}
              subtitle={place(loaded.seller.city, loaded.seller.country) ?? "Where she lives is not known yet"}
              messages={loaded.messages}
              perspective="watcher"
              pending={[]}
              loading={false}
              empty="No messages yet."
              footer={
                <p className="border-t border-border bg-surface px-5 py-3 text-sm text-muted">
                  You are watching this chat. It happens on {CHANNEL_LABELS[loaded.messages[0]?.channel ?? "whatsapp"]}.
                </p>
              }
            />
            {loaded.draft ? <ListingDraftCard draft={loaded.draft} mine={false} /> : null}
            {loaded.listing ? <LiveListingCard listing={loaded.listing} mine={false} /> : null}
            {loaded.playable ? (
              <PlayPanel name={loaded.seller.name} sellerId={loaded.seller.id} onSent={() => setVersion((count) => count + 1)} />
            ) : null}
          </>
        )}
      </section>
    </div>
  );
}

/**
 * Test mode only, under the chat of a maker with no phone of her own (the seeded makers): answer as her. Her courier
 * receipt photo is fake mode's own, which its stand-in model reads; her words go through the same handler as WhatsApp.
 */
function PlayPanel({ name, sellerId, onSent }: { name: string; sellerId: string; onSent: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  async function send(receipt: boolean) {
    setBusy(true);
    setProblem(null);
    try {
      await playSeller(sellerId, receipt ? "" : text.trim(), receipt);
      if (!receipt) setText("");
      onSent();
    } catch (error) {
      setProblem(`Not sent: ${errorMessage(error)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby="play-heading"
      className="mx-auto mt-4 max-w-xl rounded-2xl border border-dashed border-border bg-surface p-4 sm:p-5"
    >
      <h3 id="play-heading" className="flex flex-wrap items-center gap-2 font-semibold">
        Play {name} <Badge tone="warning">Test mode</Badge>
      </h3>
      <p className="mt-1 text-sm leading-6 text-muted">
        {name} has no phone in this demo, so answer as her: send the courier receipt photo she would send once she has
        shipped, then reply to OpenStall.
      </p>
      <button
        type="button"
        onClick={() => send(true)}
        disabled={busy}
        className="mt-3 inline-flex min-h-11 items-center gap-2 rounded-full border border-border px-4 text-sm font-semibold hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
      >
        Send her courier receipt photo
        <span className="rounded-full bg-warning-soft px-2 py-0.5 text-xs text-warning">Simulated</span>
      </button>
      <form
        className="mt-3 flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (text.trim()) void send(false);
        }}
      >
        <label className="min-w-0 flex-1 text-sm">
          <span className="font-medium">Reply as {name}</span>
          <input
            dir="auto"
            value={text}
            onChange={(event) => setText(event.target.value)}
            maxLength={4000}
            placeholder="For example: yes"
            className="mt-1 block min-h-11 w-full rounded-xl border border-border bg-background px-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          />
        </label>
        <button
          type="submit"
          disabled={busy || !text.trim()}
          className="inline-flex min-h-11 items-center rounded-full bg-accent px-4 text-sm font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-60"
        >
          Send as {name}
        </button>
      </form>
      {problem ? (
        <p role="alert" className="mt-2 text-sm font-semibold text-danger">
          {problem}
        </p>
      ) : null}
    </section>
  );
}

function SellerPicker({
  chats,
  selected,
  mySellerId,
}: {
  chats: Load<ChatSummary[]>;
  selected: string | null;
  mySellerId: string | null;
}) {
  if (chats.state === "loading") {
    return <div aria-busy="true" aria-label="Loading the sellers" className="mt-3 h-24 animate-pulse rounded-xl bg-border/60" />;
  }
  if (chats.state === "failed") {
    return (
      <p role="alert" className="mt-3 text-sm text-muted">
        {chats.message}
      </p>
    );
  }
  if (chats.value.length === 0) {
    return (
      <p className="mt-3 rounded-xl border border-dashed border-border p-4 text-sm leading-6 text-muted">
        No seller has written yet. When a maker sends a photo or a voice note to our WhatsApp number, or you send one
        from your demo phone, her chat appears here.
      </p>
    );
  }
  return (
    <ul aria-label="Sellers who have chatted" className="mt-3 space-y-2">
      {chats.value.map((chat) => {
        const current = chat.seller.id === selected;
        const where = place(chat.seller.city, chat.seller.country);
        return (
          <li key={`${chat.seller.id}-${chat.channel}`}>
            <Link
              href={`/seller-chat?seller=${encodeURIComponent(chat.seller.id)}`}
              aria-current={current ? "page" : undefined}
              className={`block rounded-xl border px-4 py-3 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${
                current ? "border-accent bg-accent-soft" : "border-border bg-surface hover:bg-background"
              }`}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="truncate font-semibold">
                  {chat.seller.name}
                  {chat.seller.id === mySellerId ? <span className="font-normal text-muted"> (you)</span> : null}
                </span>
                <Badge tone={chat.channel === "whatsapp" ? "success" : "accent"}>{CHANNEL_LABELS[chat.channel]}</Badge>
              </span>
              {where ? <span className="mt-0.5 block text-xs text-muted">{where}</span> : null}
              {chat.last_text ? (
                <span dir="auto" className="mt-1 block truncate text-sm text-muted">
                  {chat.last_text}
                </span>
              ) : null}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

/** A phone-style thread. As the seller, your messages are on the right; watching, the seller's are on the left. */
function Phone({
  title,
  subtitle,
  messages,
  perspective,
  pending,
  loading,
  empty,
  footer,
}: {
  title: string;
  subtitle: string;
  messages: ChatMessage[];
  perspective: "seller" | "watcher";
  pending: Pending[];
  loading: boolean;
  empty: string;
  footer: React.ReactNode;
}) {
  const end = useRef<HTMLLIElement>(null);
  const count = messages.length + pending.length;

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [count]);

  return (
    <div className="mx-auto flex max-w-xl flex-col overflow-hidden rounded-3xl border border-border bg-surface shadow-sm">
      <header className="flex items-center gap-3 border-b border-border px-5 py-4">
        <span
          aria-hidden="true"
          className="grid size-10 shrink-0 place-items-center rounded-full bg-accent text-sm font-semibold text-accent-foreground"
        >
          {perspective === "seller" ? "O" : title.slice(0, 1)}
        </span>
        <div className="min-w-0">
          <h2 className="truncate font-semibold">{perspective === "seller" ? "OpenStall" : title}</h2>
          <p className="truncate text-xs text-muted">{perspective === "seller" ? `${title} · ${subtitle}` : subtitle}</p>
        </div>
      </header>
      <ol
        aria-label={perspective === "seller" ? "Your messages with OpenStall" : `Messages with ${title}`}
        aria-busy={loading}
        // It scrolls, so a keyboard must be able to reach it and scroll it too.
        tabIndex={0}
        className="flex max-h-[32rem] min-h-64 flex-col gap-3 overflow-y-auto bg-background px-4 py-5 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent"
      >
        {count === 0 && !loading ? <li className="m-auto max-w-xs text-center text-sm text-muted">{empty}</li> : null}
        {messages.map((message) => (
          <Bubble key={message.id} message={message} title={title} perspective={perspective} />
        ))}
        {pending.map((item) => (
          <PendingBubble key={item.key} item={item} />
        ))}
        <li ref={end} aria-hidden="true" />
      </ol>
      {footer}
    </div>
  );
}

function Bubble({
  message,
  title,
  perspective,
}: {
  message: ChatMessage;
  title: string;
  perspective: "seller" | "watcher";
}) {
  const fromSeller = message.direction === "inbound";
  // As the seller, your own messages sit on the right, as on your phone.
  const right = perspective === "seller" ? fromSeller : !fromSeller;
  const speaker = fromSeller ? (perspective === "seller" ? "You" : title) : "OpenStall";
  return (
    <li className={`flex flex-col ${right ? "items-end" : "items-start"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-6 shadow-xs ${
          right ? "rounded-tr-sm bg-accent-soft" : "rounded-tl-sm bg-surface"
        }`}
      >
        <span className="sr-only">{speaker}: </span>
        {message.media.map((item, index) => (
          <Media key={index} item={item} language={message.language} />
        ))}
        {message.transcript ? <VoiceTranscript text={message.transcript} language={message.language} /> : null}
        {/* dir="auto": a message in Urdu reads right to left, as on her phone, and English left to right. */}
        {message.text ? (
          <p dir="auto" className="break-words whitespace-pre-line">
            {message.text}
          </p>
        ) : null}
      </div>
      <time dateTime={message.created_at} className="mt-1 px-1 text-xs text-muted">
        {messageTime(message.created_at)} · {CHANNEL_LABELS[message.channel]}
        {perspective === "seller" && fromSeller ? " · Sent" : null}
      </time>
    </li>
  );
}

function PendingBubble({ item }: { item: Pending }) {
  const photos = item.files.filter((file) => file.type.startsWith("image/")).length;
  const voice = item.files.length - photos;
  const attached = [photos ? `${photos} photo${photos > 1 ? "s" : ""}` : "", voice ? "a voice note" : ""]
    .filter(Boolean)
    .join(" and ");
  return (
    <li className="flex flex-col items-end">
      {/* Marked as on its way by a dashed edge, not by fading: its words stay as readable as any message. */}
      <div className="max-w-[85%] rounded-2xl rounded-tr-sm border border-dashed border-accent bg-accent-soft px-4 py-2.5 text-sm leading-6 shadow-xs">
        {attached ? <p className="text-xs text-muted">With {attached}</p> : null}
        {item.text ? <p className="break-words whitespace-pre-line">{item.text}</p> : null}
      </div>
      <p className="mt-1 px-1 text-xs text-muted">Sending…</p>
    </li>
  );
}

function Media({ item, language }: { item: ChatMedia; language?: string | null }) {
  if (item.refused || !item.url) {
    return <p className="mb-1 text-xs text-muted italic">A file that was not kept: {item.refused}</p>;
  }
  const url = mediaUrl(item.url);
  if (item.content_type.startsWith("image/")) {
    return (
      <a href={url} target="_blank" rel="noreferrer" className="mb-2 block">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={url} alt="A photo the seller sent" className="max-h-64 w-auto rounded-xl border border-border" />
      </a>
    );
  }
  if (item.spoken) {
    // OpenStall's answer read out, for a maker who talks to it in voice notes.
    const spokenIn = languageName(language ?? null);
    return (
      <figure className="mb-2">
        <audio controls preload="metadata" src={url} aria-label="OpenStall's answer, spoken" className="w-64 max-w-full">
          <a href={url}>Play the spoken answer</a>
        </audio>
        <figcaption className="mt-1 text-xs text-muted">{spokenIn ? `Spoken in ${spokenIn}` : "Spoken"}</figcaption>
      </figure>
    );
  }
  if (item.content_type.startsWith("audio/")) {
    return (
      <audio controls preload="metadata" src={url} aria-label="A voice note" className="mb-2 w-64 max-w-full">
        <a href={url}>Play the voice note</a>
      </audio>
    );
  }
  return null;
}
