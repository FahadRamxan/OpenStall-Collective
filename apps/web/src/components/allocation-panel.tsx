"use client";

import { AllCommunityModule, ModuleRegistry, themeQuartz, type ColDef } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/badge";
import { ShareBar } from "@/components/share-bar";
import { useEventStream } from "@/hooks/use-event-stream";
import { errorMessage } from "@/lib/api";
import { formatUsd } from "@/lib/catalog";
import { formatDay } from "@/lib/orders";
import { changesPlan, getPlan, planHeadline, type Plan, type PlanLine } from "@/lib/plans";
import { getLatestQuote } from "@/lib/quotes";

ModuleRegistry.registerModules([AllCommunityModule]);

/** AG Grid in the site's own colours, light and dark, as in the offers table. */
const THEME = themeQuartz.withParams({
  backgroundColor: "var(--surface)",
  foregroundColor: "var(--foreground)",
  textColor: "var(--foreground)",
  borderColor: "var(--border)",
  accentColor: "var(--accent)",
  headerBackgroundColor: "var(--background)",
  headerTextColor: "var(--muted)",
  rowHoverColor: "var(--accent-soft)",
  fontFamily: "inherit",
  fontSize: 14,
  wrapperBorderRadius: 12,
});

type Row = Pick<PlanLine, "seller_name" | "quantity"> & Partial<PlanLine>;

const money = ({ value }: { value: unknown }) => (typeof value === "string" ? formatUsd(value) : "");

const COLUMNS: ColDef<Row>[] = [
  { field: "seller_name", headerName: "Seller", flex: 1, minWidth: 120 },
  { field: "quantity", headerName: "Units", type: "rightAligned", width: 90 },
  { field: "unit_price", headerName: "Unit price", type: "rightAligned", valueFormatter: money, width: 120 },
  { field: "line_total", headerName: "Line total", type: "rightAligned", valueFormatter: money, width: 130 },
  {
    field: "delivery_date",
    headerName: "Delivery",
    valueFormatter: ({ value }) => (typeof value === "string" ? formatDay(value) : ""),
    flex: 1,
    minWidth: 170,
  },
];

/**
 * The /demo page's "Allocation" panel: how the latest quote's order is split across makers. Plain code (the allocator
 * core) fills the quantity from the cheapest valid offers first, each up to what she offered; the bar shows each
 * maker's share, and the table each line with the total in a pinned last row. A plan that cannot fill the order says
 * how many are possible, and why.
 */
export function AllocationPanel() {
  const { events } = useEventStream();
  // Events are newest first: the newest event after which the plan may have changed.
  const lastChange = events.find(changesPlan)?.id ?? 0;
  const [plan, setPlan] = useState<Plan | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getLatestQuote({ signal: controller.signal })
      .then((quote) => (quote ? getPlan(quote.id, { signal: controller.signal }) : null))
      .then((latest) => {
        setPlan(latest);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(reason));
      });
    return () => controller.abort();
  }, [lastChange]);

  return (
    <section aria-labelledby="allocation-heading" className="mt-10">
      <h2 id="allocation-heading" className="text-xl font-semibold tracking-tight">
        Allocation
      </h2>
      <p className="mt-1 leading-7 text-muted">
        Plain code splits the order: cheapest valid offer first, each maker up to the units she offered, until the
        quantity is filled. No model decides any number here.
      </p>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-danger">
          The allocation could not be loaded: {error}
        </p>
      ) : null}
      {plan ? (
        <PlanView plan={plan} />
      ) : plan === null ? (
        <p className="mt-4 rounded-xl border border-dashed border-border p-6 leading-7 text-muted">
          No plan yet. When a quote&apos;s rounds are done, its valid offers are split here, cheapest first.
        </p>
      ) : error ? null : (
        <p aria-busy="true" className="mt-4 text-muted">
          Loading the allocation…
        </p>
      )}
    </section>
  );
}

function PlanView({ plan }: { plan: Plan }) {
  const total: Row = { seller_name: "Total", quantity: plan.total_quantity, line_total: plan.total_cost };
  return (
    <div className="mt-4 rounded-xl border border-border bg-surface p-5 sm:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <Badge tone={plan.complete ? "success" : "warning"}>{plan.complete ? "Complete" : "Short"}</Badge>
        <p className="text-lg font-semibold">{planHeadline(plan)}</p>
      </div>
      {plan.reason ? <p className="mt-2 leading-7 text-muted">{plan.reason}</p> : null}
      {plan.lines.length > 0 ? <ShareBar plan={plan} /> : null}
      <div className="mt-5">
        <AgGridReact<Row>
          theme={THEME}
          rowData={plan.lines}
          pinnedBottomRowData={[total]}
          columnDefs={COLUMNS}
          defaultColDef={{ sortable: false, resizable: true, suppressMovable: true }}
          getRowId={({ data }) => data.seller_id ?? "total"}
          getRowStyle={({ node }) => (node.rowPinned ? { fontWeight: 600 } : undefined)}
          domLayout="autoHeight"
          suppressColumnVirtualisation
          ensureDomOrder
          enableCellTextSelection
        />
      </div>
    </div>
  );
}
