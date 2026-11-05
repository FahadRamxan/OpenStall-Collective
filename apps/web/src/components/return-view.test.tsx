import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RECEIPT_POLL_MS, ReturnView } from "@/components/return-view";
import type { Order, OrderPart } from "@/lib/orders";

const params = { orderId: "ord_demo" };
vi.mock("next/navigation", () => ({ useParams: () => params }));

function share(name: string, quantity: number, price: string, amount: string, seller: string) {
  return {
    id: `op_${seller}`,
    reference_id: "op_001",
    seller: { id: seller, name, city: "Lahore", country: "PK" },
    product_title: "Hand-embroidered cushion cover",
    photo: null,
    quantity,
    unit_price_usd: price,
    amount_usd: amount,
    delivery_date: "2026-12-10",
    status: "authorized" as const,
    confirmed_by_paypal: true,
    attention: null,
    confirmation_source: "paypal_sandbox" as const,
    nothing_to_confirm: false,
    payout_rail: "paypal" as const,
    payout_label: "Paid to PayPal",
    payout_via_paypal: true,
    payout_confirmed: false,
    trust_score: "0.95",
    trust_data_source: "seeded_demo" as const,
  };
}

const RESERVED: Order = {
  id: "ord_demo",
  status: "authorized",
  total_usd: "392.00",
  units: 23,
  created_at: "2026-11-03T10:00:00Z",
  approved_at: "2026-11-03T10:05:00Z",
  paypal_order_id: "FAKE-1234",
  parent_order_id: null,
  request: null,
  parts: [share("Amina", 12, "18.00", "216.00", "s_amina"), share("Priya", 11, "16.00", "176.00", "s_priya")],
};

beforeEach(() => {
  params.orderId = "ord_demo";
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("ReturnView", () => {
  it("reserves the order on arrival and shows the receipt, each share reserved until she ships", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json(RESERVED));
    vi.stubGlobal("fetch", fetchMock);

    render(<ReturnView />);

    expect(screen.getByRole("status", { name: "Reserving the money at PayPal" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 1, name: "PayPal is holding $392.00" })).toBeInTheDocument();
    const shares = within(screen.getByRole("list", { name: "Each maker's share" })).getAllByRole("listitem");
    expect(shares).toHaveLength(2);
    expect(shares[0]).toHaveTextContent("Amina · Lahore, Pakistan");
    expect(shares[0]).toHaveTextContent("12 × $18.00 · ships by December 10, 2026");
    expect(shares[0]).toHaveTextContent("$216.00");
    for (const row of shares) {
      expect(row).toHaveTextContent("Reserved, paid when she ships");
      expect(row).toHaveTextContent("Confirmed by PayPal");
    }
    expect(screen.getByText("PayPal confirmed every share.")).toBeInTheDocument();
    expect(screen.getByText("PayPal order")).toHaveTextContent("FAKE-1234");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test/api/orders/ord_demo/reserve");
    expect(init.method).toBe("POST");
  });

  it("when PayPal does not have the approval, says so and links back to the order, without Try again", async () => {
    const detail = "PayPal does not have your approval for this order yet. Go back to the order and approve it.";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail }, { status: 409 })));

    render(<ReturnView />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The money is not reserved yet");
    expect(alert).toHaveTextContent(detail);
    expect(within(alert).getByRole("link", { name: "Back to the order" })).toHaveAttribute("href", "/approve/ord_demo");
    expect(within(alert).queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("when PayPal does not answer, Try again reserves it", async () => {
    const detail = "PayPal did not answer, so nothing was reserved or paid. Try again in a moment.";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ detail }, { status: 503 }))
      .mockResolvedValueOnce(Response.json(RESERVED));
    vi.stubGlobal("fetch", fetchMock);
    render(<ReturnView />);

    fireEvent.click(await screen.findByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("heading", { level: 1, name: "PayPal is holding $392.00" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("looks again until PayPal confirms each share", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const waiting: Order = {
      ...RESERVED,
      parts: RESERVED.parts.map((part) => ({ ...part, confirmed_by_paypal: false })),
    };
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => Promise.resolve(Response.json(waiting)))
      .mockImplementation(() => Promise.resolve(Response.json(RESERVED)));
    vi.stubGlobal("fetch", fetchMock);
    render(<ReturnView />);

    expect(await screen.findByText("Waiting for PayPal to confirm each share…")).toBeInTheDocument();
    expect(screen.getAllByText("Waiting for PayPal…")).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(RECEIPT_POLL_MS);

    expect(await screen.findByText("PayPal confirmed every share.")).toBeInTheDocument();
    expect(screen.getAllByText("Confirmed by PayPal")).toHaveLength(2);
    expect(fetchMock.mock.calls[1][0]).toBe("http://api.test/api/orders/ord_demo");
    vi.useRealTimers();
  });

  it("shows when PayPal reports a problem with a share", async () => {
    const denied: Order = {
      ...RESERVED,
      parts: [{ ...RESERVED.parts[0], confirmed_by_paypal: false, attention: "PayPal denied this payment" }],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(denied)));

    render(<ReturnView />);

    expect(await screen.findByText("PayPal denied this payment")).toBeInTheDocument();
  });

  it("in fake mode never says Confirmed by PayPal: simulated PayPal confirms, and says so", async () => {
    const simulated: Order = {
      ...RESERVED,
      parts: RESERVED.parts.map((part) => ({ ...part, confirmation_source: "simulated" as const })),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(simulated)));

    const { container } = render(<ReturnView />);

    expect(await screen.findByText("Simulated PayPal confirmed every share.")).toBeInTheDocument();
    expect(screen.getAllByText("Confirmed by simulated PayPal")).toHaveLength(2);
    expect(container.textContent).not.toContain("Confirmed by PayPal");
    expect(container.textContent).toContain("no money moves");
  });

  it("shows one authorization for the total under it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(RESERVED)));

    render(<ReturnView />);

    expect(
      await screen.findByText("One PayPal authorization for $392.00. Each maker's share is captured when she ships."),
    ).toBeInTheDocument();
  });

  it("in fake mode offers a simulated proof of shipping on each reserved row, except where no rail can pay her", async () => {
    const amina: OrderPart = {
      ...RESERVED.parts[0],
      confirmation_source: "simulated",
      payout_rail: "unavailable",
      payout_label: "Payout rail not connected yet (Pakistan)",
      payout_via_paypal: false,
    };
    const priya: OrderPart = {
      ...RESERVED.parts[1],
      confirmation_source: "simulated",
      payout_label: "Paid to PayPal (simulated)",
    };
    const reserved: Order = { ...RESERVED, parts: [amina, priya] };
    const paid: Order = {
      ...reserved,
      status: "partly_shipped",
      parts: [amina, { ...priya, status: "captured", payout_confirmed: true }],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(reserved))
      .mockResolvedValueOnce(Response.json(paid));
    vi.stubGlobal("fetch", fetchMock);
    render(<ReturnView />);

    const rows = within(await screen.findByRole("list", { name: "Each maker's share" })).getAllByRole("listitem");
    const aminaButton = within(rows[0]).getByRole("button", { name: /Simulate proof of shipping/ });
    expect(aminaButton).toBeDisabled();
    expect(aminaButton).toHaveTextContent("Simulated");
    expect(aminaButton).toHaveAccessibleDescription(/payout rail not connected yet \(Pakistan\)/);
    fireEvent.click(within(rows[1]).getByRole("button", { name: /Simulate proof of shipping/ }));

    const after = within(screen.getByRole("list", { name: "Each maker's share" })).getAllByRole("listitem");
    await vi.waitFor(() => expect(after[1]).toHaveTextContent("Paid on proof of shipping"));
    expect(after[1]).toHaveTextContent("payout confirmed by simulated PayPal");
    expect(within(after[1]).queryByRole("button", { name: /Simulate proof/ })).not.toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toBe(`http://api.test/api/dev/parts/${priya.id}/proof`);
    expect(init.method).toBe("POST");
  });

  it("offers no simulated proof against the real PayPal sandbox", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(RESERVED)));

    render(<ReturnView />);

    await screen.findByText("PayPal confirmed every share.");
    expect(screen.queryByRole("button", { name: /Simulate proof/ })).not.toBeInTheDocument();
  });

  it("a share released mid-order is not waited for: PayPal never hears about it", async () => {
    const released: Order = {
      ...RESERVED,
      parts: [
        { ...RESERVED.parts[0], status: "released", confirmed_by_paypal: false, nothing_to_confirm: true },
        RESERVED.parts[1],
      ],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(released)));

    render(<ReturnView />);

    expect(await screen.findByText("Never captured; nothing for PayPal to confirm")).toBeInTheDocument();
    expect(screen.getByText("PayPal confirmed every share.")).toBeInTheDocument();
  });

  it("says each maker was told about her share, where and in which language, with a link to her chat", async () => {
    const told: Order = {
      ...RESERVED,
      parts: [
        {
          ...RESERVED.parts[0],
          ship_by: "2026-12-01",
          notice: { state: "sent", channel: "web", language: "ur", at: "2026-11-10T10:06:00Z" },
        },
        {
          ...RESERVED.parts[1],
          ship_by: "2026-11-30",
          notice: { state: "sent", channel: "whatsapp", language: "hi", at: "2026-11-10T10:06:01Z" },
        },
      ],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(told)));

    render(<ReturnView />);

    expect(
      await screen.findByText("Each maker has been told about her share, in her own language."),
    ).toBeInTheDocument();
    const rows = within(screen.getByRole("list", { name: "Each maker's share" })).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("12 × $18.00 · ships by December 1, 2026, arrives by December 10, 2026");
    expect(rows[0]).toHaveTextContent("Told in the web chat, in Urdu");
    expect(within(rows[0]).getByRole("link", { name: "See Amina's chat" })).toHaveAttribute(
      "href",
      "/seller-chat?seller=s_amina",
    );
    expect(rows[1]).toHaveTextContent("ships by November 30, 2026, arrives by December 10, 2026");
    expect(rows[1]).toHaveTextContent("Told on WhatsApp, in Hindi");
  });

  it("looks again until each maker has been told", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const waiting: Order = { ...RESERVED, parts: RESERVED.parts.map((part) => ({ ...part, notice: null })) };
    const told: Order = {
      ...RESERVED,
      parts: RESERVED.parts.map((part) => ({
        ...part,
        notice: { state: "sent" as const, channel: "web" as const, language: "ur", at: "2026-11-10T10:06:00Z" },
      })),
    };
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => Promise.resolve(Response.json(waiting)))
      .mockImplementation(() => Promise.resolve(Response.json(told)));
    vi.stubGlobal("fetch", fetchMock);
    render(<ReturnView />);

    expect(await screen.findByText("Telling each maker about her share…")).toBeInTheDocument();
    expect(screen.getAllByText("Telling her about her share…")).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(RECEIPT_POLL_MS);

    expect(
      await screen.findByText("Each maker has been told about her share, in her own language."),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Told in the web chat, in Urdu/)).toHaveLength(2);
    expect(fetchMock.mock.calls[1][0]).toBe("http://api.test/api/orders/ord_demo");
    vi.useRealTimers();
  });

  it("says which maker WhatsApp could not reach yet, and that OpenStall tries again", async () => {
    const reason = "Twilio refused the message (400): not a WhatsApp number";
    const failed: Order = {
      ...RESERVED,
      parts: [
        {
          ...RESERVED.parts[0],
          notice: { state: "sent", channel: "web", language: "ur", at: "2026-11-10T10:06:00Z" },
        },
        {
          ...RESERVED.parts[1],
          notice: { state: "failed", channel: "whatsapp", language: null, at: "2026-11-10T10:06:01Z", reason },
        },
      ],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(failed)));

    render(<ReturnView />);

    expect(await screen.findByText("1 of 2 makers told. Not reached yet: Priya.")).toBeInTheDocument();
    const rows = within(screen.getByRole("list", { name: "Each maker's share" })).getAllByRole("listitem");
    expect(rows[1]).toHaveTextContent(
      `Not told yet: ${reason}. OpenStall tries again when this page is opened again.`,
    );
    expect(within(rows[1]).queryByRole("link", { name: /chat/ })).not.toBeInTheDocument();
  });

  it("says there is no order when the API does not know the id", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: "No." }, { status: 404 })));

    render(<ReturnView />);

    expect(await screen.findByRole("heading", { name: "No order here" })).toBeInTheDocument();
  });
});
