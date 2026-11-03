import { apiBaseUrl, apiGet } from "@/lib/api";

/** seeded_demo: made up for the demo, and labelled as such wherever it appears. */
export type DataSource = "seeded_demo" | "live";

export type Product = {
  id: string;
  seller_id: string;
  title: string;
  description: string;
  category: string;
  variants: string[];
  /** Exact, as a string such as "16.00". */
  price_usd: string;
  capacity_per_week: number;
  ship_days: number;
  ship_from_city: string;
  /** Paths on the API, such as /media/seed/priya-cushion-1.svg. */
  photos: string[];
  data_source: DataSource;
};

export type TrustSummary = {
  orders_delivered: number;
  on_time_rate: number;
  dispute_rate: number;
  photo_originality: number;
  score: string;
  data_source: DataSource;
  issued_at: string;
};

export type SellerCard = {
  id: string;
  name: string;
  city: string | null;
  country: string | null;
  language: string | null;
  data_source: DataSource;
  headline: string;
  from_price_usd: string;
  cover_photo: string | null;
};

export type SellerDetail = {
  id: string;
  name: string;
  city: string | null;
  country: string | null;
  language: string | null;
  data_source: DataSource;
  products: Product[];
  trust: TrustSummary | null;
};

export function getSellers(init: RequestInit = {}): Promise<SellerCard[]> {
  return apiGet<SellerCard[]>("/api/sellers", init);
}

export function getSeller(id: string, init: RequestInit = {}): Promise<SellerDetail> {
  return apiGet<SellerDetail>(`/api/sellers/${encodeURIComponent(id)}`, init);
}

/** A photo's address: paths are served by the API, full URLs are used as they are. */
export function mediaUrl(path: string): string {
  return /^https?:\/\//.test(path) ? path : `${apiBaseUrl()}${path}`;
}

const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

/** "$16.00" from "16.00". */
export function formatUsd(amount: string): string {
  return USD.format(Number(amount));
}

function displayName(type: "language" | "region", code: string | null): string | null {
  if (!code) return null;
  try {
    return new Intl.DisplayNames(["en"], { type }).of(code) ?? null;
  } catch {
    return null;
  }
}

/** "Urdu" from "ur". */
export function languageName(code: string | null): string | null {
  return displayName("language", code);
}

/** "Jaipur, India" from the city and its ISO country code. */
export function place(city: string | null, country: string | null): string | null {
  const countryName = displayName("region", country);
  return [city, countryName].filter(Boolean).join(", ") || null;
}

/** "97%" from 0.97. */
export function percent(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

// Swatches for the colour names sellers use, so a listing's variants read at a glance.
const SWATCHES: Record<string, string> = {
  red: "#b23a48",
  teal: "#2a9d8f",
  mustard: "#d9a21b",
  indigo: "#2f3e7a",
  saffron: "#f4a623",
  white: "#f4f1ea",
  black: "#222222",
  natural: "#d9cbb0",
  sage: "#9cb08b",
  rose: "#c76b7e",
  forest: "#2f5d3a",
};

export function swatch(variant: string): string | null {
  return SWATCHES[variant.toLowerCase()] ?? null;
}
