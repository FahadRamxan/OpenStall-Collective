import type { Metadata } from "next";

import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Live demo" };

export default function DemoPage() {
  return (
    <ComingSoon title="Live demo">
      Watch one order happen live: a buyer agent&apos;s request, each seller agent&apos;s offer and how it is checked,
      the split across sellers, one PayPal sandbox checkout, and the message each seller receives on their phone.
    </ComingSoon>
  );
}
