import type { Metadata } from "next";

import { ComingSoon } from "@/components/coming-soon";

export const metadata: Metadata = { title: "Dashboard" };

export default function DashboardPage() {
  return (
    <ComingSoon title="Dashboard">
      Orders, payouts, tracking, trust passports and Demand Radar tips, in tables that update as things happen.
    </ComingSoon>
  );
}
