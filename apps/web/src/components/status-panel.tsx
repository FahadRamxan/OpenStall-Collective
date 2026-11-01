"use client";

import { Fragment, useEffect, useId, useState } from "react";

import { Badge, type BadgeTone } from "@/components/badge";
import { apiBaseUrl, errorMessage, getStatus, type AdapterState, type StatusReport } from "@/lib/api";

/** How long to wait for /api/status, so a hung API or a slow cold start cannot leave the page loading. */
export const STATUS_TIMEOUT_MS = 10_000;

type Load = { state: "loading" } | { state: "loaded"; report: StatusReport } | { state: "failed"; message: string };

type Look = { label: string; tone: BadgeTone };

const MODES: Record<string, Look & { description: string }> = {
  fake: {
    label: "Fake",
    tone: "warning",
    description:
      "Every outside service is a stand-in that gives the same answers every time. Nothing is sent to PayPal, " +
      "Twilio or an AI model, and no keys are needed. Tests and offline demos run this way.",
  },
  sandbox: {
    label: "Sandbox",
    tone: "accent",
    description:
      "Real services are used where they are ready below: the PayPal sandbox, the Twilio WhatsApp sandbox and AI " +
      "models. Rows marked Missing key or Not built yet show what is still needed. The PayPal sandbox moves no " +
      "real money.",
  },
};

const STATUSES: Record<string, Look> = {
  fake: { label: "Fake", tone: "warning" },
  real: { label: "Real", tone: "success" },
  "missing key": { label: "Missing key", tone: "danger" },
  "not built": { label: "Not built yet", tone: "neutral" },
};

/** Loads GET /api/status and shows the mode and each adapter. Written for judges as much as for developers. */
export function StatusPanel() {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let unmounted = false;
    // A timer rather than AbortSignal.timeout, which older browsers lack.
    const timer = setTimeout(() => controller.abort(), STATUS_TIMEOUT_MS);
    getStatus({ signal: controller.signal })
      .then((report) => {
        if (!unmounted) setLoad({ state: "loaded", report });
      })
      .catch((error: unknown) => {
        if (unmounted) return;
        const message = controller.signal.aborted
          ? `The API did not answer within ${STATUS_TIMEOUT_MS / 1000} seconds.`
          : errorMessage(error);
        setLoad({ state: "failed", message });
      })
      .finally(() => clearTimeout(timer));
    return () => {
      unmounted = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [attempt]);

  function tryAgain() {
    setLoad({ state: "loading" });
    setAttempt((count) => count + 1);
  }

  if (load.state === "loading") {
    return (
      <p role="status" className="mt-8 text-muted">
        Loading the status…
      </p>
    );
  }
  if (load.state === "failed") {
    return (
      <div role="alert" className="mt-8 rounded-xl border border-danger/30 bg-danger-soft p-5">
        <p className="font-semibold text-danger">Could not load the status.</p>
        <p className="mt-1 text-foreground">{load.message}</p>
        <button
          type="button"
          onClick={tryAgain}
          className="mt-4 inline-flex min-h-11 items-center rounded-full bg-accent px-5 text-sm font-semibold text-accent-foreground transition-colors hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
        >
          Try again
        </button>
      </div>
    );
  }
  return <Report report={load.report} />;
}

function Report({ report }: { report: StatusReport }) {
  const mode = MODES[report.mode] ?? { label: report.mode, tone: "neutral", description: "" };
  return (
    <>
      <section aria-labelledby="mode-heading" className="mt-8 rounded-xl border border-border bg-surface p-5 sm:p-6">
        <div className="flex flex-wrap items-center gap-3">
          <h2 id="mode-heading" className="text-xl font-semibold tracking-tight">
            Mode
          </h2>
          <Badge tone={mode.tone} size="lg">
            {mode.label}
          </Badge>
        </div>
        <p className="mt-3 leading-7 text-muted">{mode.description}</p>
        <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted">API</dt>
          <dd className="font-mono break-all">{apiBaseUrl()}</dd>
          <dt className="text-muted">Version</dt>
          <dd className="font-mono">{report.version}</dd>
        </dl>
      </section>

      <section aria-labelledby="adapters-heading" className="mt-10">
        <h2 id="adapters-heading" className="text-xl font-semibold tracking-tight">
          Adapters
        </h2>
        <p className="mt-2 leading-7 text-muted">
          The outside services OpenStall uses, and whether each one is a stand-in or the real service. Keys are named
          here, but their values are never shown.
        </p>
        <div className="mt-5 overflow-hidden rounded-xl border border-border bg-surface">
          {/* Two columns, so the descriptions keep room to read on a phone. */}
          <table aria-labelledby="adapters-heading" className="w-full border-collapse text-left text-sm">
            <thead className="border-b border-border text-xs tracking-wide text-muted uppercase">
              <tr>
                <th scope="col" className="px-4 py-3 font-semibold sm:px-5">
                  Adapter
                </th>
                <th scope="col" className="w-px px-4 py-3 font-semibold whitespace-nowrap sm:px-5">
                  Status
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {report.adapters.map((adapter) => (
                <AdapterRow key={adapter.name} adapter={adapter} />
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function AdapterRow({ adapter }: { adapter: AdapterState }) {
  const labelId = useId();
  const status = STATUSES[adapter.status] ?? { label: adapter.status, tone: "neutral" };
  return (
    <tr className="align-top">
      {/* Named by the adapter's name alone, so a screen reader says "LLM", not the whole description, as the
          row's header. */}
      <th scope="row" aria-labelledby={labelId} className="px-4 py-4 font-normal sm:px-5">
        <span id={labelId} className="block font-semibold">
          {adapter.label}
        </span>
        <span className="mt-1 block leading-6">{adapter.purpose}</span>
        <span className="mt-1 block text-xs leading-5 text-muted">
          Real service: {adapter.service}. <AdapterNote adapter={adapter} />
        </span>
      </th>
      <td className="px-4 py-4 sm:px-5">
        <Badge tone={status.tone}>{status.label}</Badge>
      </td>
    </tr>
  );
}

function AdapterNote({ adapter }: { adapter: AdapterState }) {
  switch (adapter.status) {
    case "fake":
      if (adapter.keys.length === 0) return <>No key needed.</>;
      return (
        <>
          In sandbox mode it needs <KeyList names={adapter.keys} />
        </>
      );
    case "missing key":
      return (
        <span className="text-danger">
          Not set: <KeyList names={adapter.missing_keys} />
        </span>
      );
    case "not built":
      return <>Its adapter is not built yet.</>;
    default:
      return null;
  }
}

/**
 * Setting names as a sentence ending in a full stop: "A, B and C.". Each name is an inline block, kept with the
 * word or stop after it, so it moves to the next line whole; only a name wider than the column wraps, after an
 * underscore.
 */
function KeyList({ names }: { names: string[] }) {
  return names.map((name, index) => {
    const after = index === names.length - 1 ? "." : index === names.length - 2 ? " and" : ",";
    return (
      <Fragment key={name}>
        {index > 0 && " "}
        <span className="inline-block wrap-anywhere">
          <KeyName name={name} />
          {after}
        </span>
      </Fragment>
    );
  });
}

function KeyName({ name }: { name: string }) {
  return (
    <code className="font-mono text-foreground">
      {name.split("_").map((part, index) => (
        <Fragment key={index}>
          {index > 0 && (
            <>
              _<wbr />
            </>
          )}
          {part}
        </Fragment>
      ))}
    </code>
  );
}
