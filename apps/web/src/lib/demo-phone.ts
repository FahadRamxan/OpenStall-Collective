"use client";

import { useMemo, useSyncExternalStore } from "react";

/**
 * The browser's "demo phone": a random id that stands for a seller's phone number in the web chat, kept in this
 * browser, with the seller it became once she sent something. Storage can be blocked (private windows), so the id
 * then lives in memory for as long as the page is open.
 */
export type DemoPhone = { id: string; sellerId: string | null };

const KEY = "openstall-demo-phone";
let memory: string | null = null;
const listeners = new Set<() => void>();

function read(): string | null {
  try {
    return window.localStorage.getItem(KEY) ?? memory;
  } catch {
    return memory;
  }
}

function write(value: string | null) {
  memory = value;
  try {
    if (value === null) window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, value);
  } catch {
    // Storage is blocked: the id stays in memory.
  }
  for (const listener of listeners) listener();
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  window.addEventListener("storage", onChange); // another tab started a new seller
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** A fresh id such as demo-3f9a1c7e2b40: random, so nobody can guess another browser's chat. */
export function newDemoPhoneId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  return `demo-${Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

export function parseDemoPhone(raw: string | null): DemoPhone | null {
  if (!raw) return null;
  try {
    const value = JSON.parse(raw) as Partial<DemoPhone>;
    if (typeof value.id !== "string" || !/^[A-Za-z0-9_-]{8,32}$/.test(value.id)) return null;
    return { id: value.id, sellerId: typeof value.sellerId === "string" ? value.sellerId : null };
  } catch {
    return null;
  }
}

/** Keep the demo phone, or forget it (null) to start as a new seller. */
export function saveDemoPhone(phone: DemoPhone | null): void {
  write(phone ? JSON.stringify(phone) : null);
}

/** This browser's demo phone, or null before it has one. Updates when it changes, in any tab. */
export function useDemoPhone(): DemoPhone | null {
  const raw = useSyncExternalStore(subscribe, read, () => null);
  return useMemo(() => parseDemoPhone(raw), [raw]);
}
