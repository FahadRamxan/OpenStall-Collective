"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/badge";
import { errorMessage } from "@/lib/api";
import { getSellers, type SellerCard } from "@/lib/catalog";
import {
  getPassportKey,
  getTrustCard,
  verifyInBrowser,
  verifyWithOpenStall,
  type PassportKey,
  type TrustCard,
} from "@/lib/passports";

/** The numbers a person may change, with how each is labelled. */
const NUMBERS: [keyof TrustCard, string][] = [
  ["orders_delivered", "Orders delivered"],
  ["on_time_rate", "On-time rate"],
  ["dispute_rate", "Dispute rate"],
  ["photo_originality", "Photo originality"],
  ["score", "Score"],
  ["live_deliveries", "Through OpenStall"],
];

type Check =
  | { state: "idle" }
  | { state: "checking" }
  | { state: "done"; browser: boolean | null; openStall: boolean; reason: string }
  | { state: "failed"; message: string };

/**
 * The tamper check (spec 3.7): a maker's trust card, signed by OpenStall, checked live. The browser checks the
 * signature itself with OpenStall's public key, and OpenStall's verify endpoint gives its own answer. Change any number
 * and check again: the signature no longer matches. Put it back, and it does.
 */
export function TamperCheck() {
  const [makers, setMakers] = useState<SellerCard[] | null>(null);
  const [sellerId, setSellerId] = useState("");
  const [key, setKey] = useState<PassportKey | null>(null);
  const [signed, setSigned] = useState<TrustCard | null>(null);
  const [card, setCard] = useState<TrustCard | null>(null);
  const [check, setCheck] = useState<Check>({ state: "idle" });
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([getSellers({ signal: controller.signal }), getPassportKey({ signal: controller.signal })])
      .then(([sellers, passportKey]) => {
        setMakers(sellers);
        setKey(passportKey);
        setSellerId((current) => current || (sellers.find((seller) => seller.id === "s_priya") ?? sellers[0])?.id || "");
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setProblem(errorMessage(error));
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!sellerId || !key) return;
    const controller = new AbortController();
    getTrustCard(sellerId, { signal: controller.signal })
      .then((loaded) => {
        setSigned(loaded);
        setCard(loaded);
        setProblem(null);
        void run(loaded, key);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setSigned(null);
        setCard(null);
        setProblem(errorMessage(error));
      });
    return () => controller.abort();
  }, [sellerId, key]);

  async function run(toCheck: TrustCard, passportKey: PassportKey) {
    setCheck({ state: "checking" });
    try {
      const [browser, verdict] = await Promise.all([
        verifyInBrowser(toCheck, passportKey.public_key),
        verifyWithOpenStall(toCheck),
      ]);
      setCheck({ state: "done", browser, openStall: verdict.valid, reason: verdict.reason });
    } catch (error) {
      setCheck({ state: "failed", message: errorMessage(error) });
    }
  }

  const changed = card !== null && signed !== null && NUMBERS.some(([field]) => card[field] !== signed[field]);
  const name = makers?.find((maker) => maker.id === sellerId)?.name ?? "her";
  return (
    <section aria-labelledby="tamper-heading" className="mt-10">
      <h2 id="tamper-heading" className="text-xl font-semibold tracking-tight">
        Check a trust passport
      </h2>
      <p className="mt-1 leading-7 text-muted">
        Each maker&apos;s trust card is signed by OpenStall. Your browser checks the signature itself, with OpenStall&apos;s
        public key. Change any number and check again: the signature no longer matches.
      </p>
      {key?.test_mode ? (
        <p className="mt-2 flex flex-wrap items-center gap-2 text-sm text-muted">
          <Badge tone="warning">Test mode</Badge>
          Signed with a fixed test key that anyone can rebuild: nothing it signs is trusted anywhere real.
        </p>
      ) : null}
      {problem ? (
        <p role="alert" className="mt-3 text-sm text-danger">
          The trust card could not be loaded: {problem}
        </p>
      ) : null}
      {makers && makers.length > 0 ? (
        <div className="mt-4 rounded-xl border border-border bg-surface p-4 sm:p-5">
          <label className="flex flex-wrap items-center gap-3 text-sm font-medium">
            Maker
            <select
              value={sellerId}
              onChange={(event) => setSellerId(event.target.value)}
              className="min-h-11 rounded-lg border border-border bg-background px-3"
            >
              {makers.map((maker) => (
                <option key={maker.id} value={maker.id}>
                  {maker.name}
                </option>
              ))}
            </select>
          </label>
          {card ? (
            <form
              aria-label={`${name}'s trust card`}
              className="mt-4"
              onSubmit={(event) => {
                event.preventDefault();
                if (key) void run(card, key);
              }}
            >
              <div className="grid gap-3 sm:grid-cols-3">
                {NUMBERS.map(([field, label]) => (
                  <label key={field} className="flex flex-col gap-1 text-sm">
                    <span className="font-medium text-muted">{label}</span>
                    <input
                      type="number"
                      step="any"
                      inputMode="decimal"
                      value={String(card[field])}
                      onChange={(event) => {
                        const value = Number(event.target.value);
                        setCard({ ...card, [field]: Number.isFinite(value) ? value : 0 });
                        setCheck({ state: "idle" });
                      }}
                      className={`min-h-11 rounded-lg border px-3 tabular-nums ${
                        signed && card[field] !== signed[field] ? "border-danger bg-danger-soft" : "border-border bg-background"
                      }`}
                    />
                  </label>
                ))}
              </div>
              <p className="mt-3 text-xs break-all text-muted">
                <span className="font-semibold">Signature</span>{" "}
                <span className="font-mono">{card.signature}</span>
              </p>
              <div className="mt-4 flex flex-wrap gap-3">
                <button
                  type="submit"
                  disabled={check.state === "checking"}
                  className="inline-flex min-h-11 items-center rounded-full bg-accent px-5 text-sm font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
                >
                  Check the signature
                </button>
                <button
                  type="button"
                  disabled={!changed}
                  onClick={() => {
                    if (!signed || !key) return;
                    setCard(signed);
                    void run(signed, key);
                  }}
                  className="inline-flex min-h-11 items-center rounded-full border border-border px-5 text-sm font-semibold hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
                >
                  Put it back
                </button>
              </div>
            </form>
          ) : null}
          <CheckResult check={check} changed={changed} />
        </div>
      ) : makers ? (
        <p className="mt-4 text-muted">No maker has a trust card yet.</p>
      ) : problem ? null : (
        <p aria-busy="true" className="mt-4 text-muted">
          Loading trust cards…
        </p>
      )}
    </section>
  );
}

function CheckResult({ check, changed }: { check: Check; changed: boolean }) {
  if (check.state === "idle") {
    return (
      <p role="status" className="mt-4 text-sm text-muted">
        {changed ? "Changed. Check the signature again." : " "}
      </p>
    );
  }
  if (check.state === "checking") {
    return (
      <p role="status" className="mt-4 text-sm text-muted">
        Checking the signature…
      </p>
    );
  }
  if (check.state === "failed") {
    return (
      <p role="alert" className="mt-4 text-sm text-danger">
        The signature could not be checked: {check.message}
      </p>
    );
  }
  const valid = check.browser ?? check.openStall;
  return (
    <div role="status" className="mt-4 text-sm">
      <p className={`text-base font-semibold ${valid ? "text-success" : "text-danger"}`}>
        {valid
          ? "Signature valid: OpenStall signed exactly this card."
          : "Signature does not match: this card was changed after OpenStall signed it."}
      </p>
      <p className="mt-1 text-muted">
        {check.browser === null
          ? "This browser cannot check Ed25519 itself; this is OpenStall's own check."
          : `Checked in your browser with OpenStall's public key: ${check.browser ? "valid" : "does not match"}.`}{" "}
        OpenStall&apos;s own check: {check.openStall ? "valid" : "does not match"}.
      </p>
    </div>
  );
}
