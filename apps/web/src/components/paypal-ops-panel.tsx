"use client";

import { useEffect, useState, type FormEvent } from "react";

import { Badge } from "@/components/badge";
import { errorMessage } from "@/lib/api";
import {
  askOpsAgent,
  checkWithPayPal,
  getOpsTools,
  type OpsAnswer,
  type OpsCheck,
  type OpsTools,
} from "@/lib/paypal-ops";

export const SAMPLE_QUESTION = "Is the latest order's money still held at PayPal, and is there any dispute?";

type Load<T> = { state: "idle" } | { state: "busy" } | { state: "done"; value: T } | { state: "failed"; message: string };

const BUTTON =
  "inline-flex min-h-11 items-center rounded-full bg-accent px-5 text-sm font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60";

/**
 * The PayPal ops agent (prompt 55): OpenStall's records checked against PayPal through PayPal's own MCP server, and an
 * operator's question answered by an AI agent that is offered only the server's tools that read. In test mode the
 * server is a stand-in answering from the simulated PayPal, and says so.
 */
export function PayPalOpsPanel() {
  const [tools, setTools] = useState<Load<OpsTools>>({ state: "busy" });
  const [check, setCheck] = useState<Load<OpsCheck>>({ state: "idle" });
  const [answer, setAnswer] = useState<Load<OpsAnswer>>({ state: "idle" });
  const [question, setQuestion] = useState(SAMPLE_QUESTION);

  useEffect(() => {
    let current = true;
    getOpsTools()
      .then((value) => current && setTools({ state: "done", value }))
      .catch((error: unknown) => current && setTools({ state: "failed", message: errorMessage(error) }));
    return () => {
      current = false;
    };
  }, []);

  async function runCheck() {
    setCheck({ state: "busy" });
    try {
      setCheck({ state: "done", value: await checkWithPayPal() });
    } catch (error) {
      setCheck({ state: "failed", message: errorMessage(error) });
    }
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    setAnswer({ state: "busy" });
    try {
      setAnswer({ state: "done", value: await askOpsAgent(question) });
    } catch (error) {
      setAnswer({ state: "failed", message: errorMessage(error) });
    }
  }

  const offered = tools.state === "done" ? tools.value.tools.filter((tool) => tool.offered) : [];
  const writes = tools.state === "done" ? tools.value.tools.filter((tool) => !tool.reads) : [];
  return (
    <section aria-labelledby="ops-heading" className="mt-12">
      <h2 id="ops-heading" className="text-xl font-semibold tracking-tight">
        PayPal ops agent
      </h2>
      <p className="mt-2 max-w-3xl leading-7 text-muted">
        OpenStall&apos;s own records checked against PayPal through PayPal&apos;s own MCP server, which offers
        PayPal&apos;s APIs as tools. The agent is given only the tools that read: it can never pay, refund or accept a
        claim.
      </p>
      {tools.state === "done" ? (
        <div className="mt-3 text-sm leading-6">
          <p>
            <span className="font-semibold">{tools.value.server}.</span>
          </p>
          <p className="mt-1 flex flex-wrap items-center gap-1">
            <span>Offered:</span>
            {offered.map((tool) => (
              <code key={tool.name} className="rounded bg-surface px-1.5 py-0.5 font-mono text-xs break-all">
                {tool.name}
              </code>
            ))}
          </p>
          <p className="mt-1 break-words text-muted">
            Never offered: {writes.length} tool{writes.length === 1 ? "" : "s"} that change something at PayPal (
            {writes.map((tool) => tool.name).join(", ")}).
          </p>
        </div>
      ) : tools.state === "failed" ? (
        <p role="alert" className="mt-3 text-sm text-danger">
          {tools.message}
        </p>
      ) : (
        <p role="status" className="mt-3 text-sm text-muted">
          Connecting to PayPal&apos;s MCP server…
        </p>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface p-5">
          <button type="button" onClick={runCheck} disabled={check.state === "busy"} className={BUTTON}>
            {check.state === "busy" ? "Checking with PayPal…" : "Check the latest order with PayPal"}
          </button>
          {check.state === "done" ? (
            <>
              <p className="mt-4 font-semibold">
                Order <span className="font-mono">{check.value.order_id}</span>:{" "}
                {check.value.agrees ? "PayPal agrees on every line." : "PayPal differs on a line below."}
              </p>
              <ul aria-label="OpenStall beside PayPal" className="mt-3 divide-y divide-border text-sm">
                {check.value.findings.map((finding) => (
                  <li key={finding.check} className="flex flex-col gap-1 py-2 sm:flex-row sm:items-start sm:gap-3">
                    <span className="sm:w-20 sm:shrink-0">
                      <Badge tone={finding.ok ? "success" : "danger"}>{finding.ok ? "Agrees" : "Differs"}</Badge>
                    </span>
                    <span className="min-w-0 break-words">
                      <span className="font-semibold">{finding.check}</span>
                      <span className="block text-muted">
                        OpenStall: {finding.ours}. PayPal: {finding.paypal}.
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </>
          ) : check.state === "failed" ? (
            <p role="alert" className="mt-3 text-sm text-danger">
              {check.message}
            </p>
          ) : null}
        </div>

        <form onSubmit={ask} aria-label="Ask the ops agent" className="rounded-xl border border-border bg-surface p-5">
          <label htmlFor="ops-question" className="text-sm font-semibold">
            Your question
          </label>
          <textarea
            id="ops-question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            maxLength={500}
            rows={2}
            className="mt-2 w-full rounded-lg border border-border bg-background p-3 text-sm focus-visible:outline-2 focus-visible:outline-accent"
          />
          <button type="submit" disabled={answer.state === "busy" || question.trim().length < 3} className={`mt-3 ${BUTTON}`}>
            {answer.state === "busy" ? "The agent is reading PayPal…" : "Ask the ops agent"}
          </button>
          {answer.state === "done" ? (
            <div className="mt-4 text-sm">
              <ol aria-label="What the agent read" className="space-y-1">
                {answer.value.steps.map((step, index) => (
                  <li key={`${step.tool}-${index}`}>
                    <code className="font-mono text-xs">{step.tool}</code>{" "}
                    <span className={step.ok ? "text-muted" : "text-danger"}>{step.summary}</span>
                  </li>
                ))}
              </ol>
              <p className="mt-3 leading-6">
                <span className="font-semibold">{answer.value.agent}:</span> {answer.value.answer}
              </p>
            </div>
          ) : answer.state === "failed" ? (
            <p role="alert" className="mt-3 text-sm text-danger">
              {answer.message}
            </p>
          ) : null}
        </form>
      </div>
    </section>
  );
}
