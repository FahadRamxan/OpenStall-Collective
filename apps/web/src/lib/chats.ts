import { apiBaseUrl, apiFetch, apiGet, apiPost, ApiError } from "@/lib/api";

export type ChatChannel = "whatsapp" | "web";

export type ChatSeller = { id: string; name: string; city: string | null; country: string | null };

/** A kept photo or voice note (`url`, a path on the API), or a file that was not kept and why (`refused`). */
export type ChatMedia = { url: string | null; content_type: string; size: number | null; refused: string | null };

export type ChatMessage = {
  id: string;
  direction: "inbound" | "outbound";
  channel: ChatChannel;
  text: string | null;
  media: ChatMedia[];
  /**
   * What her voice notes said, word for word as she said them (never translated), and the language it was heard in
   * (ISO 639-1). Null when the message had no voice note, or none could be heard.
   */
  transcript?: string | null;
  language?: string | null;
  created_at: string;
};

export type ChatSummary = {
  seller: ChatSeller;
  channel: ChatChannel;
  state: string;
  updated_at: string;
  last_text: string | null;
  messages: number;
};

/**
 * A seller's listing as far as her chat has told it, before she confirms it: not live for buyers. `words`: the words
 * she used for each number and her city. `missing`: the fields still to ask her for, in the spec's order.
 */
export type ListingDraft = {
  title: string | null;
  description: string | null;
  category: string | null;
  variants: string[];
  price_usd: string | null;
  capacity_per_week: number | null;
  ship_days: number | null;
  ship_from_city: string | null;
  photos: string[];
  /** Her limits, only for her own seller agent: the lowest price she would take for one, and her fewest days. */
  floor_price_usd?: string | null;
  min_lead_days?: number | null;
  words: Partial<Record<string, string>>;
  /** What is still to ask her: the listing's fields in the spec's order, then her limits. */
  missing: string[];
  /** The field she was asked about last, which her next message answers. */
  asked?: string | null;
  /** Nothing is left to ask: she was sent all of it, and her yes would publish it. */
  confirming?: boolean;
};

/** Her listing once her yes published it from her chat: live for buyers' agents. */
export type LiveListing = {
  product_id: string;
  title: string;
  price_usd: string;
  /** Her stall page on this web app. */
  stall_path: string;
};

export type Conversation = {
  seller: ChatSeller;
  messages: ChatMessage[];
  /** Her listing draft, while she is making one and until her yes. */
  draft?: ListingDraft | null;
  /** The listing her yes published from her chat. */
  listing?: LiveListing | null;
  /** Test mode only, for a maker with no phone of her own (the seeded makers): this page can play her. */
  playable?: boolean;
};

/** Every conversation with at least one message, the most recent first. */
export function getChats(init: RequestInit = {}): Promise<ChatSummary[]> {
  return apiGet<ChatSummary[]>("/api/chats", init);
}

/** One seller's messages on every channel, oldest first. */
export function getConversation(sellerId: string, init: RequestInit = {}): Promise<Conversation> {
  return apiGet<Conversation>(`/api/chats/${encodeURIComponent(sellerId)}`, init);
}

/** What the web chat answers: who the seller is now, her message's id, and OpenStall's replies. */
export type WebChatReply = { seller_id: string; message_id: string; replies: string[] };

/** A message from the browser's demo phone: text, photos and voice notes, handled exactly as on WhatsApp. */
export function sendWebMessage(sender: string, text: string, files: File[]): Promise<WebChatReply> {
  const form = new FormData();
  form.set("sender", sender);
  form.set("text", text);
  for (const file of files) form.append("files", file);
  return apiFetch<WebChatReply>("/api/seller-chat/messages", { method: "POST", body: form });
}

/** Sample files the web chat can attach, as paths on the API: in test mode only, null otherwise. */
export type ChatSamples = { voice_note: string | null; photo: string | null };

export function getSamples(init: RequestInit = {}): Promise<ChatSamples> {
  return apiGet<ChatSamples>("/api/seller-chat/samples", init);
}

/** A sample file from the API, as a file to attach and send like one the seller chose. */
export async function fetchSample(path: string, name: string): Promise<File> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`);
  } catch {
    throw new ApiError(`Could not reach the OpenStall API at ${apiBaseUrl()}. Check that it is running.`, null);
  }
  if (!response.ok) throw new ApiError(`The sample could not be loaded (HTTP ${response.status}).`, response.status);
  const type = response.headers.get("Content-Type")?.split(";", 1)[0].trim() || "application/octet-stream";
  return new File([await response.arrayBuffer()], name, { type });
}

/**
 * Test mode only: a message as if this maker sent it, with fake mode's courier receipt photo if `receipt`. It takes the
 * path a real message takes; the API refuses it (404) outside test mode.
 */
export function playSeller(sellerId: string, text: string, receipt: boolean): Promise<WebChatReply> {
  return apiPost<WebChatReply>(`/api/dev/sellers/${encodeURIComponent(sellerId)}/messages`, { text, receipt });
}

export const CHANNEL_LABELS: Record<ChatChannel, string> = { whatsapp: "WhatsApp", web: "Web chat" };

const CLOCK = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit" });

/** "14:05" in the viewer's own time zone. */
export function messageTime(iso: string): string {
  const moment = new Date(iso);
  return Number.isNaN(moment.getTime()) ? "" : CLOCK.format(moment);
}
