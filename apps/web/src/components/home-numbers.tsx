"use client";

import { useEffect, useState } from "react";

import { errorMessage } from "@/lib/api";
import { getOverview, tileUsd, type Overview } from "@/lib/overview";

/**
 * The home page's numbers, as stat tiles: live makers, approved orders, what makers were paid on proof, the parcels
 * delivered, and agents' searches this week. Loaded when the page opens; running the demo changes them.
 */
export function HomeNumbers() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getOverview({ signal: controller.signal })
      .then(setOverview)
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setProblem(errorMessage(error));
      });
    return () => controller.abort();
  }, []);

  if (overview === null) {
    return problem ? (
      <p role="alert" className="mt-6 text-danger">
        The numbers could not be loaded: {problem}
      </p>
    ) : (
      <p aria-busy="true" className="mt-6 text-muted">
        Loading the numbers…
      </p>
    );
  }
  const tiles: { label: string; value: string; detail?: string }[] = [
    {
      label: "Makers with a live listing",
      value: String(overview.makers),
      detail: overview.listings === overview.makers ? undefined : `${overview.listings} listings`,
    },
    { label: "Orders approved", value: String(overview.orders_approved) },
    {
      label: "Paid to makers on proof",
      value: tileUsd(overview.paid_usd),
      detail: overview.makers_paid === 1 ? "to 1 maker" : `to ${overview.makers_paid} makers`,
    },
    { label: "Parcels delivered", value: String(overview.deliveries) },
    { label: "Agent searches this week", value: String(overview.agent_searches) },
  ];
  return (
    <>
      <dl className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        {tiles.map((tile) => (
          <div key={tile.label} className="rounded-xl border border-border bg-background p-4">
            <dt className="text-sm text-muted">{tile.label}</dt>
            <dd className="mt-1 text-3xl font-semibold tracking-tight">{tile.value}</dd>
            {tile.detail ? <dd className="mt-0.5 text-sm text-muted">{tile.detail}</dd> : null}
          </div>
        ))}
      </dl>
      {overview.simulated ? (
        <p className="mt-3 text-sm text-muted">
          Test mode: PayPal is simulated, so these payments are too, and the five seeded makers are demo data.
        </p>
      ) : null}
    </>
  );
}
