import { apiGet, apiPost } from "@/lib/api";

/** The order as the buyer sees it on the simulated PayPal page (fake mode only). */
export type FakePayPalOrder = {
  token: string;
  status: "CREATED" | "PAYER_ACTION_REQUIRED" | "SAVED" | "APPROVED" | "VOIDED" | "COMPLETED";
  order_id: string;
  total_usd: string;
  shares: { reference_id: string; description: string; amount_usd: string }[];
  cancel_url: string;
  /** "venmo": the page stands in for Venmo (prompt 57). */
  funding?: "paypal" | "venmo";
};

export function getFakePayPalOrder(token: string, init: RequestInit = {}): Promise<FakePayPalOrder> {
  return apiGet<FakePayPalOrder>(`/api/dev/fake-paypal/${encodeURIComponent(token)}`, init);
}

/** The buyer approves. Like PayPal, the answer is where to send them next: the order's return page. */
export function approveFakePayPalOrder(token: string): Promise<{ redirect_url: string }> {
  return apiPost<{ redirect_url: string }>(`/api/dev/fake-paypal/${encodeURIComponent(token)}/approve`, {});
}
