import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MakerPhones, PHONE_MESSAGES, YES_WORDS } from "@/components/maker-phones";
import type { EventStreamState } from "@/hooks/use-event-stream";
import type { LatestOrderState } from "@/hooks/use-latest-order";
import type { Conversation } from "@/lib/chats";
import type { FeedEvent } from "@/lib/events";
import type { Order, OrderPart } from "@/lib/orders";

const stream: EventStreamState = { events: [], connected: true, error: null };
const latest: LatestOrderState = { order: undefined, error: null };
vi.mock("@/hooks/use-event-stream", async (original) => ({
  ...(await original<typeof import("@/hooks/use-event-stream")>()),
  useEventStream: () => stream,
}));
vi.mock("@/hooks/use-latest-order", () => ({ useLatestOrder: () => latest }));

const NOTICE_HI = "नमस्ते Priya! OpenStall से आपके लिए एक नया ऑर्डर आया है।";
const NOTICE_UR = "السلام علیکم Amina! OpenStall سے آپ کے لیے ایک نیا آرڈر آیا ہے۔";

function share(name: string, seller: string, language: string, extra: Partial<OrderPart> = {}): OrderPart {
  return {
    id: `op_${seller}`,
    reference_id: "op_001",
    seller: { id: seller, name, city: seller === "s_priya" ? "Jaipur" : "Lahore", country: seller === "s_priya" ? "IN" : "PK" },
    product_title: "Cushion cover",
    photo: null,
    quantity: 11,
    unit_price_usd: "16.00",
    amount_usd: "176.00",
    delivery_date: "2026-12-10",
    status: "authorized",
    notice: { state: "sent", channel: "web", language, at: "2026-11-10T10:06:00Z" },
    confirmed_by_paypal: true,
    attention: null,
    confirmation_source: "simulated",
    nothing_to_confirm: false,
    payout_rail: "paypal",
    payout_label: "Paid to PayPal when she ships (simulated)",
    payout_via_paypal: true,
    payout_confirmed: false,
    trust_score: "0.95",
    trust_data_source: "seeded_demo",
    ...extra,
  };
}

const ORDER: Order = {
  id: "ord_story",
  status: "authorized",
  total_usd: "392.00",
  units: 23,
  created_at: "2026-11-10T10:00:00Z",
  approved_at: "2026-11-10T10:05:00Z",
  paypal_order_id: "FAKE-1",
  parent_order_id: null,
  request: null,
  parts: [share("Priya", "s_priya", "hi"), share("Amina", "s_amina", "ur")],
};

function chat(id: string, name: string, texts: string[], playable = true): Conversation {
  return {
    seller: { id, name, city: null, country: null },
    playable,
    messages: texts.map((text, index) => ({
      id: `cm_${id}_${index}`,
      direction: text.startsWith("me:") ? "inbound" : "outbound",
      channel: "web",
      text: text.replace(/^me:/, ""),
      media: [],
      created_at: "2026-11-10T10:06:00Z",
    })),
  };
}

type Handler = (init?: RequestInit) => Response;

function api(routes: Record<string, Handler>) {
  return vi.fn((url: string, init?: RequestInit) => {
    const route = routes[`${init?.method ?? "GET"} ${new URL(url).pathname}`];
    return Promise.resolve(route ? route(init) : Response.json({ detail: "Not found" }, { status: 404 }));
  });
}

beforeEach(() => {
  stream.events = [];
  Object.assign(latest, { order: undefined, error: null });
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("MakerPhones", () => {
  it("shows each maker's phone, her order in her own language, as she sees it", async () => {
    latest.order = ORDER;
    vi.stubGlobal(
      "fetch",
      api({
        "GET /api/chats/s_priya": () => Response.json(chat("s_priya", "Priya", [NOTICE_HI])),
        "GET /api/chats/s_amina": () => Response.json(chat("s_amina", "Amina", [NOTICE_UR])),
      }),
    );

    render(<MakerPhones />);

    const phones = within(screen.getByRole("list", { name: "The makers' phones" })).getAllByRole("article");
    expect(phones).toHaveLength(2);
    expect(phones[0]).toHaveAccessibleName("Priya's phone");
    expect(phones[0]).toHaveTextContent("Jaipur, India · Speaks Hindi");
    const urdu = await within(phones[1]).findByText(NOTICE_UR);
    expect(urdu).toHaveAttribute("dir", "auto");
    expect(within(phones[0]).getByRole("link", { name: "Open Priya's chat" })).toHaveAttribute(
      "href",
      "/seller-chat?seller=s_priya",
    );
  });

  it("in test mode, plays a maker: her courier receipt, then yes in her language when she is asked", async () => {
    const posted: unknown[] = [];
    latest.order = {
      ...ORDER,
      parts: [
        ORDER.parts[0],
        share("Amina", "s_amina", "ur", {
          proof: {
            state: "awaiting_confirmation",
            photo_url: "/media/uploads/r.png",
            carrier: "TCS",
            tracking_number: "7712345678",
            source: "photo",
            read_by: "stand-in",
          },
        }),
      ],
    };
    vi.stubGlobal(
      "fetch",
      api({
        "GET /api/chats/s_priya": () => Response.json(chat("s_priya", "Priya", [NOTICE_HI])),
        "GET /api/chats/s_amina": () => Response.json(chat("s_amina", "Amina", [NOTICE_UR])),
        "POST /api/dev/sellers/s_priya/messages": (init) => {
          posted.push(JSON.parse(String(init?.body)));
          return Response.json({ seller_id: "s_priya", message_id: "cm_9", replies: [] }, { status: 201 });
        },
        "POST /api/dev/sellers/s_amina/messages": (init) => {
          posted.push(JSON.parse(String(init?.body)));
          return Response.json({ seller_id: "s_amina", message_id: "cm_10", replies: [] }, { status: 201 });
        },
      }),
    );

    render(<MakerPhones />);

    const priya = screen.getByRole("article", { name: "Priya's phone" });
    const amina = screen.getByRole("article", { name: "Amina's phone" });
    fireEvent.click(await within(priya).findByRole("button", { name: /Send Priya's courier receipt/ }));
    await waitFor(() => expect(posted).toEqual([{ text: "", receipt: true }]));
    // Amina is being asked about her tracking: she answers yes, in Urdu.
    expect(within(amina).queryByRole("button", { name: /courier receipt/ })).not.toBeInTheDocument();
    fireEvent.click(within(amina).getByRole("button", { name: new RegExp(`Reply .${YES_WORDS.ur}. as Amina`) }));
    await waitFor(() => expect(posted).toEqual([{ text: "", receipt: true }, { text: "ہاں", receipt: false }]));
  });

  it("offers nothing to play for a maker with her own phone, or one who is already paid", async () => {
    latest.order = { ...ORDER, parts: [share("Priya", "s_priya", "hi", { status: "captured", tracking_number: "EE1" }), ORDER.parts[1]] };
    vi.stubGlobal(
      "fetch",
      api({
        "GET /api/chats/s_priya": () => Response.json(chat("s_priya", "Priya", [NOTICE_HI])),
        "GET /api/chats/s_amina": () => Response.json(chat("s_amina", "Amina", [NOTICE_UR], false)),
      }),
    );

    render(<MakerPhones />);

    await screen.findByText(NOTICE_UR);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows only her latest messages, and looks again when a message arrives", async () => {
    latest.order = { ...ORDER, parts: [ORDER.parts[0]] };
    const texts = Array.from({ length: PHONE_MESSAGES + 3 }, (_, index) => `message ${index + 1}`);
    const fetch = api({ "GET /api/chats/s_priya": () => Response.json(chat("s_priya", "Priya", texts)) });
    vi.stubGlobal("fetch", fetch);
    const view = render(<MakerPhones />);

    const thread = await screen.findByRole("list", { name: "Messages on Priya's phone" });
    await within(thread).findByText(`message ${PHONE_MESSAGES + 3}`);
    expect(within(thread).queryByText("message 3")).not.toBeInTheDocument();
    expect(within(thread).getAllByRole("listitem")).toHaveLength(PHONE_MESSAGES);

    const event: FeedEvent = {
      id: 9,
      type: "message.received",
      entity_id: "s_priya",
      summary: "Priya sent a photo",
      payload: {},
      created_at: "2026-11-10T10:07:00Z",
    };
    stream.events = [event];
    view.rerender(<MakerPhones />);

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  });

  it("says when there is no order yet", () => {
    latest.order = null;

    render(<MakerPhones />);

    expect(screen.getByText(/No order yet/)).toBeInTheDocument();
  });
});
