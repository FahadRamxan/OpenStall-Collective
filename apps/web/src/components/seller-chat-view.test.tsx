import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SellerChatView } from "@/components/seller-chat-view";
import type { ChatSummary, Conversation } from "@/lib/chats";
import { saveDemoPhone } from "@/lib/demo-phone";
import type { FeedEvent } from "@/lib/events";

const search = { params: new URLSearchParams("seller=s_amina") };
const stream = { events: [] as FeedEvent[] };
const router = { push: vi.fn() };
vi.mock("next/navigation", () => ({ useSearchParams: () => search.params, useRouter: () => router }));
vi.mock("@/hooks/use-event-stream", () => ({
  useEventStream: () => ({ events: stream.events, connected: true, error: null }),
}));

const WELCOME = "Welcome to OpenStall! Send photos of what you make.";
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
const MINE: Conversation = {
  seller: { id: "s_web", name: "Web seller 2B40", city: null, country: null },
  messages: [
    { id: "cm_9", direction: "inbound", channel: "web", text: "I make quilts", media: [], created_at: "2026-11-03T11:00:00Z" },
    { id: "cm_10", direction: "outbound", channel: "web", text: WELCOME, media: [], created_at: "2026-11-03T11:00:01Z" },
  ],
};

type Handler = (init?: RequestInit) => Response;

function api(routes: Record<string, Handler>) {
  return vi.fn((url: string, init?: RequestInit) => {
    const route = routes[`${init?.method ?? "GET"} ${new URL(url).pathname}`];
    return Promise.resolve(route ? route(init) : Response.json({ detail: "Not found" }, { status: 404 }));
  });
}

const BROWSING: Record<string, Handler> = {
  "GET /api/chats": () => Response.json(CHATS),
  "GET /api/chats/s_amina": () => Response.json(CONVERSATION),
};

beforeEach(() => {
  search.params = new URLSearchParams("seller=s_amina");
  stream.events = [];
  router.push.mockClear();
  saveDemoPhone(null);
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("SellerChatView, watching a WhatsApp chat", () => {
  it("lists the sellers who have chatted and marks the one shown", async () => {
    vi.stubGlobal("fetch", api(BROWSING));

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
    vi.stubGlobal("fetch", api(BROWSING));

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
    expect(screen.getByText(/You are watching this chat. It happens on WhatsApp./)).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Send a message" })).not.toBeInTheDocument();
  });

  it("her voice note shows as text too, word for word, marked with the language it was heard in", async () => {
    const urdu = "کڑھائی والے کشن کور، تین رنگوں میں";
    const heard: Conversation = {
      ...CONVERSATION,
      messages: [{ ...CONVERSATION.messages[0], transcript: urdu, language: "ur" }, CONVERSATION.messages[1]],
    };
    vi.stubGlobal("fetch", api({ ...BROWSING, "GET /api/chats/s_amina": () => Response.json(heard) }));

    render(<SellerChatView />);

    const thread = await screen.findByRole("list", { name: "Messages with Amina" });
    const [fromHer, reply] = within(thread).getAllByRole("listitem");
    expect(within(fromHer).getByText("Voice note in Urdu, as text")).toBeInTheDocument();
    expect(within(fromHer).getByText(urdu)).toHaveAttribute("lang", "ur");
    expect(within(reply).queryByText(/as text/)).not.toBeInTheDocument();
  });

  it("OpenStall's answer to her voice note is spoken too, in her language", async () => {
    const answer = {
      ...CONVERSATION.messages[1],
      language: "ur",
      media: [
        { url: "/media/uploads/ans.mp3", content_type: "audio/mpeg", size: 2048, refused: null, spoken: true },
      ],
    };
    const spokenTo: Conversation = { ...CONVERSATION, messages: [CONVERSATION.messages[0], answer] };
    vi.stubGlobal("fetch", api({ ...BROWSING, "GET /api/chats/s_amina": () => Response.json(spokenTo) }));

    render(<SellerChatView />);

    const thread = await screen.findByRole("list", { name: "Messages with Amina" });
    const [fromHer, reply] = within(thread).getAllByRole("listitem");
    const spoken = within(reply).getByLabelText("OpenStall's answer, spoken");
    expect(spoken).toHaveAttribute("src", "http://api.test/media/uploads/ans.mp3");
    expect(reply).toHaveTextContent("Spoken in Urdu");
    expect(within(fromHer).queryByLabelText("OpenStall's answer, spoken")).not.toBeInTheDocument();
  });

  it("shows her listing so far under her chat while she is making one", async () => {
    const drafting: Conversation = {
      ...CONVERSATION,
      draft: {
        title: "Hand-embroidered cushion cover",
        description: null,
        category: "home textiles",
        variants: [],
        price_usd: "18.00",
        capacity_per_week: null,
        ship_days: null,
        ship_from_city: null,
        photos: [],
        words: { price_usd: "$18" },
        missing: ["description", "variants", "capacity_per_week", "ship_days", "ship_from_city", "photos"],
      },
    };
    vi.stubGlobal("fetch", api({ ...BROWSING, "GET /api/chats/s_amina": () => Response.json(drafting) }));

    render(<SellerChatView />);

    const draft = await screen.findByRole("region", { name: /Her listing so far/ });
    expect(draft).toHaveTextContent("Hand-embroidered cushion cover");
    expect(draft).toHaveTextContent("$18.00 each");
    expect(within(draft).getAllByText("Still to ask")).toHaveLength(6);
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
        "GET /api/chats": () => Response.json(CHATS),
        "GET /api/chats/s_amina": () => Response.json(conversations.length > 1 ? conversations.shift() : conversations[0]),
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

  it("her order, told in Urdu, reads right to left, and arrives without reloading", async () => {
    const urdu = "السلام علیکم Amina! OpenStall سے آپ کے لیے ایک نیا آرڈر آیا ہے۔\n\nآرڈر: ord_demo\nتعداد: 12";
    const told: Conversation = {
      ...CONVERSATION,
      messages: [
        ...CONVERSATION.messages,
        { id: "cm_4", direction: "outbound", channel: "web", text: urdu, media: [], created_at: "2026-11-10T10:06:00Z" },
      ],
    };
    const conversations = [CONVERSATION, told];
    vi.stubGlobal(
      "fetch",
      api({
        "GET /api/chats": () => Response.json(CHATS),
        "GET /api/chats/s_amina": () => Response.json(conversations.length > 1 ? conversations.shift() : conversations[0]),
      }),
    );
    const { rerender } = render(<SellerChatView />);
    await screen.findByRole("list", { name: "Messages with Amina" });

    // The notice event is a message.* event, so the chat looks again.
    stream.events = [
      {
        id: 8,
        type: "message.order_notice",
        entity_id: "op_001",
        summary: "Amina was told about her share in the web chat, in Urdu: 12 to ship by December 1",
        payload: { channel: "web" },
        created_at: "2026-11-10T10:06:00Z",
      },
    ];
    rerender(<SellerChatView />);

    const text = await screen.findByText(/آرڈر: ord_demo/);
    expect(text).toHaveAttribute("dir", "auto");
    // Her own words too, in the bubble and in the sellers list's preview.
    for (const words of screen.getAllByText("Here is my cushion")) expect(words).toHaveAttribute("dir", "auto");
  });

  it("in test mode, a maker with no phone can be played: her courier receipt photo, then her reply", async () => {
    const posted: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      api({
        "GET /api/chats": () => Response.json(CHATS),
        "GET /api/chats/s_amina": () => Response.json({ ...CONVERSATION, playable: true }),
        "POST /api/dev/sellers/s_amina/messages": (init) => {
          posted.push(JSON.parse(String(init?.body)));
          return Response.json({ seller_id: "s_amina", message_id: "cm_9", replies: [] }, { status: 201 });
        },
      }),
    );
    render(<SellerChatView />);

    const panel = await screen.findByRole("region", { name: /Play Amina/ });
    expect(panel).toHaveTextContent("Test mode");
    fireEvent.click(within(panel).getByRole("button", { name: /Send her courier receipt photo/ }));
    await waitFor(() => expect(posted).toEqual([{ text: "", receipt: true }]));

    const reply = within(panel).getByRole("textbox", { name: "Reply as Amina" });
    expect(within(panel).getByRole("button", { name: "Send as Amina" })).toBeDisabled();
    fireEvent.change(reply, { target: { value: "ہاں" } });
    fireEvent.click(within(panel).getByRole("button", { name: "Send as Amina" }));

    await waitFor(() => expect(posted).toEqual([{ text: "", receipt: true }, { text: "ہاں", receipt: false }]));
    await waitFor(() => expect(reply).toHaveValue(""));
  });

  it("offers no play panel for a maker who chats from her own phone", async () => {
    vi.stubGlobal("fetch", api(BROWSING));

    render(<SellerChatView />);

    await screen.findByRole("list", { name: "Messages with Amina" });
    expect(screen.queryByRole("region", { name: /Play Amina/ })).not.toBeInTheDocument();
  });

  it("an unknown seller says so", async () => {
    search.params = new URLSearchParams("seller=s_nobody");
    vi.stubGlobal("fetch", api({ "GET /api/chats": () => Response.json(CHATS) }));

    render(<SellerChatView />);

    expect(await screen.findByRole("alert")).toHaveTextContent("There is no seller at this address.");
  });
});

describe("SellerChatView, your own demo phone", () => {
  beforeEach(() => {
    search.params = new URLSearchParams();
  });

  it("starts empty, ready for your first message", async () => {
    vi.stubGlobal("fetch", api({ "GET /api/chats": () => Response.json([]) }));

    render(<SellerChatView />);

    expect(await screen.findByText(/No seller has written yet/)).toBeInTheDocument();
    expect(screen.getByText("Send a photo of something you make, or tell OpenStall about it, to start.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("sends your message from a new demo phone and shows OpenStall's reply", async () => {
    let sent: FormData | null = null;
    const fetchMock = api({
      "GET /api/chats": () => Response.json([]),
      "POST /api/seller-chat/messages": (init) => {
        sent = init?.body as FormData;
        return Response.json({ seller_id: "s_web", message_id: "cm_9", replies: [WELCOME] });
      },
      "GET /api/chats/s_web": () => Response.json(MINE),
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<SellerChatView />);

    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "I make quilts" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText(WELCOME)).toBeInTheDocument();
    const thread = screen.getByRole("list", { name: "Your messages with OpenStall" });
    const [mine, reply] = within(thread).getAllByRole("listitem");
    expect(mine).toHaveTextContent(/^You: I make quilts/);
    expect(mine).toHaveTextContent("Sent");
    expect(reply).toHaveTextContent(`OpenStall: ${WELCOME}`);
    expect(sent!.get("text")).toBe("I make quilts");
    expect(sent!.get("sender")).toMatch(/^demo-[0-9a-f]{12}$/);
    expect(JSON.parse(window.localStorage.getItem("openstall-demo-phone")!)).toEqual({
      id: sent!.get("sender"),
      sellerId: "s_web",
    });
    expect(screen.getByLabelText("Message")).toHaveValue("");
  });

  it("sends an attached photo with the message", async () => {
    let sent: FormData | null = null;
    vi.stubGlobal(
      "fetch",
      api({
        "GET /api/chats": () => Response.json([]),
        "POST /api/seller-chat/messages": (init) => {
          sent = init?.body as FormData;
          return Response.json({ seller_id: "s_web", message_id: "cm_9", replies: [WELCOME] });
        },
        "GET /api/chats/s_web": () => Response.json(MINE),
      }),
    );
    render(<SellerChatView />);
    const photo = new File(["png"], "cushion.png", { type: "image/png" });

    fireEvent.change(screen.getByLabelText("Attach a photo"), { target: { files: [photo] } });
    expect(within(screen.getByRole("list", { name: "Attached" })).getByText("cushion.png")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText(WELCOME)).toBeInTheDocument();
    expect((sent!.getAll("files")[0] as File).name).toBe("cushion.png");
  });

  it("a message that could not be sent stays in the box, with the reason", async () => {
    vi.stubGlobal(
      "fetch",
      api({
        "GET /api/chats": () => Response.json([]),
        "POST /api/seller-chat/messages": () =>
          Response.json({ detail: "Write a message or attach a photo or voice note." }, { status: 422 }),
      }),
    );
    render(<SellerChatView />);

    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "Hello?" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Not sent: Write a message or attach");
    expect(screen.getByLabelText("Message")).toHaveValue("Hello?");
  });

  it("in test mode, offers the sample voice note, sent like one you recorded", async () => {
    let sent: FormData | null = null;
    vi.stubGlobal(
      "fetch",
      api({
        "GET /api/chats": () => Response.json([]),
        "GET /api/seller-chat/samples": () =>
          Response.json({ voice_note: "/api/dev/samples/voice-note.wav", photo: "/api/dev/samples/photo.png" }),
        "GET /api/dev/samples/voice-note.wav": () => new Response("RIFF", { headers: { "Content-Type": "audio/wav" } }),
        "POST /api/seller-chat/messages": (init) => {
          sent = init?.body as FormData;
          return Response.json({ seller_id: "s_web", message_id: "cm_9", replies: [WELCOME] });
        },
        "GET /api/chats/s_web": () => Response.json(MINE),
      }),
    );
    render(<SellerChatView />);

    fireEvent.click(await screen.findByRole("button", { name: /Attach the sample voice note/ }));
    await screen.findByRole("button", { name: "Remove the voice note" });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText(WELCOME)).toBeInTheDocument();
    const file = sent!.get("files") as File;
    expect([file.name, file.type]).toEqual(["sample-voice-note.wav", "audio/wav"]);
  });

  it("outside test mode there is no sample voice note to attach", async () => {
    vi.stubGlobal(
      "fetch",
      api({
        "GET /api/chats": () => Response.json([]),
        "GET /api/seller-chat/samples": () => Response.json({ voice_note: null, photo: null }),
      }),
    );

    render(<SellerChatView />);

    expect(await screen.findByText(/No seller has written yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sample voice note/ })).not.toBeInTheDocument();
  });

  it("without a microphone, offers to upload a voice note instead", async () => {
    vi.stubGlobal("fetch", api({ "GET /api/chats": () => Response.json([]) }));

    render(<SellerChatView />);

    expect(await screen.findByLabelText("Upload a voice note")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Record a voice note" })).not.toBeInTheDocument();
  });

  it("Start as a new seller forgets this browser's seller", async () => {
    saveDemoPhone({ id: "demo-3f9a1c7e2b40", sellerId: "s_web" });
    vi.stubGlobal(
      "fetch",
      api({ "GET /api/chats": () => Response.json([]), "GET /api/chats/s_web": () => Response.json(MINE) }),
    );
    render(<SellerChatView />);
    expect(await screen.findByText("I make quilts")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Start as a new seller" }));

    expect(window.localStorage.getItem("openstall-demo-phone")).toBeNull();
    expect(router.push).toHaveBeenCalledWith("/seller-chat");
    expect(screen.queryByText("I make quilts")).not.toBeInTheDocument();
  });
});
