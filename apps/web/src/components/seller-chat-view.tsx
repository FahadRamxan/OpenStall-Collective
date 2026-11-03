"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Badge } from "@/components/badge";
import { useEventStream } from "@/hooks/use-event-stream";
import { ApiError, errorMessage } from "@/lib/api";
import { mediaUrl, place } from "@/lib/catalog";
import {
  CHANNEL_LABELS,
  getChats,
  getConversation,
  messageTime,
  type ChatMedia,
  type ChatMessage,
  type ChatSummary,
  type Conversation,
} from "@/lib/chats";

type Load<T> = { state: "loading" } | { state: "loaded"; value: T } | { state: "failed"; message: string };

/**
 * Sellers' conversations with OpenStall, as chat bubbles: what they sent on WhatsApp, photos and voice notes
 * included, and every reply. It follows the event log, so a new message appears without reloading.
 */
export function SellerChatView() {
  const chosen = useSearchParams().get("seller");
  const [chats, setChats] = useState<Load<ChatSummary[]>>({ state: "loading" });
  const [conversation, setConversation] = useState<Load<Conversation> | null>(null);
  const { events } = useEventStream();
  // The newest message event: when it changes, someone wrote, so look again.
  const latestMessage = events.find((event) => event.type.startsWith("message."))?.id ?? 0;
  const sellerId = chosen ?? (chats.state === "loaded" ? chats.value[0]?.seller.id : undefined);

  useEffect(() => {
    const controller = new AbortController();
    getChats({ signal: controller.signal })
      .then((value) => setChats({ state: "loaded", value }))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setChats({ state: "failed", message: errorMessage(error) });
      });
    return () => controller.abort();
  }, [latestMessage]);

  useEffect(() => {
    if (!sellerId) return;
    const controller = new AbortController();
    getConversation(sellerId, { signal: controller.signal })
      .then((value) => setConversation({ state: "loaded", value }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const message =
          error instanceof ApiError && error.status === 404
            ? "There is no seller at this address."
            : errorMessage(error);
        setConversation({ state: "failed", message });
      });
    return () => controller.abort();
  }, [sellerId, latestMessage]);

  return (
    <div className="grid gap-6 lg:grid-cols-[18rem_1fr]">
      <section aria-labelledby="sellers-heading" className="min-w-0">
        <h2 id="sellers-heading" className="text-sm font-semibold tracking-wide text-muted uppercase">
          Sellers
        </h2>
        <SellerPicker chats={chats} selected={sellerId} />
      </section>
      <section aria-label="Conversation" className="min-w-0">
        {!sellerId ? null : conversation === null || conversation.state === "loading" ? (
          <div aria-busy="true" aria-label="Loading the conversation" className="h-96 animate-pulse rounded-3xl bg-border/60" />
        ) : conversation.state === "failed" ? (
          <p role="alert" className="rounded-2xl border border-border bg-surface p-5 text-muted">
            {conversation.message}
          </p>
        ) : (
          <Thread conversation={conversation.value} />
        )}
      </section>
    </div>
  );
}

function SellerPicker({ chats, selected }: { chats: Load<ChatSummary[]>; selected: string | undefined }) {
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
        No seller has written yet. When a maker sends a photo or a voice note to our WhatsApp number, her chat appears
        here.
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
                <span className="truncate font-semibold">{chat.seller.name}</span>
                <Badge tone={chat.channel === "whatsapp" ? "success" : "accent"}>{CHANNEL_LABELS[chat.channel]}</Badge>
              </span>
              {where ? <span className="mt-0.5 block text-xs text-muted">{where}</span> : null}
              {chat.last_text ? <span className="mt-1 block truncate text-sm text-muted">{chat.last_text}</span> : null}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function Thread({ conversation }: { conversation: Conversation }) {
  const end = useRef<HTMLLIElement>(null);
  const { seller, messages } = conversation;
  const where = place(seller.city, seller.country);

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length]);

  return (
    <div className="mx-auto flex max-w-xl flex-col overflow-hidden rounded-3xl border border-border bg-surface shadow-sm">
      <header className="flex items-center gap-3 border-b border-border px-5 py-4">
        <span
          aria-hidden="true"
          className="grid size-10 shrink-0 place-items-center rounded-full bg-accent text-sm font-semibold text-accent-foreground"
        >
          {seller.name.slice(0, 1)}
        </span>
        <div className="min-w-0">
          <h2 className="truncate font-semibold">{seller.name}</h2>
          <p className="truncate text-xs text-muted">{where ?? "Where she lives is not known yet"}</p>
        </div>
      </header>
      <ol aria-label={`Messages with ${seller.name}`} className="flex max-h-[32rem] min-h-64 flex-col gap-3 overflow-y-auto bg-background px-4 py-5">
        {messages.length === 0 ? <li className="m-auto text-sm text-muted">No messages yet.</li> : null}
        {messages.map((message) => (
          <Bubble key={message.id} message={message} sellerName={seller.name} />
        ))}
        <li ref={end} aria-hidden="true" />
      </ol>
    </div>
  );
}

function Bubble({ message, sellerName }: { message: ChatMessage; sellerName: string }) {
  const fromSeller = message.direction === "inbound";
  return (
    <li className={`flex flex-col ${fromSeller ? "items-start" : "items-end"}`}>
      <div
        className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-6 shadow-xs ${
          fromSeller ? "rounded-tl-sm bg-surface" : "rounded-tr-sm bg-accent-soft"
        }`}
      >
        <span className="sr-only">{fromSeller ? `${sellerName}: ` : "OpenStall: "}</span>
        {message.media.map((item, index) => (
          <Media key={index} item={item} />
        ))}
        {message.text ? <p className="break-words whitespace-pre-line">{message.text}</p> : null}
      </div>
      <time dateTime={message.created_at} className="mt-1 px-1 text-xs text-muted">
        {messageTime(message.created_at)} · {CHANNEL_LABELS[message.channel]}
      </time>
    </li>
  );
}

function Media({ item }: { item: ChatMedia }) {
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
  if (item.content_type.startsWith("audio/")) {
    return (
      <audio controls preload="metadata" src={url} aria-label="A voice note" className="mb-2 w-64 max-w-full">
        <a href={url}>Play the voice note</a>
      </audio>
    );
  }
  return null;
}
