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

  it("the buyer confirms each parcel that shipped arrived, and the order completes with the last", async () => {
    const amina: OrderPart = { ...RESERVED.parts[0], status: "released", nothing_to_confirm: true };
    const priya: OrderPart = { ...RESERVED.parts[1], status: "captured", payout_confirmed: true };
    const shipped: Order = { ...RESERVED, status: "shipped", parts: [amina, priya] };
    const complete: Order = {
      ...shipped,
      status: "completed",
      paid_usd: "176.00",
      released_usd: "216.00",
      parts: [amina, { ...priya, status: "delivered", delivered_at: "2026-12-04T15:30:00+00:00", on_time: true }],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(shipped))
      .mockResolvedValueOnce(Response.json(complete));
    vi.stubGlobal("fetch", fetchMock);
    render(<ReturnView />);

    const rows = within(await screen.findByRole("list", { name: "Each maker's share" })).getAllByRole("listitem");
    expect(within(rows[0]).queryByRole("button", { name: /Confirm delivery/ })).not.toBeInTheDocument();
    fireEvent.click(within(rows[1]).getByRole("button", { name: "Confirm delivery of Priya's parcel" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Order complete" })).toBeInTheDocument();
    const after = within(screen.getByRole("list", { name: "Each maker's share" })).getAllByRole("listitem");
    expect(after[1]).toHaveTextContent("Delivered to you");
    expect(after[1]).toHaveTextContent("Received December 4, 2026, on time");
    expect(within(after[1]).queryByRole("button", { name: /Confirm delivery/ })).not.toBeInTheDocument();
    expect(screen.getByText("Every parcel that shipped has arrived, and every maker who shipped is paid.")).toBeVisible();
    const went = screen.getByLabelText("Where the total went");
    expect(went).toHaveTextContent("Paid to the makers, on proof of shipping$176.00");
    expect(went).toHaveTextContent("Released back to you, never charged$216.00");
    expect(screen.queryByText(/Reserved at/)).not.toBeInTheDocument();
    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toBe(`http://api.test/api/orders/ord_demo/parts/${priya.id}/delivered`);
    expect(init.method).toBe("POST");
  });

  it("says when a parcel arrived late, and shows a refused confirmation", async () => {
    const late: OrderPart = {
      ...RESERVED.parts[0],
      status: "delivered",
      delivered_at: "2026-12-12T09:00:00+00:00",
      on_time: false,
    };
    const priya: OrderPart = { ...RESERVED.parts[1], status: "captured" };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json({ ...RESERVED, status: "shipped", parts: [late, priya] }))
      .mockResolvedValueOnce(Response.json({ detail: "Priya has not shipped her share yet." }, { status: 409 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<ReturnView />);

    const rows = within(await screen.findByRole("list", { name: "Each maker's share" })).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Received December 12, 2026, late: it was due December 10, 2026");
    fireEvent.click(within(rows[1]).getByRole("button", { name: "Confirm delivery of Priya's parcel" }));

    expect(await within(rows[1]).findByRole("alert")).toHaveTextContent("Priya has not shipped her share yet.");
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

  it("shows the tracking each maker confirmed, with her courier receipt, or what is still being read", async () => {
    const shipped: Order = {
      ...RESERVED,
      status: "partly_shipped",
      parts: [
        {
          ...RESERVED.parts[0],
          proof: {
            state: "awaiting_confirmation",
            photo_url: "/media/uploads/abc.png",
            carrier: "TCS",
            tracking_number: "7712345678",
            source: "photo",
            read_by: "Claude",
          },
        },
        {
          ...RESERVED.parts[1],
          status: "captured",
          carrier: "India Post",
          tracking_number: "EE123456789IN",
          tracking_on_paypal: true,
          proof: {
            state: "confirmed",
            photo_url: "/media/uploads/def.png",
            carrier: "India Post",
            tracking_number: "EE123456789IN",
            source: "photo",
            read_by: "Claude",
          },
        },
      ],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(shipped)));

    render(<ReturnView />);

    const rows = within(await screen.findByRole("list", { name: "Each maker's share" })).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Her courier receipt reads TCS, tracking 7712345678: waiting for her to confirm it.");
    expect(rows[1]).toHaveTextContent("Shipped with India Post: EE123456789IN");
    expect(within(rows[1]).getByRole("link", { name: "See her courier receipt" })).toHaveAttribute(
      "href",
      "http://api.test/media/uploads/def.png",
    );
    expect(rows[1]).toHaveTextContent("Tracking on the PayPal order");
  });

  it("says when tracking is not on the PayPal order yet, and why", async () => {
    const tracked = {
      carrier: "TCS",
      tracking_number: "7712345678",
      tracking_on_paypal: false,
      confirmation_source: "simulated" as const,
    };
    const order: Order = {
      ...RESERVED,
      parts: [
        { ...RESERVED.parts[0], ...tracked }, // reserved: no capture for PayPal to track yet
        { ...RESERVED.parts[1], ...tracked, status: "captured" }, // paid, but PayPal did not take her tracking yet
      ],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(order)));

    render(<ReturnView />);

    const rows = within(await screen.findByRole("list", { name: "Each maker's share" })).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("It goes on the simulated PayPal order once her share is captured.");
    expect(rows[1]).toHaveTextContent(
      "Not on the simulated PayPal order yet: it is tried again when this page is opened again.",
    );
  });

  it("says when her receipt arrived but its number still has to be typed", async () => {
    const waiting: Order = {
      ...RESERVED,
      parts: [
        {
          ...RESERVED.parts[0],
          proof: {
            state: "awaiting_number",
            photo_url: "/media/uploads/abc.png",
            carrier: null,
            tracking_number: null,
            source: "photo",
            read_by: null,
          },
        },
        RESERVED.parts[1],
      ],
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(waiting)));

    render(<ReturnView />);

    expect(
      await screen.findByText("Her courier receipt arrived; waiting for her to type its tracking number."),
    ).toBeInTheDocument();
  });

  it("says there is no order when the API does not know the id", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: "No." }, { status: 404 })));

    render(<ReturnView />);

    expect(await screen.findByRole("heading", { name: "No order here" })).toBeInTheDocument();
  });
});
