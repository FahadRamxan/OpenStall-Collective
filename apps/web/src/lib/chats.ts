import { apiFetch, apiGet, apiPost } from "@/lib/api";

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

export type Conversation = {
  seller: ChatSeller;
  messages: ChatMessage[];
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
