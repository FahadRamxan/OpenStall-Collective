import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { STATUS_TIMEOUT_MS, StatusPanel } from "@/components/status-panel";
import type { AdapterState, StatusReport } from "@/lib/api";

const ADAPTER_LABELS = ["LLM", "Speech to text", "Embedder", "Messenger", "Payment gateway", "Image search"];

function adapter(overrides: Partial<AdapterState> & Pick<AdapterState, "label">): AdapterState {
  return {
    name: overrides.label.toLowerCase().replaceAll(" ", "_"),
    purpose: `What the ${overrides.label} is for.`,
    service: `${overrides.label} service`,
    status: "fake",
    keys: ["MADE_UP_KEY"],
    missing_keys: [],
    ...overrides,
  };
}

const DATABASE_OK: StatusReport["database"] = {
  status: "ok",
  tables: { orders: 0, sellers: 4 },
  message: null,
};

const PAYPAL_FAKE: StatusReport["payment"] = {
  status: "fake",
  path: "payouts",
  message: "Checkout runs on the simulated PayPal page. Nothing reaches PayPal.",
};

const FAKE_REPORT: StatusReport = {
  mode: "fake",
  version: "0.1.0",
  database: DATABASE_OK,
  payment: PAYPAL_FAKE,
  adapters: ADAPTER_LABELS.map((label) => adapter({ label })),
};

const SANDBOX_REPORT: StatusReport = {
  mode: "sandbox",
  version: "0.2.0",
  database: DATABASE_OK,
  payment: {
    status: "token ok",
    path: "multiparty",
    message: "PayPal gave us a token at https://api-m.sandbox.paypal.com.",
  },
  adapters: [
    adapter({ label: "LLM", status: "not built", keys: ["ANTHROPIC_API_KEY"] }),
    adapter({
      label: "Messenger",
      status: "missing key",
      service: "Twilio WhatsApp sandbox",
      keys: ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"],
      missing_keys: ["TWILIO_AUTH_TOKEN"],
    }),
    adapter({ label: "Payment gateway", status: "real", service: "PayPal sandbox" }),
  ],
};

/** A fetch that never answers, like a hung API, but rejects when its call is aborted, as fetch does. */
function hangingFetch() {
  return vi.fn(
    (_url: string, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new DOMException("The operation was aborted.", "AbortError")));
      }),
  );
}

async function adaptersTable() {
  return screen.findByRole("table", { name: "Adapters" });
}

/** The table row whose row header is `label`. */
function row(table: HTMLElement, label: string) {
  const header = within(table).getByRole("rowheader", { name: label });
  return header.closest("tr") as HTMLElement;
}

describe("StatusPanel", () => {
  beforeEach(() => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows fake mode and lists every adapter as fake", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json(FAKE_REPORT));
    vi.stubGlobal("fetch", fetchMock);

    render(<StatusPanel />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading the status…");
    const table = await adaptersTable();
    expect(within(screen.getByRole("region", { name: "Mode" })).getByText("Fake")).toBeInTheDocument();
    const headers = within(table).getAllByRole("rowheader");
    expect(headers).toHaveLength(ADAPTER_LABELS.length);
    ADAPTER_LABELS.forEach((label, index) => expect(headers[index]).toHaveAccessibleName(label));
    for (const label of ADAPTER_LABELS) {
      expect(within(row(table, label)).getByText("Fake")).toBeInTheDocument();
    }
    expect(fetchMock).toHaveBeenCalledWith("http://api.test/api/status", expect.objectContaining({ method: "GET" }));
  });

  it("shows the API it talks to and the API's version", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(FAKE_REPORT)));

    render(<StatusPanel />);

    const mode = await screen.findByRole("region", { name: "Mode" });
    expect(within(mode).getByText("http://api.test")).toBeInTheDocument();
    expect(within(mode).getByText("0.1.0")).toBeInTheDocument();
  });

  it("says what each adapter is for, and which keys the real service would need", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(FAKE_REPORT)));

    render(<StatusPanel />);

    const llm = row(await adaptersTable(), "LLM");
    expect(llm).toHaveTextContent("What the LLM is for.");
    expect(llm).toHaveTextContent("Real service: LLM service. In sandbox mode it needs MADE_UP_KEY.");
  });

  it("in sandbox mode, names the missing keys and the adapters not built yet", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(SANDBOX_REPORT)));

    render(<StatusPanel />);

    const table = await adaptersTable();
    expect(within(screen.getByRole("region", { name: "Mode" })).getByText("Sandbox")).toBeInTheDocument();
    expect(screen.getByText(/Real services are used where they are ready/)).toBeInTheDocument();

    const messenger = row(table, "Messenger");
    expect(within(messenger).getByText("Missing key")).toBeInTheDocument();
    expect(messenger).toHaveTextContent("Real service: Twilio WhatsApp sandbox. Not set: TWILIO_AUTH_TOKEN.");
    expect(messenger).not.toHaveTextContent("TWILIO_ACCOUNT_SID");

    expect(within(row(table, "LLM")).getByText("Not built yet")).toBeInTheDocument();
    expect(row(table, "LLM")).toHaveTextContent("Its adapter is not built yet.");
    expect(within(row(table, "Payment gateway")).getByText("Real")).toBeInTheDocument();
  });

  it("joins several key names in plain English", async () => {
    const report: StatusReport = {
      ...FAKE_REPORT,
      adapters: [adapter({ label: "Messenger", keys: ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "THIRD_KEY"] })],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(report)));

    render(<StatusPanel />);

    expect(row(await adaptersTable(), "Messenger")).toHaveTextContent(
      "In sandbox mode it needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and THIRD_KEY.",
    );
  });

  it("says so when the real service needs no key", async () => {
    const report: StatusReport = { ...FAKE_REPORT, adapters: [adapter({ label: "Embedder", keys: [] })] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(report)));

    render(<StatusPanel />);

    expect(row(await adaptersTable(), "Embedder")).toHaveTextContent("Real service: Embedder service. No key needed.");
  });

  it("shows PayPal as fake in fake mode, with the payment path", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(FAKE_REPORT)));

    render(<StatusPanel />);

    const paypal = await screen.findByRole("region", { name: "PayPal" });
    expect(within(paypal).getByText("Fake")).toBeInTheDocument();
    expect(paypal).toHaveTextContent("Checkout runs on the simulated PayPal page.");
    expect(paypal).toHaveTextContent("Payouts. PayPal holds the buyer's approval for OpenStall");
  });

  it("shows when PayPal gave the API a sandbox token, and when it refused", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(SANDBOX_REPORT)));
    const { unmount } = render(<StatusPanel />);

    const paypal = await screen.findByRole("region", { name: "PayPal" });
    expect(within(paypal).getByText("Token OK")).toBeInTheDocument();
    expect(paypal).toHaveTextContent("Multiparty. Each maker is a payee on the PayPal order");
    unmount();

    const refused: StatusReport = {
      ...SANDBOX_REPORT,
      payment: { status: "failed", path: "payouts", message: "PayPal gave no token: Client Authentication failed" },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(refused)));
    render(<StatusPanel />);

    const failed = await screen.findByRole("region", { name: "PayPal" });
    expect(within(failed).getByText("Failed")).toBeInTheDocument();
    expect(failed).toHaveTextContent("Client Authentication failed");
  });

  it("shows the database as OK, with the rows in each table", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(FAKE_REPORT)));

    render(<StatusPanel />);

    const database = await screen.findByRole("region", { name: "Database" });
    expect(within(database).getByText("OK")).toBeInTheDocument();
    const rows = within(database).getByLabelText("Rows per table");
    expect(rows).toHaveTextContent("orders0");
    expect(rows).toHaveTextContent("sellers4");
  });

  it("says when the database is not migrated, and how to fix it", async () => {
    const report: StatusReport = {
      ...FAKE_REPORT,
      database: { status: "not migrated", tables: {}, message: "Missing tables: orders. Run alembic upgrade head." },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(report)));

    render(<StatusPanel />);

    const database = await screen.findByRole("region", { name: "Database" });
    expect(within(database).getByText("Not migrated")).toBeInTheDocument();
    expect(database).toHaveTextContent("Run alembic upgrade head.");
    expect(within(database).queryByLabelText("Rows per table")).not.toBeInTheDocument();
  });

  it("says when the database cannot be reached", async () => {
    const report: StatusReport = {
      ...FAKE_REPORT,
      database: { status: "error", tables: {}, message: "The database could not be reached (OperationalError)." },
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(report)));

    render(<StatusPanel />);

    const database = await screen.findByRole("region", { name: "Database" });
    expect(within(database).getByText("Error")).toBeInTheDocument();
    expect(database).toHaveTextContent("could not be reached");
  });

  it("shows a status it does not know as the API wrote it", async () => {
    const report = {
      ...FAKE_REPORT,
      adapters: [{ ...adapter({ label: "LLM" }), status: "warming up" }],
    } as unknown as StatusReport;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(report)));

    render(<StatusPanel />);

    expect(within(row(await adaptersTable(), "LLM")).getByText("warming up")).toBeInTheDocument();
  });

  it("says when the status cannot be loaded, and loads it on Try again", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValueOnce(Response.json(FAKE_REPORT));
    vi.stubGlobal("fetch", fetchMock);

    render(<StatusPanel />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load the status.");
    expect(alert).toHaveTextContent("Could not reach the OpenStall API at http://api.test. Check that it is running.");

    fireEvent.click(within(alert).getByRole("button", { name: "Try again" }));

    expect(screen.getByRole("status")).toHaveTextContent("Loading the status…");
    expect(await adaptersTable()).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("gives up after 10 seconds, so a hung API cannot leave it loading", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", hangingFetch());

    render(<StatusPanel />);
    await act(() => vi.advanceTimersByTimeAsync(STATUS_TIMEOUT_MS - 1));
    expect(screen.getByRole("status")).toHaveTextContent("Loading the status…");

    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(screen.getByRole("alert")).toHaveTextContent("The API did not answer within 10 seconds.");
    expect(STATUS_TIMEOUT_MS).toBe(10_000);
  });

  it("stops loading when it is removed from the page", () => {
    vi.useFakeTimers();
    const fetchMock = hangingFetch();
    vi.stubGlobal("fetch", fetchMock);

    const { unmount } = render(<StatusPanel />);
    unmount();

    const { signal } = fetchMock.mock.calls[0][1] as RequestInit;
    expect(signal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
});
