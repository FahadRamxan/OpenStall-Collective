import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import type { Metadata } from "next";

import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";

import "./globals.css";

// Geist ships in the geist package (next/font/local), so builds and UI tests work offline.
// They set --font-geist-sans and --font-geist-mono, which globals.css maps to font-sans and font-mono.

export const metadata: Metadata = {
  title: {
    default: "OpenStall Collective",
    template: "%s · OpenStall Collective",
  },
  description: "Small WhatsApp sellers, selling to AI shopping agents, paid through PayPal.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-background font-sans text-foreground">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-surface focus:px-4 focus:py-2 focus:text-sm focus:font-medium focus:shadow"
        >
          Skip to content
        </a>
        <SiteHeader />
        <main id="main" className="flex-1">
          {children}
        </main>
        <SiteFooter />
      </body>
    </html>
  );
}
