import type { Metadata } from "next";

import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Seller chat" };

export default function SellerChatPage() {
  return (
    <ComingSoon title="Seller chat">
      The seller&apos;s side of OpenStall, in your browser. Send photos and a voice note, answer a few short
      questions, say yes, and the listing goes live. It works the same way as the WhatsApp chat, so you can try it
      without WhatsApp.
    </ComingSoon>
  );
}
