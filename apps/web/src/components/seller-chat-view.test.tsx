import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SellerChatView } from "@/components/seller-chat-view";
import type { ChatSummary, Conversation } from "@/lib/chats";
import type { FeedEvent } from "@/lib/events";

const search = { params: new URLSearchParams("seller=s_amina") };
const stream = { events: [] as FeedEvent[] };
vi.mock("next/navigation", () => ({ useSearchParams: () => search.params }));
vi.mock("@/hooks/use-event-stream", () => ({
  useEventStream: () => ({ events: stream.events, connected: true, error: null }),
}));

const AMINA = { id: "s_amina", name: "Amina", city: "Lahore", country: "PK" };
const CHATS: ChatSummary[] = [
  {
    seller: AMINA,
    channel: "whatsapp",
    state: "collecting",
    updated_at: "2026-11-03T10:05:00Z",
    last_text: "Here is my cushion",
    messages: 2,
  },
  {
    seller: { id: "s_new", name: "Rukhsana", city: null, country: "PK" },
    channel: "whatsapp",
    state: "collecting",
    updated_at: "2026-11-03T09:00:00Z",
    last_text: "Salaam",
    messages: 1,
  },
];
const CONVERSATION: Conversation = {
  seller: AMINA,
  messages: [
    {
      id: "cm_1",
      direction: "inbound",
      channel: "whatsapp",
      text: "Here is my cushion",
      media: [
        { url: "/media/uploads/abc.png", content_type: "image/png", size: 100, refused: null },
        { url: "/media/uploads/def.wav", content_type: "audio/wav", size: 200, refused: null },
        { url: null, content_type: "application/pdf", size: null, refused: "Only photos and voice notes can be kept." },
      ],
      created_at: "2026-11-03T10:04:00Z",
    },
    {
      id: "cm_2",
      direction: "outbound",
      channel: "whatsapp",
      text: "Sorry, I could not keep one of your files.",
      media: [],
      created_at: "2026-11-03T10:05:00Z",
    },
  ],
};

function api(routes: Record<string, () => Response>) {
  return vi.fn((url: string) => {
    const path = new URL(url).pathname;
    const route = routes[path];
    return Promise.resolve(route ? route() : Response.json({ detail: "Not found" }, { status: 404 }));
  });
}

beforeEach(() => {
  search.params = new URLSearchParams("seller=s_amina");
  stream.events = [];
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("SellerChatView", () => {
  it("lists the sellers who have chatted and marks the chosen one", async () => {
    vi.stubGlobal("fetch", api({ "/api/chats": () => Response.json(CHATS), "/api/chats/s_amina": () => Response.json(CONVERSATION) }));

    render(<SellerChatView />);

    const sellers = within(await screen.findByRole("list", { name: "Sellers who have chatted" })).getAllByRole("link");
    expect(sellers.map((link) => link.getAttribute("href"))).toEqual([
      "/seller-chat?seller=s_amina",
      "/seller-chat?seller=s_new",
    ]);
    expect(sellers[0]).toHaveAttribute("aria-current", "page");
    expect(sellers[0]).toHaveTextContent("AminaWhatsAppLahore, PakistanHere is my cushion");
  });

  it("shows her messages as bubbles, with her photo, her voice note and what could not be kept", async () => {
    vi.stubGlobal("fetch", api({ "/api/chats": () => Response.json(CHATS), "/api/chats/s_amina": () => Response.json(CONVERSATION) }));

    render(<SellerChatView />);

    const thread = await screen.findByRole("list", { name: "Messages with Amina" });
    const [fromHer, reply] = within(thread).getAllByRole("listitem").slice(0, 2);
    expect(fromHer).toHaveTextContent(/^Amina: /);
    expect(fromHer).toHaveTextContent("Here is my cushion");
    expect(within(fromHer).getByRole("img", { name: "A photo the seller sent" })).toHaveAttribute(
      "src",
      "http://api.test/media/uploads/abc.png",
    );
    expect(fromHer.querySelector("audio")).toHaveAttribute("src", "http://api.test/media/uploads/def.wav");
    expect(fromHer).toHaveTextContent("A file that was not kept: Only photos and voice notes can be kept.");
    expect(reply).toHaveTextContent("OpenStall: Sorry, I could not keep one of your files.");
  });

  it("without a choice, shows the most recent conversation", async () => {
    search.params = new URLSearchParams();
    vi.stubGlobal("fetch", api({ "/api/chats": () => Response.json(CHATS), "/api/chats/s_amina": () => Response.json(CONVERSATION) }));

    render(<SellerChatView />);

    expect(await screen.findByRole("list", { name: "Messages with Amina" })).toBeInTheDocument();
  });

  it("a new message appears without reloading", async () => {
    const later: Conversation = {
      ...CONVERSATION,
      messages: [
        ...CONVERSATION.messages,
        { id: "cm_3", direction: "inbound", channel: "whatsapp", text: "Mirror work too", media: [], created_at: "2026-11-03T10:06:00Z" },
      ],
    };
    const conversations = [CONVERSATION, later];
    vi.stubGlobal(
      "fetch",
      api({
        "/api/chats": () => Response.json(CHATS),
        "/api/chats/s_amina": () => Response.json(conversations.length > 1 ? conversations.shift() : conversations[0]),
      }),
    );
    const { rerender } = render(<SellerChatView />);
    await screen.findByRole("list", { name: "Messages with Amina" });

    stream.events = [
      {
        id: 7,
        type: "message.received",
        entity_id: "s_amina",
        summary: "Amina sent a message on WhatsApp",
        payload: {},
        created_at: "2026-11-03T10:06:00Z",
      },
    ];
    rerender(<SellerChatView />);

    expect(await screen.findByText("Mirror work too")).toBeInTheDocument();
  });

  it("before anyone writes, says how a chat begins", async () => {
    search.params = new URLSearchParams();
    vi.stubGlobal("fetch", api({ "/api/chats": () => Response.json([]) }));

    render(<SellerChatView />);

    expect(await screen.findByText(/No seller has written yet/)).toBeInTheDocument();
  });

  it("an unknown seller says so", async () => {
    search.params = new URLSearchParams("seller=s_nobody");
    vi.stubGlobal("fetch", api({ "/api/chats": () => Response.json(CHATS) }));

    render(<SellerChatView />);

    expect(await screen.findByRole("alert")).toHaveTextContent("There is no seller at this address.");
  });
});
