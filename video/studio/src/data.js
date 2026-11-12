/* OpenStall demo video: data.
 * Times are seconds on narration-draft.mp3. The narration lines, their times and every chat message are loaded at
 * start from the kit's own files (narration-timecodes.json, whatsapp-real-chat.json, whatsapp-scripts.json), so the
 * captions and the phones always show the exact words. This file only says how to cut and time them. */
(function () {
  "use strict";

  // Length of the whole video: the last line ends at 165.62, then a silent end card.
  window.VIDEO = { duration: 170.6, endCard: 165.95 };

  window.BRAND = {
    paper: "#f8f6f1",
    surface: "#ffffff",
    ink: "#1c1714",
    muted: "#5a514a",
    border: "#e8e1d7",
    teal: "#0e6e64",
    tealStrong: "#0a574f",
    tealSoft: "#e1f2ee",
  };

  // One colour per maker, used everywhere she appears.
  window.MAKERS = {
    amina: { name: "Amina", city: "Lahore", country: "Pakistan", color: "#eb6834", lang: "Urdu", lat: 31.55, lon: 74.34, qty: 12, unit: 18, total: 216 },
    priya: { name: "Priya", city: "Jaipur", country: "India", color: "#2a78d6", lang: "Hindi", lat: 26.91, lon: 75.79, qty: 11, unit: 16, total: 176 },
    lucia: { name: "Lucía", city: "Oaxaca", country: "Mexico", color: "#1baf7a", lang: "Spanish", lat: 17.07, lon: -96.73, qty: 10, unit: 22, total: 220 },
    grace: { name: "Grace", city: "Detroit", country: "United States", color: "#eda100", lang: "English", lat: 42.33, lon: -83.05, qty: 7, unit: 29, total: 203 },
    noor: { name: "Noor", city: "Manchester", country: "United Kingdom", color: "#e87ba4", lang: "English", lat: 53.48, lon: -2.24 },
  };

  // Captions: each narration line (in order, from narration-timecodes.json) cut into readable pieces at the voice's
  // own pauses. [text, start] — the first piece starts with the line. The pieces must join (with one space) into the
  // exact line; main.js checks that on load and refuses to start if they don't.
  window.CAPTION_CUTS = [
    [["Forty hand-embroidered cushion covers... needed in thirty days."]],
    [["One AI shopping agent, ready to buy."]],
    [["And the women who make them best sell only on WhatsApp..."], ["and none of them can make forty alone.", 11.9]],
    [["OpenStall Collective turns them into one supplier,"], ["in three steps: list, split, and pay on proof.", 17.77]],
    [["Claude does the talking. Code decides. PayPal holds the money."]],
    [["Step one: list."]],
    [["This is a real chat on OpenStall's WhatsApp number."], ["A maker writes one line in Urdu... and sends a photo.", 33.75]],
    [["Claude reads the photo: a blue paisley cushion cover."], ["Every number in the listing comes from the maker's own words.", 41.75]],
    [["OpenStall asks only for what's missing,"], ["one short question at a time, in Urdu.", 48.36]],
    [["One tap on haan, yes..."], ["and the stall is live, for any AI agent to read.", 54.08]],
    [["Step two: split."]],
    [["A buyer's AI agent asks OpenStall's MCP storefront for forty covers,"], ["at most thirty dollars each.", 66.47]],
    [["Each maker's agent bids,"], ["and code checks every price against her floor and the buyer's maximum.", 70.67]],
    [
      ["Plain code splits the order: twelve from Amina, eleven from Priya,"],
      ["ten from Lucía, seven from Grace...", 79.76],
      ["eight hundred and fifteen dollars.", 82.75],
    ],
    [["The agent can't pay."], ["A person approves one PayPal checkout, intent authorize...", 87.27], ["so PayPal only holds the money.", 90.98]],
    [["Each maker hears about her share on her phone, in her own language."]],
    [["Step three: pay on proof."]],
    [["Priya ships her parcel in Jaipur and photographs the courier receipt."]],
    [["AI reads the courier and the tracking number..."], ["and Priya confirms with one tap.", 107.15]],
    [
      ["Only then is her share captured from that one authorization,"],
      ["and paid out to her PayPal...", 113.25],
      ["with her tracking on the PayPal order.", 114.9],
    ],
    [["In Pakistan, where Payouts can't reach,"], ["Amina is paid to her bank through Hyperwallet...", 119.86], ["simulated here, and labelled.", 122.54]],
    [["And if Grace can't make it?"]],
    [["Her share is released, never charged..."], ["and the other makers' agents bid for her seven covers, as a top-up.", 130.42]],
    [["Try to break it: ten real attacks..."], ["all refused by the code they target.", 137.76]],
    [["Every maker carries a signed trust passport."], ["Change one number, and the signature fails.", 143.52]],
    [["Orders and payments run on APIMatic's PayPal SDK..."], ["and an ops agent checks them through PayPal's own MCP server, read-only.", 150.48]],
    [["A receipt photo can be faked,"], ["so next, the courier's own scan will release the money.", 157.64]],
    [["Claude talks."]],
    [["Code decides."]],
    [["PayPal pays on proof."]],
  ];

  // Screen recordings: frame counts from ffprobe (all 1920x1080, 60 fps).
  window.CLIPS = {
    R2: { file: "R2-run.mp4", frames: 1992 },
    R3: { file: "R3-approve.mp4", frames: 2033 },
    R7: { file: "R7-attacks.mp4", frames: 965 },
    R8: { file: "R8-tamper.mp4", frames: 1294 },
    R9: { file: "R9-status-hosted.mp4", frames: 1399 },
    R12: { file: "R12-receipt.mp4", frames: 2340 },
  };

  // Shots: one use of a clip. map = [[video time, clip time], ...] (straight lines between, held outside; the clips
  // are still pages between their scrolls, so holds are invisible). cam = [[time, [cx, cy, zoom], ease], ...] in the
  // clip's own pixels: (cx, cy) is put at the centre of the browser window, zoom 1 shows the whole 1920x1080 page.
  // hl = highlight boxes in clip pixels: {t, until, box: [x0, y0, x1, y1], tone}.
  // The comments give the clip's key moments (see recordings/moments.json).
  window.SHOTS = {
    // R2: /demo. 5.75 Run the demo request; 9.25 Request; 17.82 Offers (still to 22.40); 24.02 Allocation.
    r2a: {
      clip: "R2", frame: "main", t0: 60.9, t1: 69.2, fadeIn: 0, fadeOut: 0.35,
      map: [[60.9, 2.5], [69.2, 10.8]],
      cam: [
        [60.9, [960, 540, 1.0]],
        [62.1, [960, 540, 1.0]],
        [63.5, [700, 690, 1.38], "inOutCubic"],
        [65.9, [700, 690, 1.38]],
        [67.6, [690, 400, 1.45], "inOutCubic"],
      ],
      hl: [
        { t: 63.9, until: 65.6, box: [52, 890, 372, 966], tone: "teal" },
        { t: 67.9, until: 69.3, box: [56, 380, 1270, 430], tone: "teal" },
      ],
    },
    r2b: {
      clip: "R2", frame: "main", t0: 68.85, t1: 85.95, fadeIn: 0.35, fadeOut: 0.4,
      map: [[68.85, 17.45], [75.35, 22.38], [77.1, 24.13], [81.85, 28.85]],
      cam: [
        [68.85, [800, 630, 1.2]],
        [70.2, [800, 630, 1.2]],
        [71.2, [540, 770, 1.8], "inOutCubic"],
        [72.5, [540, 770, 1.8]],
        [73.5, [960, 540, 1.0], "inOutCubic"],
        [84.9, [960, 540, 1.0]],
      ],
      hl: [
        { t: 70.95, until: 73.3, box: [42, 702, 640, 812], tone: "warn", label: "Refused: over the buyer's maximum" },
        { t: 71.75, until: 73.3, box: [42, 838, 640, 900], tone: "teal" },
        { t: 73.65, until: 75.2, box: [42, 1032, 640, 1080], tone: "warn" },
        { t: 74.0, until: 75.2, box: [1372, 1000, 1890, 1054], tone: "teal" },
      ],
    },
    // R3: approval page 4.65; simulated PayPal page 16.58 (Test mode banner), scroll 18.57-19.62, Approve click 21.43;
    // "Simulated PayPal is holding $815.00" 23.05.
    r3a: {
      clip: "R3", frame: "main", t0: 85.55, t1: 88.6, fadeIn: 0.4, fadeOut: 0.35,
      map: [[85.55, 4.66], [87.69, 6.8]],
      cam: [
        [85.55, [800, 420, 1.35]],
        [86.3, [800, 420, 1.35]],
        [87.3, [800, 360, 1.55], "inOutCubic"],
      ],
      hl: [{ t: 86.15, until: 88.6, box: [220, 290, 1386, 408], tone: "teal" }],
    },
    r3c: {
      clip: "R3", frame: "main", t0: 88.25, t1: 91.5, fadeIn: 0.35, fadeOut: 0.35,
      map: [[88.25, 17.25], [89.05, 18.4], [89.85, 19.65], [91.15, 21.45]],
      cam: [
        [88.25, [960, 560, 1.12]],
        [89.2, [960, 560, 1.12]],
        [90.3, [960, 470, 1.42], "inOutCubic"],
      ],
      hl: [],
    },
    r3d: {
      clip: "R3", frame: "main", t0: 91.15, t1: 93.8, fadeIn: 0.35, fadeOut: 0,
      map: [[91.15, 23.05], [93.8, 25.7]],
      cam: [
        [91.15, [760, 420, 1.3]],
        [92.6, [720, 360, 1.5], "inOutCubic"],
      ],
      hl: [{ t: 91.85, until: 93.8, box: [222, 416, 1094, 456], tone: "amber" }],
    },
    // R12: the buyer's receipt. Priya's row still 4.60-10.17; Amina's 12.90-16.32; the order heals itself 23.18-.
    r12p: {
      clip: "R12", frame: "side", t0: 114.75, t1: 117.75, fadeIn: 0, fadeOut: 0,
      map: [[114.75, 4.65], [117.75, 7.65]],
      cam: [[114.75, [803, 400, 1.6]], [117.75, [803, 395, 1.68], "inOutSine"]],
      hl: [
        { t: 115.35, until: 117.75, box: [1074, 316, 1344, 350], tone: "teal" },
        { t: 115.95, until: 117.75, box: [242, 440, 860, 498], tone: "teal" },
      ],
    },
    r12a: {
      clip: "R12", frame: "side", t0: 122.65, t1: 125.45, fadeIn: 0, fadeOut: 0,
      map: [[122.65, 13.0], [125.45, 15.8]],
      cam: [[122.65, [803, 430, 1.6]], [125.45, [803, 425, 1.68], "inOutSine"]],
      hl: [{ t: 123.2, until: 125.45, box: [252, 386, 734, 420], tone: "amber" }],
    },
    r12g: {
      clip: "R12", frame: "side", t0: 133.3, t1: 135.25, fadeIn: 0, fadeOut: 0,
      map: [[133.3, 23.3], [135.25, 25.25]],
      cam: [[133.3, [803, 440, 1.6]], [135.25, [803, 440, 1.66], "inOutSine"]],
      hl: [{ t: 133.85, until: 135.25, box: [244, 466, 1164, 502], tone: "teal" }],
    },
    // R7: Try every attack 7.61 -> 10 of 10 refused; scroll through the rows 9.92-13.22.
    r7: {
      clip: "R7", frame: "main", t0: 134.85, t1: 141.05, fadeIn: 0, fadeOut: 0.3,
      map: [[134.85, 5.85], [139.0, 10.0], [140.75, 13.25]],
      cam: [
        [134.85, [700, 520, 1.3]],
        [136.2, [700, 520, 1.3]],
        [137.4, [640, 580, 1.5], "inOutCubic"],
        [139.0, [640, 580, 1.5]],
        [140.6, [720, 560, 1.3], "inOutCubic"],
      ],
      hl: [{ t: 137.95, until: 139.2, box: [300, 426, 548, 462], tone: "teal" }],
    },
    // R8: on-time rate typed to 0.99 at 7.52-8.08; Check the signature 10.72 -> red; Put it back 17.03 -> valid.
    r8a: {
      clip: "R8", frame: "main", t0: 140.75, t1: 144.75, fadeIn: 0.3, fadeOut: 0.25,
      map: [[140.75, 4.5], [144.75, 8.5]],
      cam: [[140.75, [700, 480, 1.35]], [142.0, [640, 470, 1.6], "inOutCubic"]],
      hl: [{ t: 143.95, until: 144.75, box: [462, 340, 862, 396], tone: "warn" }],
    },
    r8b: {
      clip: "R8", frame: "main", t0: 144.5, t1: 146.25, fadeIn: 0.25, fadeOut: 0.25,
      map: [[144.5, 10.4], [146.25, 12.15]],
      cam: [[144.5, [640, 470, 1.6]], [146.25, [640, 480, 1.64], "inOutSine"]],
      hl: [
        { t: 144.5, until: 146.25, box: [462, 340, 862, 396], tone: "warn" },
        { t: 145.0, until: 146.25, box: [58, 676, 940, 708], tone: "warn" },
      ],
    },
    r8c: {
      clip: "R8", frame: "main", t0: 146.0, t1: 147.45, fadeIn: 0.25, fadeOut: 0.3,
      map: [[146.0, 16.85], [147.45, 18.3]],
      cam: [[146.0, [640, 480, 1.64]], [147.45, [640, 480, 1.6], "inOutSine"]],
      hl: [{ t: 146.55, until: 147.45, box: [58, 676, 720, 708], tone: "teal" }],
    },
    // R9: the hosted /status on PayPal's real sandbox. Doctor 4.22-8.17 (still); APIMatic cross-check 10.50-14.12.
    r9a: {
      clip: "R9", frame: "main", t0: 147.15, t1: 150.9, fadeIn: 0.3, fadeOut: 0.35,
      map: [[147.15, 10.55], [150.9, 14.1]],
      cam: [[147.15, [800, 372, 1.35]], [148.6, [800, 372, 1.45], "inOutCubic"]],
      hl: [{ t: 147.9, until: 150.9, box: [252, 160, 1366, 478], tone: "teal" }],
    },
    r9b: {
      clip: "R9", frame: "main", t0: 150.55, t1: 156.3, fadeIn: 0.35, fadeOut: 0,
      map: [[150.55, 4.3], [154.4, 8.15]],
      cam: [[150.55, [800, 430, 1.32]], [152.0, [800, 420, 1.42], "inOutCubic"]],
      hl: [
        { t: 151.2, until: 156.3, box: [222, 306, 402, 340], tone: "teal" },
        { t: 151.8, until: 156.3, box: [244, 392, 1366, 458], tone: "teal" },
      ],
    },
  };

  // Phone chats: which messages show, and when. msg = index into the kit's chat JSON. "tap" puts a ripple on a
  // quick-reply button and sends its title back as her message, as WhatsApp does. hl = words to mark in a message
  // (and in its English line), at a time.
  window.CHATS = {
    real: {
      source: "real",
      time: "15:11",
      date: "10 November 2026",
      label: "A real WhatsApp chat, November 10",
      // The stall link is shown on the hosted address, as the brief asks.
      replace: [["http://localhost:3000/stall/s_c46af5c690b8", "openstall-collective.onrender.com/stall/…"]],
      events: [
        { msg: 0, at: 34.15 },
        { msg: 1, at: 35.1, typing: 0.5 },
        { msg: 2, at: 35.95, typing: 0.45 },
        { msg: 3, at: 36.55 },
        { msg: 4, at: 39.55, typing: 0.6 },
        { msg: 5, at: 42.25 },
        { msg: 6, at: 42.95, typing: 0.4 },
        { msg: 7, at: 43.85 },
        { msg: 8, at: 44.55, typing: 0.4 },
        { msg: 9, at: 45.75 },
        { msg: 10, at: 46.45, typing: 0.4 },
        { msg: 11, at: 47.35 },
        { msg: 12, at: 48.05, typing: 0.4 },
        { msg: 13, at: 48.95 },
        { msg: 14, at: 49.65, typing: 0.4 },
        { msg: 15, at: 50.5 },
        { msg: 16, at: 51.35, typing: 0.55 },
        { msg: 17, at: 53.15, tap: 52.75 },
        { msg: 18, at: 54.15, typing: 0.7 },
      ],
      hl: [{ msg: 4, text: "نیلے نقش والا کشن کور", en: "Blue patterned cushion cover", at: 40.0 }],
      // Claude reading the photo: a soft scan over it
      scan: { msg: 3, t0: 38.1, t1: 39.35 },
    },
    amina: {
      source: "A2", maker: "amina", time: "18:07",
      events: [
        { msg: 0, at: 0, stamp: "18:07" },
        { msg: 1, at: 118.15, stamp: "18:08", flash: 117.95 },
        { msg: 2, at: 118.95, typing: 0.45, stamp: "18:08" },
        { msg: 3, at: 120.25, tap: 119.95, stamp: "18:08" },
        { msg: 4, at: 120.85, typing: 0.35, stamp: "18:08" },
        { msg: 5, at: 121.55, typing: 0.35, stamp: "18:08" },
      ],
      hl: [
        { msg: 2, text: "TCS", en: "TCS", at: 119.3 },
        { msg: 2, text: "7712345678", en: "7712345678", at: 119.55 },
        { msg: 5, text: "Hyperwallet", en: "Hyperwallet", at: 121.95 },
        { msg: 5, text: "(ٹیسٹ موڈ: نقلی PayPal، کوئی اصل رقم منتقل نہیں ہوئی۔)", en: "(Test mode: simulated PayPal, no real money moved.)", at: 122.6, tone: "warn" },
      ],
    },
    priya: {
      source: "A3", maker: "priya", time: "18:07",
      events: [
        { msg: 0, at: 0, stamp: "18:07" },
        { msg: 1, at: 102.45, stamp: "18:08", flash: 102.25 },
        { msg: 2, at: 104.95, typing: 0.5, stamp: "18:08" },
        { msg: 3, at: 108.5, tap: 108.15, stamp: "18:08" },
        { msg: 4, at: 109.3, typing: 0.4, stamp: "18:08" },
        { msg: 5, at: 113.45, typing: 0.45, stamp: "18:08" },
      ],
      hl: [
        { msg: 2, text: "India Post", en: "India Post", at: 105.55 },
        { msg: 2, text: "EE123456789IN", en: "EE123456789IN", at: 106.25 },
        { msg: 5, text: "आपको भुगतान हो गया!", en: "You are paid!", at: 113.9 },
        { msg: 5, text: "(टेस्ट मोड: नकली PayPal, कोई असली पैसा नहीं भेजा गया।)", en: "(Test mode: simulated PayPal, no real money moved.)", at: 114.4, tone: "warn" },
      ],
    },
    lucia: { source: "A4", maker: "lucia", time: "18:07", events: [{ msg: 0, at: 94.54, typing: 0.5, stamp: "18:07" }], hl: [] },
    grace: {
      source: "A5", maker: "grace", time: "18:07",
      events: [
        { msg: 0, at: 0, stamp: "18:07" },
        { msg: 1, at: 125.95, stamp: "18:09" },
        { msg: 2, at: 126.85, typing: 0.45, stamp: "18:09" },
        { msg: 3, at: 128.6, tap: 128.25, tapButton: 0, stamp: "18:09" },
        { msg: 4, at: 129.4, typing: 0.4, stamp: "18:09" },
      ],
      hl: [{ msg: 4, text: "nothing is charged for it", en: null, at: 129.9 }],
    },
  };
  // Sound: besides a soft pop for every message and a tick for every tap (worked out from CHATS), a small chime when
  // a maker is paid on the hold card. Levels are in tools/make-audio.mjs; music is optional (--music file).
  window.SFX_EXTRA = [
    { t: 113.45, kind: "chime" },
    { t: 121.6, kind: "chime" },
  ];

  // The four phones at once (93.5): each gets her order message.
  window.CHATS.amina4 = { source: "A2", maker: "amina", time: "18:07", events: [{ msg: 0, at: 94.3, typing: 0.5, stamp: "18:07" }], hl: [] };
  window.CHATS.priya4 = { source: "A3", maker: "priya", time: "18:07", events: [{ msg: 0, at: 94.42, typing: 0.5, stamp: "18:07" }], hl: [] };
  window.CHATS.grace4 = { source: "A5", maker: "grace", time: "18:07", events: [{ msg: 0, at: 94.66, typing: 0.5, stamp: "18:07" }], hl: [] };
})();
