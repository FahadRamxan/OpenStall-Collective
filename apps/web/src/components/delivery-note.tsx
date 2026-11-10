import type { ChatMessage } from "@/lib/chats";

/** How far a message of OpenStall's got on WhatsApp, as the line under it says it. */
const WORDS: Record<NonNullable<ChatMessage["delivery"]>, string> = {
  sent: "Sent",
  delivered: "Delivered",
  read: "Read",
  failed: "Not delivered",
};

/** " · Read" and the like, for the line under a message of OpenStall's on WhatsApp; nothing while it is not known. */
export function deliveryWords(message: ChatMessage): string {
  return message.direction === "outbound" && message.delivery ? ` · ${WORDS[message.delivery]}` : "";
}

/**
 * Why WhatsApp could not deliver a message of OpenStall's, in WhatsApp's words, under it, so the page never shows a
 * message as reaching her phone when it did not: WhatsApp taking a message only means it took it, and Meta says
 * later whether it arrived.
 */
export function DeliveryProblem({ message }: { message: ChatMessage }) {
  if (message.direction !== "outbound" || message.delivery !== "failed") return null;
  return (
    <p className="mt-1 max-w-[85%] px-1 text-xs leading-5 break-words text-danger">
      {message.delivery_error ?? "WhatsApp could not deliver it."}
    </p>
  );
}
