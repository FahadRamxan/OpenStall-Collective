import type { Metadata } from "next";
import { Suspense } from "react";

import { SellerChatView } from "@/components/seller-chat-view";

export const metadata: Metadata = { title: "Seller chat" };

export default function SellerChatPage() {
  return (
    <section className="mx-auto max-w-5xl px-4 py-10 sm:px-6 sm:py-14">
      <div className="max-w-2xl">
        <h1 className="text-3xl font-semibold tracking-tight text-balance sm:text-4xl">Seller chat</h1>
        <p className="mt-3 text-lg leading-8 text-muted">
          The sellers&apos; side of OpenStall. Be a seller from your demo phone, with the same chat makers have on
          WhatsApp, or watch what they send: photos, voice notes and OpenStall&apos;s answers, as they arrive.
        </p>
      </div>
      <div className="mt-8">
        {/* The chosen seller is in the query string, which is only known per request. */}
        <Suspense fallback={null}>
          <SellerChatView />
        </Suspense>
      </div>
    </section>
  );
}
