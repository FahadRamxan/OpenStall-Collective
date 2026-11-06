"use client";

import type { ColDef, ICellRendererParams } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";

import { Badge, type BadgeTone } from "@/components/badge";
import { GRID_THEME, WRAPPED } from "@/components/grid-theme";
import { useEventStream } from "@/hooks/use-event-stream";
import { ApiError, errorMessage } from "@/lib/api";
import { formatUsd, percent } from "@/lib/catalog";
import {
  getDashboard,
  sendRadarTip,
  type Dashboard,
  type DashboardOrder,
  type DashboardPassport,
  type DashboardShare,
  type RadarGroup,
} from "@/lib/dashboard";
import { ORDER_STATUS_LABELS, PART_STATUS_LABELS, formatDay, type OrderStatus, type PartStatus } from "@/lib/orders";

const DEFAULT_COLUMN: ColDef = { sortable: true, resizable: true, suppressMovable: true };
const LINK =
  "text-accent underline underline-offset-4 hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

function day(iso: string | null | undefined): string {
  return iso ? formatDay(iso.slice(0, 10)) : "";
}

function money({ value }: { value: unknown }): string {
  return typeof value === "string" ? formatUsd(value) : "";
}

function byAmount(a: string, b: string): number {
  return Number(a) - Number(b);
}

const SHARE_TONES: Record<PartStatus, BadgeTone> = {
  pending: "neutral",
  authorized: "accent",
  captured: "success",
  delivered: "success",
  released: "neutral",
};

const ORDER_COLUMNS: ColDef<DashboardOrder>[] = [
  { field: "id", headerName: "Order", cellRenderer: OrderCell, pinned: "left", width: 176, autoHeight: true },
  {
    field: "status",
    headerName: "Status",
    valueFormatter: ({ value }) => ORDER_STATUS_LABELS[value as OrderStatus] ?? String(value),
    width: 176,
  },
  { field: "total_usd", headerName: "Total", valueFormatter: money, comparator: byAmount, type: "rightAligned", width: 112 },
  {
    field: "paid_usd",
    headerName: "Paid on proof",
    valueFormatter: money,
    comparator: byAmount,
    type: "rightAligned",
    width: 132,
  },
  {
    field: "released_usd",
    headerName: "Released",
    valueFormatter: money,
    comparator: byAmount,
    type: "rightAligned",
    width: 112,
  },
  { field: "units", headerName: "Units", type: "rightAligned", width: 88 },
  { field: "makers", headerName: "Makers", type: "rightAligned", width: 96 },
  { field: "approved_at", headerName: "Approved", valueFormatter: ({ value }) => day(value as string | null), width: 136 },
  { field: "created_at", headerName: "Drafted", valueFormatter: ({ value }) => day(value as string), width: 136 },
];

const PAYOUT_COLUMNS: ColDef<DashboardShare>[] = [
  { field: "maker", headerName: "Maker", pinned: "left", width: 112 },
  { field: "order_id", headerName: "Order", cellClass: "font-mono", width: 168 },
  { field: "quantity", headerName: "Units", type: "rightAligned", width: 84 },
  { field: "amount_usd", headerName: "Share", valueFormatter: money, comparator: byAmount, type: "rightAligned", width: 104 },
  { field: "status", headerName: "Payment", cellRenderer: ShareStatusCell, width: 236, autoHeight: true },
  { field: "payout", headerName: "Payout", width: 300, wrapText: true, autoHeight: true, cellStyle: WRAPPED },
];

const TRACKING_COLUMNS: ColDef<DashboardShare>[] = [
  { field: "maker", headerName: "Maker", pinned: "left", width: 112 },
  { field: "order_id", headerName: "Order", cellClass: "font-mono", width: 168 },
  { field: "carrier", headerName: "Courier", width: 128 },
  { field: "tracking_number", headerName: "Tracking number", cellClass: "font-mono", width: 176 },
  {
    field: "tracking_on_paypal",
    headerName: "On PayPal",
    valueFormatter: ({ value }) => (value ? "Yes" : "Not yet"),
    width: 112,
  },
  { field: "ship_by", headerName: "Ship by", valueFormatter: ({ value }) => day(value as string | null), width: 132 },
  {
    field: "delivered_at",
    headerName: "Delivered",
    valueFormatter: ({ data }) =>
      data?.delivered_at ? `${day(data.delivered_at)}${data.on_time === false ? ", late" : ", on time"}` : "Not yet",
    width: 172,
  },
];

const PASSPORT_COLUMNS: ColDef<DashboardPassport>[] = [
  { field: "name", headerName: "Maker", cellRenderer: MakerLinkCell, pinned: "left", width: 112 },
  {
    field: "score",
    headerName: "Score",
    valueFormatter: ({ value }) => (typeof value === "number" ? value.toFixed(2) : ""),
    type: "rightAligned",
    width: 92,
  },
  { field: "orders_delivered", headerName: "Orders delivered", type: "rightAligned", width: 148 },
  { field: "on_time_rate", headerName: "On time", valueFormatter: ({ value }) => percent(Number(value)), width: 104 },
  { field: "dispute_rate", headerName: "Disputes", valueFormatter: ({ value }) => percent(Number(value)), width: 104 },
  {
    field: "photo_originality",
    headerName: "Photo originality",
    valueFormatter: ({ value }) => percent(Number(value)),
    width: 148,
  },
  { field: "live_deliveries", headerName: "Through OpenStall", type: "rightAligned", width: 156 },
  {
    field: "data_source",
    headerName: "Data",
    valueFormatter: ({ value }) => (value === "seeded_demo" ? "Seeded demo" : "Live"),
    width: 124,
  },
  { field: "signature_valid", headerName: "Signature", cellRenderer: SignatureCell, width: 140 },
];

/** What the Radar grid's tip cells need from the dashboard. */
type TipContext = { send: (key: string) => void; busy: string | null };

const RADAR_COLUMNS: ColDef<RadarGroup>[] = [
  {
    field: "label",
    headerName: "Searched for",
    cellRenderer: SearchedCell,
    pinned: "left",
    width: 220,
    wrapText: true,
    autoHeight: true,
  },
  { field: "searches", headerName: "This week", cellRenderer: CountCell, type: "rightAligned", width: 120, autoHeight: true },
  {
    colId: "maker",
    headerName: "Who could make them",
    cellRenderer: RadarMakerCell,
    width: 260,
    wrapText: true,
    autoHeight: true,
  },
  { colId: "tip", headerName: "Tip", cellRenderer: TipCell, width: 240, autoHeight: true, sortable: false },
];

/**
 * The dashboard (spec 3.9, prompt 44): AG Grid tables of the recent orders, each maker's payout, her tracking, the
 * trust passports and Demand Radar, with Radar's biggest tip on top. It loads again whenever the live feed moves, so
 * the tables follow what happens on /demo and in the makers' chats.
 */
export function DashboardView() {
  const { events } = useEventStream();
  const newest = events[0]?.id ?? 0;
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  const [tipProblem, setTipProblem] = useState<string | null>(null);
  const [needsToken, setNeedsToken] = useState(false);
  const [token, setToken] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getDashboard({ signal: controller.signal })
      .then((loaded) => {
        setDashboard(loaded);
        setProblem(null);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) setProblem(errorMessage(error));
      });
    return () => controller.abort();
  }, [newest, version]);

  async function send(key: string) {
    setBusy(key);
    setTipProblem(null);
    try {
      await sendRadarTip(key, token || null);
      setVersion((current) => current + 1);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) setNeedsToken(true);
      setTipProblem(errorMessage(error));
    } finally {
      setBusy(null);
    }
  }

  if (dashboard === null) {
    return problem ? (
      <p role="alert" className="mt-8 text-danger">
        The dashboard could not be loaded: {problem}
      </p>
    ) : (
      <p aria-busy="true" className="mt-8 text-muted">
        Loading the dashboard…
      </p>
    );
  }
  const tracked = dashboard.shares.filter((share) => share.tracking_number || share.delivered_at);
  const top = dashboard.radar[0];
  const context: TipContext = { send: (key) => void send(key), busy };
  return (
    <div className="mt-8 space-y-10">
      {dashboard.simulated ? (
        <p className="flex flex-wrap items-center gap-2 text-sm text-muted">
          <Badge tone="warning">Test mode</Badge>
          PayPal and the payouts are simulated; the makers and their numbers marked seeded are demo data.
        </p>
      ) : null}
      {top ? (
        <section aria-labelledby="radar-tip-heading" className="rounded-xl border border-accent/30 bg-accent-soft p-5">
          <h2 id="radar-tip-heading" className="text-sm font-semibold tracking-wide text-accent uppercase">
            Demand Radar tip
          </h2>
          <p className="mt-2 text-xl font-semibold text-balance">{top.tip}</p>
          {top.seeded > 0 ? (
            <p className="mt-1 text-sm text-muted">
              {top.seeded === top.searches ? "All" : `${top.seeded} of`} {top.searches === 1 ? "this search" : "these searches"}{" "}
              {top.seeded === 1 && top.searches === 1 ? "is" : "are"} seeded demo data.
            </p>
          ) : null}
        </section>
      ) : null}
      <Table id="orders" title="Orders" empty="No orders yet." rows={dashboard.orders} columns={ORDER_COLUMNS} rowId="id" />
      <Table
        id="payouts"
        title="Payouts"
        intro="Each maker's share: reserved when the buyer approves, paid to her when she proves she shipped, or released."
        empty="No shares yet."
        rows={dashboard.shares}
        columns={PAYOUT_COLUMNS}
        rowId="part_id"
      />
      <Table
        id="tracking"
        title="Tracking"
        intro="Each parcel a maker shipped: the courier and tracking number she confirmed, on the PayPal order, and delivered."
        empty="No maker has shipped yet: her tracking appears here once she confirms it."
        rows={tracked}
        columns={TRACKING_COLUMNS}
        rowId="part_id"
      />
      <Table
        id="passports"
        title="Trust passports"
        intro="Each maker's signed trust card, and whether its signature holds."
        empty="No trust passports yet."
        rows={dashboard.passports}
        columns={PASSPORT_COLUMNS}
        rowId="seller_id"
      />
      <Table
        id="radar"
        title="Demand Radar"
        intro="This week's searches that found nothing, grouped by their words, with the maker who could make them."
        empty="No search found nothing this week."
        rows={dashboard.radar}
        columns={RADAR_COLUMNS}
        rowId="key"
        context={context}
      >
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
        {tipProblem ? (
          <p role="alert" className="mt-3 text-sm text-danger">
            The tip was not sent: {tipProblem}
          </p>
        ) : null}
      </Table>
    </div>
  );
}

function Table<Row extends object>({
  id,
  title,
  intro,
  empty,
  rows,
  columns,
  rowId,
  context,
  children,
}: {
  id: string;
  title: string;
  intro?: string;
  empty: string;
  rows: Row[];
  columns: ColDef<Row>[];
  rowId: keyof Row & string;
  context?: TipContext;
  children?: ReactNode;
}) {
  return (
    <section aria-labelledby={`${id}-heading`}>
      <h2 id={`${id}-heading`} className="text-xl font-semibold tracking-tight">
        {title}
      </h2>
      {intro ? <p className="mt-1 leading-7 text-muted">{intro}</p> : null}
      {children}
      {rows.length === 0 ? (
        <p className="mt-4 rounded-xl border border-dashed border-border p-6 leading-7 text-muted">{empty}</p>
      ) : (
        <div className="mt-4">
          <AgGridReact<Row>
            theme={GRID_THEME}
            rowData={rows}
            columnDefs={columns}
            defaultColDef={DEFAULT_COLUMN}
            getRowId={({ data }) => String(data[rowId])}
            context={context}
            domLayout="autoHeight"
            suppressColumnVirtualisation
            ensureDomOrder
            enableCellTextSelection
          />
        </div>
      )}
    </section>
  );
}

function OrderCell({ data }: ICellRendererParams<DashboardOrder>) {
  if (!data) return null;
  return (
    <div className="py-2 leading-5">
      <Link href={`/approve/${encodeURIComponent(data.id)}`} className={`font-mono ${LINK}`}>
        {data.id}
      </Link>
      {data.top_up_of ? (
        <p className="text-xs text-muted">
          Top-up of <span className="font-mono">{data.top_up_of}</span>
        </p>
      ) : data.requested_by_agent ? (
        <p className="text-xs text-muted">Drafted by an AI agent</p>
      ) : data.from_stall ? (
        <p className="text-xs text-muted">Bought on a stall</p>
      ) : null}
    </div>
  );
}

function ShareStatusCell({ data }: ICellRendererParams<DashboardShare>) {
  if (!data) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 py-2">
      <Badge tone={SHARE_TONES[data.status]}>{PART_STATUS_LABELS[data.status]}</Badge>
      {data.dropped_out ? <Badge tone="warning">Dropped out</Badge> : null}
    </div>
  );
}

function MakerLinkCell({ data }: ICellRendererParams<DashboardPassport>) {
  if (!data) return null;
  return (
    <Link href={`/stall/${encodeURIComponent(data.seller_id)}`} className={LINK}>
      {data.name}
    </Link>
  );
}

function SignatureCell({ data }: ICellRendererParams<DashboardPassport>) {
  if (!data) return null;
  if (data.signature_valid === null) return <Badge tone="neutral">No key to check</Badge>;
  return data.signature_valid ? <Badge tone="success">Valid</Badge> : <Badge tone="danger">Does not match</Badge>;
}

function SearchedCell({ data }: ICellRendererParams<RadarGroup>) {
  if (!data) return null;
  const others = data.queries.filter((query) => query !== data.label);
  return (
    <div className="py-2 leading-5">
      <p className="font-semibold">{data.label}</p>
      {others.length > 0 ? <p className="text-xs text-muted">Also: {others.join("; ")}</p> : null}
    </div>
  );
}

function CountCell({ data }: ICellRendererParams<RadarGroup>) {
  if (!data) return null;
  return (
    <div className="py-2 text-right leading-5">
      <p className="font-semibold tabular-nums">{data.searches}</p>
      {data.seeded > 0 ? <p className="text-xs text-muted">{data.seeded} seeded</p> : null}
    </div>
  );
}

function RadarMakerCell({ data }: ICellRendererParams<RadarGroup>) {
  if (!data) return null;
  if (!data.maker) return <p className="py-2 leading-5 text-muted">Nobody on OpenStall yet</p>;
  return (
    <div className="py-2 leading-5">
      <p className="font-semibold">{data.maker.name}</p>
      <p className="text-xs text-muted">
        Makes {data.maker.product_title.toLowerCase()} (shares “{data.maker.shared.join(", ")}”)
      </p>
    </div>
  );
}

function TipCell({ data, context }: ICellRendererParams<RadarGroup, unknown, TipContext>) {
  if (!data) return null;
  if (data.tipped_at) return <Badge tone="success">{`Tipped ${day(data.tipped_at)}`}</Badge>;
  if (!data.maker || !context) return <span className="text-sm text-muted">No maker to tip</span>;
  const sending = context.busy === data.key;
  return (
    <div className="py-1.5">
      <button
        type="button"
        disabled={context.busy !== null}
        onClick={() => context.send(data.key)}
        className="inline-flex min-h-9 items-center rounded-full bg-accent px-3 text-xs font-semibold text-accent-foreground hover:bg-accent-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-60"
      >
        {sending ? "Sending…" : `Send the tip to ${data.maker.name}`}
      </button>
    </div>
  );
}
