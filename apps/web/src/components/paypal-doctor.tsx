"use client";

import { useEffect, useState } from "react";

import { Badge, type BadgeTone } from "@/components/badge";
import { errorMessage } from "@/lib/api";
import { getDoctor, type CheckStatus, type DoctorReport, type PayPalProduct, type ProductState } from "@/lib/doctor";

/** How long to wait for the doctor: in sandbox mode it asks PayPal for a token and reads the webhook back. */
export const DOCTOR_TIMEOUT_MS = 15_000;

type Load = { state: "loading" } | { state: "loaded"; report: DoctorReport } | { state: "failed"; message: string };

const CHECKS: Record<CheckStatus, { label: string; tone: BadgeTone }> = {
  ok: { label: "OK", tone: "success" },
  warn: { label: "Warning", tone: "warning" },
  fail: { label: "Failed", tone: "danger" },
  skip: { label: "Skipped", tone: "neutral" },
};

const STATES: Record<ProductState, BadgeTone> = {
  proven: "success",
  built: "accent",
  simulated: "warning",
  "not built": "neutral",
};

/**
 * The PayPal doctor and the PayPal products table on /status (prompt 53): whether this setup is ready to hold a
 * buyer's money and pay makers, check by check, and each PayPal product with how far it has got and why. The same
 * report prints in a terminal with `python scripts/doctor.py`.
 */
export function PayPalDoctor() {
  const [load, setLoad] = useState<Load>({ state: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    let unmounted = false;
    const timer = setTimeout(() => controller.abort(), DOCTOR_TIMEOUT_MS);
    getDoctor({ signal: controller.signal })
      .then((report) => {
        if (!unmounted) setLoad({ state: "loaded", report });
      })
      .catch((error: unknown) => {
        if (unmounted) return;
        const message = controller.signal.aborted
          ? `The API did not answer within ${DOCTOR_TIMEOUT_MS / 1000} seconds.`
          : errorMessage(error);
        setLoad({ state: "failed", message });
      })
      .finally(() => clearTimeout(timer));
    return () => {
      unmounted = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, []);

  return (
    <>
      <section aria-labelledby="doctor-heading" className="mt-10" id="paypal-doctor">
        <h2 id="doctor-heading" className="text-xl font-semibold tracking-tight">
          PayPal doctor
        </h2>
        <p className="mt-2 leading-7 text-muted">
          Is this setup ready to hold a buyer&apos;s money and pay the makers? Each check says what to do. It names a
          missing key, never its value, and the same report prints in a terminal with{" "}
          <code className="font-mono text-sm">python scripts/doctor.py</code>.
        </p>
        {load.state === "loading" ? (
          <p role="status" className="mt-5 text-muted">
            Running the PayPal checks…
          </p>
        ) : load.state === "failed" ? (
          <p role="alert" className="mt-5 rounded-xl border border-danger/30 bg-danger-soft p-4 text-foreground">
            Could not run the PayPal doctor: {load.message}
          </p>
        ) : (
          <>
            <p className="mt-4 font-semibold">
              {load.report.healthy ? "Nothing failed." : "Something failed: see the checks marked Failed."}
            </p>
            <ul aria-label="PayPal checks" className="mt-4 divide-y divide-border rounded-xl border border-border bg-surface">
              {load.report.checks.map((check) => (
                <li key={check.name} className="flex flex-col gap-2 p-4 sm:flex-row sm:items-start sm:gap-4 sm:px-5">
                  <span className="sm:w-24 sm:shrink-0">
                    <Badge tone={CHECKS[check.status].tone}>{CHECKS[check.status].label}</Badge>
                  </span>
                  <span className="min-w-0 text-sm leading-6">
                    <span className="font-semibold">{check.name}</span>
                    <span className="block break-words text-muted">{check.detail}</span>
                  </span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      {load.state === "loaded" ? <Products products={load.report.products} /> : null}
    </>
  );
}

function Products({ products }: { products: PayPalProduct[] }) {
  return (
    <section aria-labelledby="products-heading" className="mt-10" id="paypal-products">
      <h2 id="products-heading" className="text-xl font-semibold tracking-tight">
        PayPal products
      </h2>
      <p className="mt-2 leading-7 text-muted">
        Every PayPal product OpenStall uses or plans to, what it does here, and how far it has got: proven on
        PayPal&apos;s real sandbox, built but not yet run there, simulated and labelled, or not built yet.
      </p>
      <div className="mt-5 overflow-hidden rounded-xl border border-border bg-surface">
        <table aria-labelledby="products-heading" className="w-full border-collapse text-left text-sm">
          <thead className="border-b border-border text-xs tracking-wide text-muted uppercase">
            <tr>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">
                Product
              </th>
              <th scope="col" className="px-4 py-3 font-semibold sm:px-5">
                How far it has got
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {products.map((product) => (
              <tr key={product.key} className="align-top">
                <th scope="row" className="px-4 py-4 font-normal sm:px-5">
                  <span className="block font-semibold">{product.name}</span>
                  <span className="mt-1 block leading-6 text-muted">{product.used_for}</span>
                  {product.calls.length ? (
                    <span className="mt-1 block font-mono text-xs break-all text-muted">
                      {product.calls.join(" · ")}
                    </span>
                  ) : null}
                </th>
                <td className="px-4 py-4 sm:px-5">
                  <Badge tone={STATES[product.state]} wrap>
                    {product.state_words}
                  </Badge>
                  <p className="mt-2 leading-6 text-muted">{product.evidence}</p>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
