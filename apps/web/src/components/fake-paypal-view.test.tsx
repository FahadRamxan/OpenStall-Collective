import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FakePayPalView } from "@/components/fake-paypal-view";
import type { FakePayPalOrder } from "@/lib/fake-paypal";
import { goTo } from "@/lib/navigation";

const search = { params: new URLSearchParams("token=FAKE-1") };
vi.mock("next/navigation", () => ({ useSearchParams: () => search.params }));
vi.mock("@/lib/navigation", () => ({ goTo: vi.fn() }));

const ORDER: FakePayPalOrder = {
  token: "FAKE-1",
  status: "PAYER_ACTION_REQUIRED",
  order_id: "ord_demo",
  total_usd: "392.00",
  shares: [
    { reference_id: "op_001", description: "12 × Hand-embroidered cushion cover, Amina", amount_usd: "216.00" },
    { reference_id: "op_002", description: "11 × Mirror-work embroidered cushion cover, Priya", amount_usd: "176.00" },
  ],
  cancel_url: "http://localhost:3000/approve/ord_demo?cancelled=1",
};
const RETURN_URL = "http://localhost:3000/approve/ord_demo/return?token=FAKE-1&PayerID=FAKEBUYER01";

beforeEach(() => {
  search.params = new URLSearchParams("token=FAKE-1");
  vi.mocked(goTo).mockClear();
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("FakePayPalView", () => {
  it("says plainly that it is a simulation, and shows the total and each maker's share", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json(ORDER)));

    render(<FakePayPalView />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Simulated PayPal (test mode)");
    expect(screen.getByRole("note")).toHaveTextContent("No PayPal or Venmo account is used and no money moves.");
    const shares = within(await screen.findByRole("list", { name: "What you approve" })).getAllByRole("listitem");
    expect(shares[0]).toHaveTextContent("12 × Hand-embroidered cushion cover, Amina$216.00");
    expect(screen.getByText("$392.00")).toBeInTheDocument();
    expect(screen.getByText(/Approving reserves \$392.00/)).toBeInTheDocument();
  });

  it("stands in for Venmo when the order was made for Venmo", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...ORDER, funding: "venmo" })));

    render(<FakePayPalView />);

    expect(await screen.findByRole("heading", { level: 1, name: "Simulated Venmo (test mode)" })).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("This page stands in for Venmo while OpenStall runs in fake mode.");
    expect(screen.getByText(/asks you to approve order/)).toHaveTextContent("with Venmo.");
  });

  it("Approve approves the order and returns to OpenStall the way PayPal does", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(Response.json(ORDER))
      .mockResolvedValueOnce(Response.json({ redirect_url: RETURN_URL }));
    vi.stubGlobal("fetch", fetchMock);
    render(<FakePayPalView />);

    fireEvent.click(await screen.findByRole("button", { name: "Approve" }));

    await vi.waitFor(() => expect(goTo).toHaveBeenCalledWith(RETURN_URL));
    expect(fetchMock.mock.calls[1][0]).toBe("http://api.test/api/dev/fake-paypal/FAKE-1/approve");
  });

  it("Cancel goes back to the order without approving", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json(ORDER));
    vi.stubGlobal("fetch", fetchMock);
    render(<FakePayPalView />);

    fireEvent.click(await screen.findByRole("button", { name: "Cancel and go back" }));

    expect(goTo).toHaveBeenCalledWith(ORDER.cancel_url);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("an approved order only offers the way back", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ ...ORDER, status: "APPROVED" })));

    render(<FakePayPalView />);

    expect(await screen.findByRole("button", { name: "Back to OpenStall" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel and go back" })).not.toBeInTheDocument();
  });

  it("an expired checkout says what to do", async () => {
    const detail = "This test checkout has expired or never existed. Go back to the order and press Approve again.";
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail }, { status: 404 })));

    render(<FakePayPalView />);

    expect(await screen.findByRole("alert")).toHaveTextContent("press Approve again");
  });

  it("a link without a checkout says so", () => {
    search.params = new URLSearchParams();
    vi.stubGlobal("fetch", vi.fn());

    render(<FakePayPalView />);

    expect(screen.getByRole("alert")).toHaveTextContent("This link has no checkout in it.");
  });
});
