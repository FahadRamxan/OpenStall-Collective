"""The story through the local test-mode API, up to a receipt with every kind of share on it: Priya paid on proof
(PayPal), Amina paid on proof (her bank through Hyperwallet, simulated), Lucía still reserved, Grace released. Prints
the order id and writes it to receipt-order.txt for the recorder. Test mode only."""

import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

sys.stdout.reconfigure(encoding="utf-8")
c = httpx.Client(base_url="http://localhost:8000", timeout=120)


def post(path, **kwargs):
    response = c.post(path, **kwargs)
    if response.status_code >= 400:
        raise SystemExit(f"{path}: {response.status_code} {response.text[:300]}")
    return response.json() if response.content else None


assert c.get("/api/status").json()["mode"] == "fake", "refusing: the local API is not in test mode"
post("/api/demo/reset")
order_id = post("/api/demo/run")["order_id"]
checkout = post(f"/api/orders/{order_id}/checkout")
parts = urlsplit(checkout["approval_url"])
token = (parse_qs(parts.query).get("token") or [parts.path.rstrip("/").split("/")[-1]])[0]
post(f"/api/dev/fake-paypal/{token}/approve")
post(f"/api/orders/{order_id}/reserve")
time.sleep(4)
post("/api/dev/sellers/s_priya/messages", json={"receipt": True})
post("/api/dev/sellers/s_priya/messages", json={"text": "हाँ"})
post("/api/dev/sellers/s_amina/messages", json={"receipt": True})
post("/api/dev/sellers/s_amina/messages", json={"text": "جی ہاں"})
post("/api/dev/sellers/s_grace/messages", json={"text": "Sorry, I can't make this order."})
post("/api/dev/sellers/s_grace/messages", json={"text": "Yes"})
time.sleep(4)
order = c.get(f"/api/orders/{order_id}").json()
print("order", order_id, order.get("status"))
for part in order.get("parts", []):
    print(f"  {part['seller']['name']:6} {part['status']:11} {part.get('tracking_number') or ''}")
Path(__file__).with_name("receipt-order.txt").write_text(order_id, encoding="utf-8")
