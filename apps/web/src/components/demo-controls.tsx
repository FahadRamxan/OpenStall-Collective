"use client";

import Link from "next/link";
import { useState } from "react";

import { useEventStream } from "@/hooks/use-event-stream";
import { ApiError, errorMessage } from "@/lib/api";
import { formatUsd } from "@/lib/catalog";
import { resetDemo, runAgent, runDemo, STEPS, stepsDone, type DemoAgentRun, type DemoRun } from "@/lib/demo";

type Busy = "run" | "agent" | "reset" | null;

/**
 * The /demo page's controls: run the story's request with the scripted buyer agent (through the real MCP
 * storefront), or with a buyer's AI agent that chooses the tools itself (Claude in sandbox mode, test mode's
 * stand-in here), or put the demo world back as seeded. The stepper follows the run live from the event stream:
 * Search, Quote, Offers, Allocation, Approval. In sandbox mode the API asks for the demo token, and a field for it
 * appears; the token is kept only while the page is open.
 */
export function DemoControls() {
  const { events } = useEventStream();
  const done = stepsDone(events);
  const [busy, setBusy] = useState<Busy>(null);
  const [confirming, setConfirming] = useState(false);
  const [run, setRun] = useState<DemoRun | null>(null);
  const [agentRun, setAgentRun] = useState<DemoAgentRun | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needsToken, setNeedsToken] = useState(false);
  const [token, setToken] = useState("");

  async function act(kind: "run" | "agent" | "reset") {
    setBusy(kind);
    setError(null);
    setMessage(null);
    try {
      if (kind === "run") {
        const result = await runDemo(token || null);
        setRun(result);
        setAgentRun(null);
      } else if (kind === "agent") {
        const result = await runAgent(token || null);
        setAgentRun(result);
        setRun(null);
      } else {
        await resetDemo(token || null);
        setRun(null);
        setAgentRun(null);
        setMessage("The demo is reset: the seeded makers and the story's draft order are back.");
      }
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 401) setNeedsToken(true);
      setError(errorMessage(reason));
    } finally {
      setBusy(null);
      setConfirming(false);
    }
  }

  return (
    <section aria-labelledby="controls-heading" className="mt-10 rounded-2xl border border-border bg-surface p-5 sm:p-6">
      <h2 id="controls-heading" className="text-xl font-semibold tracking-tight">
        Run the story
      </h2>
      <p className="mt-1 leading-7 text-muted">
        A buyer agent asks OpenStall&apos;s MCP storefront for 40 hand-embroidered cushion covers, at most $30 each,
        due in 30 days, and gets the approval link for a person. Run the scripted one, or an AI agent that reads the
        request in words and chooses the tools itself. Neither can pay: you approve on the link.
      </p>

      <ol aria-label="The buyer agent's steps" className="mt-4 flex flex-wrap gap-2 text-sm">
        {STEPS.map((step, index) => {
          const state = done === null || index > done ? "waiting" : index < done ? "done" : "now";
          return (
            <li
              key={step.name}
              aria-current={state === "now" ? "step" : undefined}
              data-state={state}
              className={`rounded-full px-3 py-1 ${
                state === "done"
                  ? "bg-success-soft text-success"
                  : state === "now"
                    ? "bg-accent-soft font-semibold text-accent"
                    : "bg-background text-muted"
              }`}
            >
              {state === "done" ? "✓ " : null}
              {step.name}
            </li>
          );
        })}
      </ol>

      {needsToken ? (
        <label className="mt-4 block text-sm font-medium">
          Demo token (sandbox mode)
          <input
            type="password"
            autoComplete="off"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            className="mt-1 block w-full max-w-sm rounded-lg border border-border bg-background px-3 py-2"
          />
        </label>
      ) : null}

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => act("run")}
          disabled={busy !== null}
          className="inline-flex min-h-11 items-center rounded-full bg-accent px-5 text-sm font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
        >
          {busy === "run" ? "Running…" : "Run the demo request"}
        </button>
        <button
          type="button"
          onClick={() => act("agent")}
          disabled={busy !== null}
          className="inline-flex min-h-11 items-center rounded-full border border-accent px-5 text-sm font-semibold text-accent hover:bg-accent-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
        >
          {busy === "agent" ? "The AI agent is working…" : "Run it with an AI agent"}
        </button>
        {confirming ? (
          <span role="group" aria-label="Confirm the reset" className="inline-flex flex-wrap items-center gap-2">
            <span className="text-sm">Remove every order, quote and offer?</span>
            <button
              type="button"
              onClick={() => act("reset")}
              disabled={busy !== null}
              className="inline-flex min-h-11 items-center rounded-full bg-danger px-4 text-sm font-semibold text-white disabled:opacity-60"
            >
              {busy === "reset" ? "Resetting…" : "Yes, reset"}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="inline-flex min-h-11 items-center rounded-full border border-border px-4 text-sm font-semibold"
            >
              Cancel
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={busy !== null}
            className="inline-flex min-h-11 items-center rounded-full border border-border px-5 text-sm font-semibold hover:bg-background disabled:opacity-60"
          >
            Reset demo
          </button>
        )}
      </div>

      <div role="status" className="mt-3 text-sm leading-6">
        {run ? (
          <p>
            Order <span className="font-mono">{run.order_id}</span> drafted: {formatUsd(run.total_usd)}.{" "}
            <Link
              href={`/approve/${encodeURIComponent(run.order_id)}`}
              className="font-semibold text-accent underline underline-offset-4"
            >
              Open its approval page
            </Link>
          </p>
        ) : agentRun ? (
          <AgentRunView run={agentRun} />
        ) : message ? (
          <p>{message}</p>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      ) : null}
    </section>
  );
}

/** What the buyer's AI agent did: each tool it chose, and its answer to the person, with the approval link. */
function AgentRunView({ run }: { run: DemoAgentRun }) {
  const answer = run.said.at(-1);
  return (
    <div className="space-y-2">
      <p>
        <span className="font-semibold">The buyer&apos;s AI agent</span> ({run.agent}) chose {run.steps.length}{" "}
        {run.steps.length === 1 ? "tool" : "tools"}:
      </p>
      <ol aria-label="The tools the AI agent chose" className="list-decimal space-y-0.5 pl-5">
        {run.steps.map((step, index) => (
          <li key={`${step.tool}-${index}`}>
            <span className="font-mono">{step.tool}</span>: <span className={step.ok ? "" : "text-danger"}>{step.summary}</span>
          </li>
        ))}
      </ol>
      {answer ? (
        <blockquote className="border-l-2 border-accent pl-3 text-muted">
          <span className="sr-only">The agent said: </span>
          {answer}
        </blockquote>
      ) : null}
      {run.order_id && run.total_usd ? (
        <p>
          Order <span className="font-mono">{run.order_id}</span> drafted: {formatUsd(run.total_usd)}.{" "}
          <Link
            href={`/approve/${encodeURIComponent(run.order_id)}`}
            className="font-semibold text-accent underline underline-offset-4"
          >
            Open its approval page
          </Link>
        </p>
      ) : (
        <p className="text-danger">The agent stopped without drafting an order.</p>
      )}
    </div>
  );
}
