import { apiGet } from "@/lib/api";

/** ok, warn, fail, or skip: not checked in this mode, or not until another check passes. */
export type CheckStatus = "ok" | "warn" | "fail" | "skip";

/** One of the PayPal doctor's checks, with what to do in words (GET /api/paypal/doctor). */
export type DoctorCheck = { name: string; status: CheckStatus; detail: string };

/** How far a PayPal product has got: proven on the sandbox, built, simulated, or not built yet. */
export type ProductState = "proven" | "built" | "simulated" | "not built";

/** A PayPal product OpenStall uses or plans to, and its evidence (packages/paypal/openstall_paypal/products.py). */
export type PayPalProduct = {
  key: string;
  name: string;
  used_for: string;
  calls: string[];
  code: string;
  state: ProductState;
  state_words: string;
  evidence: string;
  prompts: string;
};

/** The PayPal doctor's report (prompt 53): its checks, whether any failed, and the products table. */
export type DoctorReport = {
  mode: "fake" | "sandbox";
  healthy: boolean;
  checks: DoctorCheck[];
  products: PayPalProduct[];
};

export function getDoctor(init: RequestInit = {}): Promise<DoctorReport> {
  return apiGet<DoctorReport>("/api/paypal/doctor", init);
}
