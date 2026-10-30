"use client";

import { useEffect, useState } from "react";

import { getHealth } from "@/lib/api";

/** How long to wait for /health, so a hung API or a slow cold start on the hosted demo cannot leave it checking. */
export const HEALTH_CHECK_TIMEOUT_MS = 10_000;

type Status = "checking" | "online" | "offline";

const DOT_CLASSES: Record<Status, string> = {
  checking: "bg-border",
  online: "bg-emerald-500",
  offline: "bg-red-500",
};

// Every visitor reads this line, so it is written for them. Developers find the failed request in the browser console.
const MESSAGES: Record<Status, string> = {
  checking: "Checking the API…",
  online: "API online",
  offline: "API offline. Try again in a minute.",
};

/** Whether this browser can reach the API: proves the API address and CORS are set up right. */
export function ApiStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    const controller = new AbortController();
    let unmounted = false;
    // A timer rather than AbortSignal.timeout or AbortSignal.any, which older browsers lack.
    const timer = setTimeout(() => controller.abort(), HEALTH_CHECK_TIMEOUT_MS);
    getHealth({ signal: controller.signal })
      .then(() => setStatus("online"))
      .catch(() => {
        if (!unmounted) setStatus("offline");
      })
      .finally(() => clearTimeout(timer));
    return () => {
      unmounted = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, []);

  return (
    <p role="status" className="flex items-start gap-2">
      <span aria-hidden="true" className={`mt-1.5 size-2 shrink-0 rounded-full ${DOT_CLASSES[status]}`} />
      <span>{MESSAGES[status]}</span>
    </p>
  );
}
