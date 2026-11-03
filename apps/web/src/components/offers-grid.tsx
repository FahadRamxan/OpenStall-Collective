"use client";

import {
  AllCommunityModule,
  ModuleRegistry,
  themeQuartz,
  type ColDef,
  type GetRowIdParams,
  type ICellRendererParams,
} from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";

import { Badge } from "@/components/badge";
import { useLiveList, type LiveListSource } from "@/hooks/use-live-list";
import { formatUsd } from "@/lib/catalog";
import { arrivalWords, getRecentOffers, offerFromEvent, roundWords, type AgentOffer } from "@/lib/offers";
import { MAX_ROUNDS } from "@/lib/quotes";
import { formatDay } from "@/lib/orders";

ModuleRegistry.registerModules([AllCommunityModule]);

/** The most offers the panel keeps. It shows those of the latest request. */
export const RECENT_OFFERS = 50;

const OFFERS: LiveListSource<AgentOffer> = {
  load: (init) => getRecentOffers(RECENT_OFFERS, init),
  fromEvent: offerFromEvent,
  key: (offer) => offer.id,
  time: (offer) => offer.created_at,
  limit: RECENT_OFFERS,
};

/** AG Grid in the site's own colours, light and dark, from the same tokens as the rest of the page. */
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

/** Wrapped text at the page's own line height, not the grid's row height, with room above and below. */
const WRAPPED = { lineHeight: "1.375rem", paddingTop: "0.625rem", paddingBottom: "0.625rem" };

/*
 * The verdict comes right after the price it is about: on a laptop every column is in view, and on a phone, where the
 * grid scrolls sideways inside itself with the seller pinned, the verdict is the first thing to scroll to. Each round
 * and try is under the seller's name.
 */
const COLUMNS: ColDef<AgentOffer>[] = [
  {
    field: "seller_name",
    headerName: "Seller",
    cellRenderer: SellerCell,
    pinned: "left",
    width: 118,
    autoHeight: true,
  },
  {
    field: "unit_price",
    headerName: "Price",
    valueFormatter: ({ value }) => (typeof value === "string" ? formatUsd(value) : ""),
    comparator: (a: string, b: string) => Number(a) - Number(b),
    type: "rightAligned",
    width: 92,
  },
  {
    colId: "check",
    headerName: "Code check",
    cellRenderer: CheckCell,
    cellStyle: WRAPPED,
    width: 188,
    wrapText: true,
    autoHeight: true,
    sortable: false,
  },
  { field: "quantity", headerName: "Units", type: "rightAligned", width: 76 },
  {
    field: "delivery_date",
    headerName: "Delivery",
    valueFormatter: ({ value }) => (typeof value === "string" ? shortDay(value) : ""),
    tooltipValueGetter: ({ value }) => (typeof value === "string" ? formatDay(value) : ""),
    width: 92,
  },
  {
    field: "message",
    headerName: "Agent's message",
    cellStyle: WRAPPED,
    flex: 1,
    minWidth: 220,
    wrapText: true,
    autoHeight: true,
    sortable: false,
  },
];

/**
 * The /demo page's "Offers" panel: every price the seller agents proposed for the latest quote request, valid or
 * refused, with why the code refused it and the agent's message to the buyer. Rows are added live as the code checks
 * each proposal. Nothing here is a model's word: valid and refused are the code check's verdicts.
 */
export function OffersGrid() {
  const { rows, loading, error, arrived } = useLiveList(OFFERS);
  // The rows come newest first, so the first row's request is the latest one. Its offers are shown oldest first,
  // the order the agents made them, so a refused price sits just above the retry that followed it.
  const requestId = rows[0]?.request_id;
  const latest = rows.filter((offer) => offer.request_id === requestId).reverse();
  return (
    <section aria-labelledby="offers-heading" className="mt-10">
      <h2 id="offers-heading" className="text-xl font-semibold tracking-tight">
        Offers
      </h2>
      <p className="mt-1 leading-7 text-muted">
        Each seller&apos;s agent proposes a price, and code checks it against her limits and the buyer&apos;s maximum.
        A refused price goes back to the agent with the reason, at most twice. Only valid offers can win a share.
      </p>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-danger">
          Earlier offers could not be loaded: {error}
        </p>
      ) : null}
      {latest.length > 0 ? (
        <div className="mt-4">
          {/* The round the latest proposal was made in: a quote runs at most MAX_ROUNDS (spec 3.3). */}
          <p className="mb-2 text-sm font-medium text-muted">
            Round {Math.max(...latest.map((offer) => offer.round))} of {MAX_ROUNDS}
          </p>
          <AgGridReact<AgentOffer>
            theme={THEME}
            rowData={latest}
            columnDefs={COLUMNS}
            defaultColDef={{ sortable: true, resizable: true, suppressMovable: true }}
            getRowId={rowId}
            domLayout="autoHeight"
            suppressColumnVirtualisation
            ensureDomOrder
            enableCellTextSelection
          />
        </div>
      ) : loading ? (
        <p aria-busy="true" className="mt-4 text-muted">
          Loading offers…
        </p>
      ) : error ? null : (
        <p className="mt-4 rounded-xl border border-dashed border-border p-6 leading-7 text-muted">
          No seller agent has made an offer yet. When a buyer agent asks for a quote, each matching seller&apos;s agent
          proposes a price here, and the code check says whether it is valid.
        </p>
      )}
      {/* Always in the page, so screen readers hear each new verdict. The ones loaded at first are not read out. */}
      <div role="status" className="sr-only">
        {arrived ? <span key={arrived.id}>{arrivalWords(arrived)}</span> : null}
      </div>
    </section>
  );
}

function rowId({ data }: GetRowIdParams<AgentOffer>): string {
  return data.id;
}

/** Her name, and which round and try this proposal was. */
function SellerCell({ data }: ICellRendererParams<AgentOffer>) {
  if (!data) return null;
  return (
    <span className="block py-2 leading-5">
      <span className="block font-semibold">{data.seller_name}</span>
      <span className="block text-xs text-muted">{roundWords(data)}</span>
    </span>
  );
}

const SHORT_DAY = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

/** "Dec 10" from "2026-12-10", the same in every time zone. */
function shortDay(isoDate: string): string {
  const day = new Date(`${isoDate}T00:00:00Z`);
  return Number.isNaN(day.getTime()) ? isoDate : SHORT_DAY.format(day);
}

/** "Valid", or "Refused" with why: the words carry the verdict, the colour only repeats it. */
function CheckCell({ data }: ICellRendererParams<AgentOffer>) {
  if (!data) return null;
  return data.is_valid ? (
    <Badge tone="success">Valid</Badge>
  ) : (
    <span className="inline-flex flex-wrap items-center gap-x-2">
      <Badge tone="danger">Refused</Badge>
      <span className="text-sm leading-6 text-muted">{data.why}</span>
    </span>
  );
}
