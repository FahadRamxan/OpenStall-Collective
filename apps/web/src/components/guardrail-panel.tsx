"use client";

import { useEffect, useState } from "react";

import { Badge, type BadgeTone } from "@/components/badge";
import { ApiError, errorMessage } from "@/lib/api";
import { getAttacks, runAttack, runEveryAttack, type Attack, type AttackResult, type Outcome } from "@/lib/guardrails";

const RESULT_WORDS: Record<AttackResult, string> = {
  refused: "Refused",
  got_through: "Got through",
  not_tried: "Not tried",
};
const RESULT_TONES: Record<AttackResult, BadgeTone> = { refused: "success", got_through: "danger", not_tried: "neutral" };

/**
 * Try to break it (prompt 40): each attack really tries something OpenStall must never allow, through the same code a
 * real request goes through, and shows what refused it. Nothing an attack touches is kept, and each refusal appears in
 * the live feed. In sandbox mode the API asks for the demo token, as the demo controls do.
 */
export function GuardrailPanel() {
  const [attacks, setAttacks] = useState<Attack[] | null>(null);
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({});
  const [busy, setBusy] = useState<string | null>(null); // "all", or the key of the attack being tried
  const [problem, setProblem] = useState<string | null>(null);
  const [needsToken, setNeedsToken] = useState(false);
  const [token, setToken] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getAttacks({ signal: controller.signal })
      .then(setAttacks)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setProblem(errorMessage(error));
      });
    return () => controller.abort();
  }, []);

  async function attempt(key: string | null) {
    setBusy(key ?? "all");
    setProblem(null);
    try {
      const results = key ? [await runAttack(key, token || null)] : await runEveryAttack(token || null);
      setOutcomes((current) => ({ ...current, ...Object.fromEntries(results.map((outcome) => [outcome.key, outcome])) }));
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) setNeedsToken(true);
      setProblem(errorMessage(error));
    } finally {
      setBusy(null);
    }
  }

  const tried = Object.values(outcomes);
  const refused = tried.filter((outcome) => outcome.result === "refused").length;
  return (
    <section aria-labelledby="guardrails-heading" className="mt-10">
      <h2 id="guardrails-heading" className="text-xl font-semibold tracking-tight">
        Try to break it
      </h2>
      <p className="mt-1 leading-7 text-muted">
        Each attack really tries something OpenStall must never allow, through the same code a real request goes
        through. Nothing it touches is kept, and each refusal appears in the live feed.
      </p>
      {attacks === null ? (
        problem ? (
          <p role="alert" className="mt-3 text-sm text-danger">
            The attacks could not be loaded: {problem}
          </p>
        ) : (
          <p aria-busy="true" className="mt-4 text-muted">
            Loading the attacks…
          </p>
        )
      ) : (
        <div className="mt-4 rounded-xl border border-border bg-surface p-4 sm:p-5">
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => attempt(null)}
              className="inline-flex min-h-11 items-center rounded-full bg-accent px-5 text-sm font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
            >
              {busy === "all" ? "Trying every attack…" : "Try every attack"}
            </button>
            <p role="status" className="text-sm font-medium">
              {tried.length > 0 ? (
                <span className={refused === tried.length ? "text-success" : "text-danger"}>
                  {refused} of {tried.length} {tried.length === 1 ? "attack" : "attacks"} refused
                </span>
              ) : null}
            </p>
          </div>
          {needsToken ? (
            <label className="mt-3 flex flex-col gap-1 text-sm font-medium sm:max-w-sm">
              Demo token (sandbox mode)
              <input
                type="password"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                autoComplete="off"
                className="min-h-11 rounded-lg border border-border bg-background px-3"
              />
            </label>
          ) : null}
          {problem ? (
            <p role="alert" className="mt-3 text-sm text-danger">
              Not tried: {problem}
            </p>
          ) : null}
          <ul aria-label="Attacks" className="mt-4 divide-y divide-border border-t border-border">
            {attacks.map((attack) => {
              const outcome = outcomes[attack.key];
              return (
                <li key={attack.key} aria-label={attack.name} className="py-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold">{attack.name}</p>
                      <p className="mt-0.5 text-sm text-muted">{attack.guard}</p>
                    </div>
                    <button
                      type="button"
                      disabled={busy !== null}
                      onClick={() => attempt(attack.key)}
                      aria-label={`Try it: ${attack.name}`}
                      className="inline-flex min-h-11 items-center rounded-full border border-border px-4 text-sm font-semibold hover:bg-background focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
                    >
                      {busy === attack.key ? "Trying…" : "Try it"}
                    </button>
                  </div>
                  {outcome ? (
                    <div className="mt-2 text-sm leading-6">
                      <p className="text-muted">{outcome.tried}</p>
                      <p className="mt-1 flex flex-wrap items-start gap-2">
                        <Badge tone={RESULT_TONES[outcome.result]}>{RESULT_WORDS[outcome.result]}</Badge>
                        <span className="min-w-0 flex-1">{outcome.reason}</span>
                      </p>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}
