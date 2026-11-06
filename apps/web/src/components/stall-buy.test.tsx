import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StallBuy } from "@/components/stall-buy";
import type { Product } from "@/lib/catalog";
import type { PayPalButtonsOptions } from "@/lib/stall-orders";

const PRODUCT: Product = {
  id: "p_priya_cushion",
  seller_id: "s_priya",
  title: "Mirror-work embroidered cushion cover",
  description: "Cotton cover.",
  category: "home textiles",
  variants: [],
  price_usd: "16.00",
  capacity_per_week: 4,
  ship_days: 10,
  ship_from_city: "Jaipur",
  photos: [],
  data_source: "seeded_demo",
};

type Call = { method: string; path: string; body: unknown };

/** The API: PayPal's config, then a stall order, its checkout and its reserve. */
function api(config: object) {
  const calls: Call[] = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = new URL(url).pathname;
    calls.push({ method: init?.method ?? "GET", path, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (path === "/api/paypal/config") return Response.json(config);
    if (path === "/api/stall-orders") return Response.json({ id: "ord_stall" }, { status: 201 });
    if (path === "/api/orders/ord_stall/checkout") {
      return Response.json({ paypal_order_id: "PAYPAL-1", approval_url: "http://web.test/fake-paypal/PAYPAL-1" });
    }
    if (path === "/api/orders/ord_stall/reserve") return Response.json({ id: "ord_stall", status: "authorized" });
    return Response.json({ detail: "not found" }, { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  delete window.paypal;
});

describe("StallBuy", () => {
  it("in test mode, sends the purchase to simulated PayPal", async () => {
    const calls = api({ mode: "fake", client_id: null, currency: "USD", intent: "authorize" });
    const go = vi.fn();
    render(<StallBuy product={PRODUCT} maker="Priya" go={go} />);

    fireEvent.change(screen.getByLabelText("How many"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Ship to (city)"), { target: { value: "Chicago" } });
    expect(screen.getByText(/3 × \$16\.00 =/)).toHaveTextContent("3 × $16.00 = $48.00, worked out again by OpenStall");
    fireEvent.click(await screen.findByRole("button", { name: /Buy with simulated PayPal/ }));

    await waitFor(() => expect(go).toHaveBeenCalledWith("http://web.test/fake-paypal/PAYPAL-1"));
    expect(calls.filter((call) => call.method === "POST")).toEqual([
      { method: "POST", path: "/api/stall-orders", body: { product_id: "p_priya_cushion", quantity: 3, ship_to: "Chicago" } },
      { method: "POST", path: "/api/orders/ord_stall/checkout", body: {} },
    ]);
  });

  it("asks for the city before anything is drafted", async () => {
    const calls = api({ mode: "fake", client_id: null, currency: "USD", intent: "authorize" });
    render(<StallBuy product={PRODUCT} maker="Priya" go={vi.fn()} />);

    fireEvent.click(await screen.findByRole("button", { name: /Buy with simulated PayPal/ }));

    expect(screen.getByRole("alert")).toHaveTextContent("Say which city it ships to.");
    expect(calls.some((call) => call.method === "POST")).toBe(false);
  });

  it("in sandbox mode, draws PayPal's buttons: they create the PayPal order, then reserve it once approved", async () => {
    const calls = api({ mode: "sandbox", client_id: "made-up-client-id", currency: "USD", intent: "authorize" });
    let options: PayPalButtonsOptions | null = null;
    const render_ = vi.fn(async () => {});
    window.paypal = {
      Buttons: (given) => {
        options = given;
        return { render: render_, close: vi.fn(async () => {}) };
      },
    };
    const go = vi.fn();
    render(<StallBuy product={PRODUCT} maker="Priya" go={go} />);

    await waitFor(() => expect(render_).toHaveBeenCalled());
    fireEvent.change(screen.getByLabelText("Ship to (city)"), { target: { value: "Austin" } });
    const reject = vi.fn(async () => {});
    const resolve = vi.fn(async () => {});
    await waitFor(async () => {
      await options!.onClick?.({}, { resolve, reject });
      expect(resolve).toHaveBeenCalled();
    });

    expect(await options!.createOrder()).toBe("PAYPAL-1");
    await options!.onApprove();

    expect(calls.filter((call) => call.method === "POST").map((call) => call.path)).toEqual([
      "/api/stall-orders",
      "/api/orders/ord_stall/checkout",
      "/api/orders/ord_stall/reserve",
    ]);
    expect(go).toHaveBeenCalledWith("/approve/ord_stall/return");
  });

  it("says so when sandbox mode has no PayPal client id", async () => {
    api({ mode: "sandbox", client_id: null, currency: "USD", intent: "authorize" });

    render(<StallBuy product={PRODUCT} maker="Priya" />);

    expect(await screen.findByText(/PayPal is not connected here yet/)).toBeInTheDocument();
  });
});
