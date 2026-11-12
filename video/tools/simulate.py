"""The whole story, played through the local test-mode API (http://localhost:8000, OPENSTALL_MODE=fake) exactly as the
pages play it, then every chat written out for the video's WhatsApp animations: video/whatsapp-scripts.md and
whatsapp-scripts.json. Test mode only: it refuses to run against any API not in fake mode."""

import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

sys.stdout.reconfigure(encoding="utf-8")
API = "http://localhost:8000"
HOSTED_API = "https://openstall-collective-api.onrender.com"
KIT = Path(__file__).resolve().parents[1]
c = httpx.Client(base_url=API, timeout=120)


def post(path: str, **kwargs):
    response = c.post(path, **kwargs)
    if response.status_code >= 400:
        raise SystemExit(f"{path}: {response.status_code} {response.text[:300]}")
    return response.json() if response.content else None


def step(title: str) -> None:
    print(f"\n== {title}")


assert c.get("/api/status").json()["mode"] == "fake", "refusing: the local API is not in test mode"

step("reset the demo world")
post("/api/demo/reset")

step("a buyer agent asks for 40 cushion covers; the order is drafted")
run = post("/api/demo/run")
order_id = run["order_id"]
print("  order", order_id, run.get("total_usd"))

step("a person approves at simulated PayPal; the order is reserved")
checkout = post(f"/api/orders/{order_id}/checkout")
parts = urlsplit(checkout["approval_url"])
print("  approval url:", checkout["approval_url"])
token = (parse_qs(parts.query).get("token") or [parts.path.rstrip("/").split("/")[-1]])[0]
post(f"/api/dev/fake-paypal/{token}/approve")
reserved = post(f"/api/orders/{order_id}/reserve")
print("  status", reserved.get("status"))
time.sleep(4)  # each maker is told after the answer

step("Priya sends her courier receipt and confirms in Hindi")
post("/api/dev/sellers/s_priya/messages", json={"receipt": True})
post("/api/dev/sellers/s_priya/messages", json={"text": "हाँ"})
step("Amina sends hers and confirms in Urdu")
post("/api/dev/sellers/s_amina/messages", json={"receipt": True})
post("/api/dev/sellers/s_amina/messages", json={"text": "جی ہاں"})
step("Grace cannot make it, and confirms")
post("/api/dev/sellers/s_grace/messages", json={"text": "Sorry, I can't make this order."})
post("/api/dev/sellers/s_grace/messages", json={"text": "Yes"})
time.sleep(4)

step("a new maker lists her cushion cover from the web demo phone (sample photo and Urdu voice note)")
photo = c.get("/api/dev/samples/photo.png").content
voice = c.get("/api/dev/samples/voice-note.wav").content
sender = "videomaker01"
first = post("/api/seller-chat/messages", data={"sender": sender, "text": ""},
             files=[("files", ("photo.png", photo, "image/png")), ("files", ("voice-note.wav", voice, "audio/wav"))])
new_seller = first["seller_id"]
for answer in ["9", "Lahore", "15", "5", "ہاں"]:
    reply = post("/api/seller-chat/messages", data={"sender": sender, "text": answer})
    print(f"  she says {answer!r}: {len(reply['replies'])} replies")
    time.sleep(0.4)

order = c.get(f"/api/orders/{order_id}").json()
print("\n== the order now:", order.get("status"))
for part in order.get("parts", []):
    print(f"  {part['seller']['name']:6} {part['status']:12} {part.get('tracking_number') or ''}")


def chat_of(base: str, seller_id: str) -> dict:
    with httpx.Client(base_url=base, timeout=60) as client:
        return client.get(f"/api/chats/{seller_id}").json()


def lines(chat: dict) -> list[dict]:
    out = []
    for message in chat.get("messages", []):
        media = [m.get("kind") or m.get("media_type") for m in message.get("media", [])] if message.get("media") else []
        out.append({
            "from": "maker" if message.get("direction") == "inbound" else "OpenStall",
            "text": message.get("text") or "",
            "english": message.get("english") or "",
            "buttons": message.get("buttons") or [],
            "media": media,
            "voice_transcript": message.get("transcript") or "",
        })
    return out


chats = {
    "A0 Welcome on real WhatsApp (the hosted demo, a +92 number)": lines(chat_of(HOSTED_API, "s_53a82b0aeae3"))[:2],
    "A1 A maker lists her cushion cover (Urdu)": lines(chat_of(API, new_seller)),
    "A2 Amina: her share, her receipt, paid to her bank (Urdu)": lines(chat_of(API, "s_amina")),
    "A3 Priya: her share, her receipt, paid on proof (Hindi)": lines(chat_of(API, "s_priya")),
    "A4 Lucía: her share (Spanish)": lines(chat_of(API, "s_lucia")),
    "A5 Grace: her share, then she drops out (English)": lines(chat_of(API, "s_grace")),
}
(KIT / "whatsapp-scripts.json").write_text(json.dumps(chats, ensure_ascii=False, indent=2), encoding="utf-8")

md = ["# WhatsApp chats to animate", "",
      "Exported from the app itself on November 11 (test mode on this computer; A0 from the hosted demo's real "
      "WhatsApp). Each message is word for word what OpenStall sends or receives. *In English* lines are for the "
      "viewer; the maker sees only her language. Buttons are WhatsApp quick replies.", ""]
for title, messages in chats.items():
    md += [f"## {title}", ""]
    for m in messages:
        who = "**Maker**" if m["from"] == "maker" else "**OpenStall**"
        extra = f" [{', '.join(x for x in m['media'] if x)}]" if m["media"] else ""
        md.append(f"{who}{extra}:")
        md.append("")
        md += ["> " + line if line else ">" for line in (m["text"] or "(no words)").splitlines()]
        if m["voice_transcript"]:
            md += ["", f"*Voice note, as heard:* {m['voice_transcript']}"]
        if m["english"] and m["english"] != m["text"]:
            md += [""] + ["> *In English:* " + line if i == 0 else "> " + line
                          for i, line in enumerate(m["english"].splitlines())]
        if m["buttons"]:
            md += ["", "Buttons: " + " · ".join(f"[{b}]" for b in m["buttons"])]
        md.append("")
(KIT / "whatsapp-scripts.md").write_text("\n".join(md), encoding="utf-8")
print("\nwrote", KIT / "whatsapp-scripts.md", "and .json")
for title, messages in chats.items():
    print(f"  {title}: {len(messages)} messages")
