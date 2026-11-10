"""Telling each maker about her share (prompt 31, spec 3.6): once PayPal holds the order, each maker whose share is
reserved gets one message in her language, on WhatsApp or in the web chat, with what to make, by when, where it goes
and how she is paid. Nobody is told twice, and a message WhatsApp refuses is sent on the next try."""

import asyncio
import threading
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from mcp import Client
from sqlalchemy import select

from openstall_api.events import EventType
from openstall_api.main import app
from openstall_api.adapters import AdapterUnavailable
from openstall_api.models import (
    Channel,
    ChatMessage,
    ChatSession,
    Direction,
    Event,
    Order,
    OrderPart,
    PayoutRailChoice,
    Seller,
    utcnow,
)
from openstall_api.notices import (
    NoticeFacts,
    _claim,
    compose_notice,
    language_words,
    notify_order,
    ship_by,
    tell_maker,
)
from openstall_api.payments import release_share, reserve_order
from openstall_api.seed import DEMO_ORDER_ID, seed, seed_demo_order
from openstall_api.storefront import storefront
from openstall_api.whatsapp import MessengerError
from openstall_api.wording import english_of

client = TestClient(app)
TODAY = date(2026, 11, 10)  # the story's order is then due December 10, 2026, in Chicago
PRIYA_PHONE = "+15550100002"  # fictional (555-01xx), never a real phone

GRACE = NoticeFacts(
    maker="Grace",
    order_id="ord_demo",
    item="Hand-embroidered linen cushion cover",
    quantity=7,
    unit_price=Decimal("29.00"),
    amount=Decimal("203.00"),
    ship_by=date(2026, 12, 7),
    deliver_by=date(2026, 12, 10),
    ship_to="Chicago",
    paid_on_proof=True,
)


# The message itself


def test_the_english_message_says_what_to_make_by_when_where_and_how_she_is_paid():
    notice = compose_notice(GRACE, "en")

    assert notice.language == "en"
    assert notice.text == (
        "Hello Grace! You have a new order from OpenStall.\n"
        "\n"
        "Order: ord_demo\n"
        "Item: Hand-embroidered linen cushion cover\n"
        "Quantity: 7\n"
        "Price: $29.00 each, $203.00 in all\n"
        "Ship by: December 7, 2026\n"
        "Deliver to: Chicago, by December 10, 2026\n"
        "\n"
        "PayPal is holding your $203.00. When you ship, send a photo of the courier receipt here, and you will be "
        "paid then."
    )


@pytest.mark.parametrize(
    ("language", "ship", "deliver", "unit", "amount"),
    [
        ("ur", "7 دسمبر 2026", "10 دسمبر 2026 تک", "29.00 ڈالر فی عدد", "کل 203.00 ڈالر"),
        ("hi", "7 दिसंबर 2026", "10 दिसंबर 2026 तक", "$29.00 प्रति पीस", "कुल $203.00"),
        ("es", "7 de diciembre de 2026", "a más tardar el 10 de diciembre de 2026", "US$29.00 cada uno", "US$203.00"),
    ],
)
def test_each_language_has_every_fact_with_its_own_dates_and_money(language, ship, deliver, unit, amount):
    notice = compose_notice(GRACE, language)

    assert notice.language == language
    for fact in ("Grace", "ord_demo", "Hand-embroidered linen cushion cover", "7", ship, deliver, unit, amount):
        assert fact in notice.text, (language, fact)
    assert "Chicago" in notice.text
    assert "December" not in notice.text  # the date is in her language
    assert notice.text.count("\n") == 9  # the same lines as in English


def test_spanish_says_us_dollars_because_a_bare_dollar_sign_reads_as_pesos_in_mexico():
    assert "US$203.00" in compose_notice(GRACE, "es").text
    assert "US$" not in compose_notice(GRACE, "en").text


def test_urdu_writes_dollars_after_the_amount_so_it_reads_right_to_left():
    urdu = compose_notice(GRACE, "ur").text
    assert "PayPal نے آپ کے 203.00 ڈالر محفوظ کر لیے ہیں" in urdu
    assert "$" not in urdu


def test_she_is_promised_payment_on_her_receipt_only_when_a_payout_rail_can_reach_her():
    cannot_pay = NoticeFacts(**{**GRACE.__dict__, "paid_on_proof": False})

    paid = compose_notice(GRACE, "en").text
    waiting = compose_notice(cannot_pay, "en").text

    assert "send a photo of the courier receipt here, and you will be paid then" in paid
    assert waiting.endswith(
        "PayPal is holding your $203.00, but payouts to your country are not connected yet. Please wait for our "
        "message before you ship."
    )
    assert "you will be paid" not in waiting
    for language in ("ur", "hi", "es"):
        assert compose_notice(cannot_pay, language).text != compose_notice(GRACE, language).text


def test_a_language_without_a_template_gets_english_and_the_feed_says_so():
    notice = compose_notice(GRACE, "bn")

    assert (notice.language, notice.requested) == ("en", "bn")
    assert notice.text == compose_notice(GRACE, "en").text
    assert language_words(notice) == "English (no template for 'bn' yet)"
    assert language_words(compose_notice(GRACE, None)) == "English"
    assert language_words(compose_notice(GRACE, "ur")) == "Urdu"


def test_a_regional_language_code_uses_its_language():
    assert compose_notice(GRACE, "es-MX").language == "es"
    assert language_words(compose_notice(GRACE, "en-GB")) == "English"


def test_lines_without_their_facts_are_left_out_or_said_another_way():
    no_dates = NoticeFacts(**{**GRACE.__dict__, "ship_by": None, "deliver_by": None})
    no_place = NoticeFacts(**{**GRACE.__dict__, "ship_to": None})
    no_listing = NoticeFacts(**{**GRACE.__dict__, "item": None})

    assert "Ship by" not in compose_notice(no_dates, "en").text
    assert "Deliver to: Chicago\n" in compose_notice(no_dates, "en").text
    assert "Deliver by: December 10, 2026\n" in compose_notice(no_place, "en").text
    assert "Item: the items you offered\n" in compose_notice(no_listing, "en").text
    assert "Artículo: los artículos que ofreciste\n" in compose_notice(no_listing, "es").text


# The story's order


@pytest.fixture
def story(db):
    """The story's order (12/11/10/7, $815.00, due December 10 in Chicago), sent to the simulated PayPal and approved
    there by the buyer. Returns the database session."""
    seed(db, with_amina=True)
    seed_demo_order(db, TODAY)
    db.commit()
    token = client.post(f"/api/orders/{DEMO_ORDER_ID}/checkout").json()["paypal_order_id"]
    assert client.post(f"/api/dev/fake-paypal/{token}/approve").status_code == 200
    return db


def reserve() -> dict:
    response = client.post(f"/api/orders/{DEMO_ORDER_ID}/reserve")
    assert response.status_code == 200
    return response.json()


def notices(db) -> list[Event]:
    db.expire_all()
    query = select(Event).where(Event.type == EventType.ORDER_NOTICE_SENT.value).order_by(Event.id)
    return list(db.scalars(query))


def failures(db) -> list[Event]:
    db.expire_all()
    query = select(Event).where(Event.type == EventType.ORDER_NOTICE_FAILED.value).order_by(Event.id)
    return list(db.scalars(query))


def chat_of(db, seller_id: str) -> list[ChatMessage]:
    db.expire_all()
    query = (
        select(ChatMessage)
        .join(ChatSession, ChatSession.id == ChatMessage.session_id)
        .where(ChatSession.seller_id == seller_id)
        .order_by(ChatMessage.created_at)
    )
    return list(db.scalars(query))


def parts(db) -> dict[str, OrderPart]:
    db.expire_all()
    return {part.seller.name: part for part in db.get(Order, DEMO_ORDER_ID).parts}


def test_once_paypal_holds_the_order_each_maker_is_told_in_her_language(story, fakes):
    reserve()

    told = notices(story)
    assert [event.payload_json["summary"] for event in told] == [
        "Amina was told about her share in the web chat, in Urdu: 12 to ship by December 1",
        "Priya was told about her share in the web chat, in Hindi: 11 to ship by November 30",
        "Lucía was told about her share in the web chat, in Spanish: 10 to ship by December 4",
        "Grace was told about her share in the web chat, in English: 7 to ship by December 7",
    ]
    for seller_id, greeting in (
        ("s_amina", "السلام علیکم Amina!"),
        ("s_priya", "नमस्ते Priya!"),
        ("s_lucia", "¡Hola, Lucía!"),
        ("s_grace", "Hello Grace!"),
    ):
        [message] = chat_of(story, seller_id)
        assert (message.direction, message.channel) == (Direction.OUTBOUND, Channel.WEB)
        assert message.text.startswith(greeting)
        assert "ord_demo" in message.text
    # The seeded makers have no WhatsApp number: nothing went out on WhatsApp.
    assert fakes.messenger.calls == []
    assert all(part.notified_at is not None for part in parts(story).values())


@pytest.mark.parametrize("language", ["ur", "hi", "es"])
def test_each_notice_carries_the_same_facts_in_english_for_the_pages(language):
    notice = compose_notice(GRACE, language)

    assert english_of(notice.text) == compose_notice(GRACE, "en").text
    assert english_of(compose_notice(GRACE, "en").text) is None  # English needs no English line


def test_each_maker_told_in_her_language_keeps_its_english_and_the_chat_api_gives_it(story):
    reserve()

    english = {seller: chat_of(story, seller)[0].english for seller in ("s_amina", "s_priya", "s_lucia", "s_grace")}
    assert english["s_grace"] is None  # told in English
    told = (("s_amina", "Amina", "$216.00"), ("s_priya", "Priya", "$176.00"), ("s_lucia", "Lucía", "$220.00"))
    for seller, name, amount in told:
        assert english[seller].startswith(f"Hello {name}! You have a new order from OpenStall.")
        assert f"{amount} in all" in english[seller]
    [message] = client.get("/api/chats/s_amina").json()["messages"]
    assert message["english"] == english["s_amina"]
    assert message["text"].startswith("السلام علیکم Amina!")


def test_amina_is_promised_payment_on_her_receipt_as_hyperwallet_reaches_pakistan(story):
    reserve()

    [amina] = chat_of(story, "s_amina")
    assert "رسید کی تصویر یہاں بھیجیں، اسی وقت آپ کو ادائیگی ہو جائے گی" in amina.text
    assert "ادائیگی کا انتظام ابھی مکمل نہیں ہوا" not in amina.text


def test_a_maker_no_payout_rail_reaches_is_asked_to_wait(story):
    story.get(Seller, "s_amina").payout_rail = PayoutRailChoice.PAYPAL  # PayPal Payouts cannot reach Pakistan
    story.commit()
    reserve()

    [amina] = chat_of(story, "s_amina")
    [priya] = chat_of(story, "s_priya")
    assert "ادائیگی کا انتظام ابھی مکمل نہیں ہوا" in amina.text  # payouts to her country are not ready
    assert "ادائیگی ہو جائے گی" not in amina.text  # so she is not promised payment on her receipt
    assert "रसीद की फ़ोटो यहाँ भेजें" in priya.text  # Priya can be paid: send the receipt photo here


def test_the_receipt_shows_when_each_share_must_ship_and_that_she_was_told(story):
    order = reserve()

    # The answer goes out before the makers are told; the order read just after shows them told.
    after = client.get(f"/api/orders/{DEMO_ORDER_ID}").json()
    assert {part["seller"]["name"]: part["ship_by"] for part in after["parts"]} == {
        "Amina": "2026-12-01",
        "Priya": "2026-11-30",
        "Lucía": "2026-12-04",
        "Grace": "2026-12-07",
    }
    assert {part["delivery_date"] for part in after["parts"]} == {"2026-12-10"}
    assert [(part["notice"]["state"], part["notice"]["channel"], part["notice"]["language"]) for part in after["parts"]] == [
        ("sent", "web", "ur"),
        ("sent", "web", "hi"),
        ("sent", "web", "es"),
        ("sent", "web", "en"),
    ]
    assert all(part["notice"]["at"].endswith(("Z", "+00:00")) for part in after["parts"])
    assert all(part["notice"] is None for part in order["parts"])  # the reserve answer itself is not held up


def test_a_draft_order_has_no_notices_and_telling_it_does_nothing(db, fakes):
    seed(db, with_amina=True)
    seed_demo_order(db, TODAY)
    db.commit()

    assert notify_order(DEMO_ORDER_ID, lambda: fakes.messenger) == []
    assert notify_order("ord_missing", lambda: fakes.messenger) == []
    assert notices(db) == []
    draft = client.get(f"/api/orders/{DEMO_ORDER_ID}").json()
    assert all(part["notice"] is None for part in draft["parts"])


def test_reserving_again_tells_nobody_twice(story, fakes):
    reserve()
    reserve()

    assert len(notices(story)) == 4
    assert all(len(chat_of(story, seller_id)) == 1 for seller_id in ("s_amina", "s_priya", "s_lucia", "s_grace"))
    assert notify_order(DEMO_ORDER_ID, lambda: fakes.messenger) == []


def with_whatsapp(db, seller_id: str, number: str) -> None:
    db.get(Seller, seller_id).whatsapp_number = number
    db.commit()


def test_a_maker_with_a_whatsapp_number_is_told_on_whatsapp(story, fakes):
    with_whatsapp(story, "s_priya", PRIYA_PHONE)

    reserve()

    [sent] = fakes.messenger.calls
    assert sent.to == f"whatsapp:{PRIYA_PHONE}"
    assert sent.text.startswith("नमस्ते Priya! OpenStall से आपके लिए एक नया ऑर्डर आया है।")
    [stored] = chat_of(story, "s_priya")
    assert (stored.channel, stored.text) == (Channel.WHATSAPP, sent.text)
    priya = next(event for event in notices(story) if event.payload_json["seller_id"] == "s_priya")
    assert priya.payload_json["summary"] == (
        "Priya was told about her share on WhatsApp, in Hindi: 11 to ship by November 30"
    )
    assert (priya.payload_json["channel"], priya.payload_json["provider_message_id"]) == ("whatsapp", sent.message_id)
    assert priya.entity_id == parts(story)["Priya"].id


def refused(to, text, media_urls=()):
    raise MessengerError("Twilio refused the message (400): Twilio could not find a Channel with the From address")


def test_a_message_whatsapp_refuses_is_said_and_sent_on_the_next_try(story, fakes):
    with_whatsapp(story, "s_priya", PRIYA_PHONE)
    messenger = fakes.messenger
    messenger.send = refused  # WhatsApp refuses every message for now

    reserve()

    [failed] = failures(story)
    assert failed.payload_json["summary"] == (
        "Priya could not be told about her share on WhatsApp: Twilio refused the message (400): Twilio could not "
        "find a Channel with the From address"
    )
    assert parts(story)["Priya"].notified_at is None  # the claim was given back
    assert chat_of(story, "s_priya") == []  # nothing she did not receive is shown in her chat
    assert len(notices(story)) == 3  # the other makers were still told
    order = client.get(f"/api/orders/{DEMO_ORDER_ID}").json()
    priya = next(part for part in order["parts"] if part["seller"]["name"] == "Priya")
    assert priya["notice"]["state"] == "failed"
    assert priya["notice"]["reason"].startswith("Twilio refused the message (400)")

    del messenger.send  # WhatsApp works again: the receipt page reserving again sends it
    reserve()

    assert len(fakes.messenger.calls) == 1
    assert len(notices(story)) == 4
    order = client.get(f"/api/orders/{DEMO_ORDER_ID}").json()
    priya = next(part for part in order["parts"] if part["seller"]["name"] == "Priya")
    assert (priya["notice"]["state"], priya["notice"]["channel"]) == ("sent", "whatsapp")


def test_a_failure_never_shows_her_phone_number(story, fakes):
    """The reason is on the public /demo feed and the receipt, and Twilio quotes the number in some errors."""
    with_whatsapp(story, "s_priya", PRIYA_PHONE)

    def invalid(to, text, media_urls=()):
        raise MessengerError(f"Twilio refused the message (400): The 'To' number {to} is not a valid phone number.")

    fakes.messenger.send = invalid

    reserve()

    [failed] = failures(story)
    assert failed.payload_json["reason"] == (
        "Twilio refused the message (400): The 'To' number her number is not a valid phone number"
    )
    assert PRIYA_PHONE.removeprefix("+") not in str(failed.payload_json)


def test_sandbox_mode_without_twilio_keys_says_so_for_a_whatsapp_maker(story, fakes):
    with_whatsapp(story, "s_priya", PRIYA_PHONE)
    reserve_order(story, DEMO_ORDER_ID, fakes.payment_gateway)
    story.commit()

    def no_twilio():
        raise AdapterUnavailable("Sandbox mode needs TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN for the Messenger")

    told = notify_order(DEMO_ORDER_ID, no_twilio)

    assert len(told) == 3  # the web chat makers need no Twilio
    [failed] = failures(story)
    assert failed.payload_json["reason"] == (
        "Sandbox mode needs TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN for the Messenger"
    )


def test_a_released_share_is_not_told(story, fakes):
    reserve_order(story, DEMO_ORDER_ID, fakes.payment_gateway)
    story.commit()
    release_share(story, parts(story)["Lucía"].id, fakes.payment_gateway)
    story.commit()

    told = notify_order(DEMO_ORDER_ID, lambda: fakes.messenger)

    assert len(told) == 3
    assert chat_of(story, "s_lucia") == []
    assert "Lucía" not in " ".join(event.payload_json["summary"] for event in notices(story))


def test_only_one_request_can_claim_a_share(story, fakes):
    reserve_order(story, DEMO_ORDER_ID, fakes.payment_gateway)
    story.commit()
    part_id = parts(story)["Grace"].id

    now = utcnow()
    assert _claim(story, part_id, now) is True
    story.commit()
    assert _claim(story, part_id, now) is False  # claimed a moment ago: someone is telling her
    # A claim left by a stopped process is taken over after two minutes ...
    assert _claim(story, part_id, now + timedelta(minutes=3)) is True
    story.rollback()
    # ... but never once she has been told.
    assert tell_maker(part_id, lambda: fakes.messenger) is False  # still claimed (by `now`)
    parts(story)["Grace"].notified_at = None
    story.commit()
    assert tell_maker(part_id, lambda: fakes.messenger) is True
    assert _claim(story, part_id, utcnow() + timedelta(hours=1)) is False


def test_two_requests_at_once_send_her_one_message(story, fakes):
    with_whatsapp(story, "s_priya", PRIYA_PHONE)
    reserve_order(story, DEMO_ORDER_ID, fakes.payment_gateway)
    story.commit()
    part_id = parts(story)["Priya"].id
    sending, release = threading.Event(), threading.Event()
    real_send = fakes.messenger.send

    def slow_send(to, text, media_urls=()):
        sending.set()
        assert release.wait(5)
        return real_send(to, text, media_urls)

    fakes.messenger.send = slow_send
    results: list[bool] = []
    first = threading.Thread(target=lambda: results.append(tell_maker(part_id, lambda: fakes.messenger)))
    first.start()
    assert sending.wait(5)  # the first request has claimed her share and is sending

    second = tell_maker(part_id, lambda: fakes.messenger)
    release.set()
    first.join(5)

    assert (results, second) == ([True], False)
    assert len(fakes.messenger.calls) == 1
    assert len(chat_of(story, "s_priya")) == 1


def test_ship_by_is_the_delivery_date_less_her_ship_days(story):
    by_name = parts(story)
    assert ship_by(by_name["Amina"]) == date(2026, 12, 1)  # 9 ship days to Chicago
    assert ship_by(by_name["Grace"]) == date(2026, 12, 7)  # 3 ship days
    grace = by_name["Grace"]
    grace.product = None
    assert ship_by(grace) == date(2026, 12, 10)  # no listing to say how long it travels
    grace.delivery_date = None
    assert ship_by(grace) is None
    story.rollback()


# The buyer agent's view


def get_order_status(order_id: str) -> dict:
    async def go():
        async with Client(storefront) as mcp:
            return await mcp.call_tool("get_order_status", {"order_id": order_id})

    result = asyncio.run(go())
    assert not result.is_error, result.content
    return result.structured_content


def test_the_buyer_agent_sees_when_each_maker_was_told_and_must_ship(story):
    before = get_order_status(DEMO_ORDER_ID)
    assert {share["told_at"] for share in before["shares"]} == {None}

    reserve()

    after = get_order_status(DEMO_ORDER_ID)
    assert all(share["told_at"] for share in after["shares"])
    assert {share["seller_name"]: share["ship_by"] for share in after["shares"]} == {
        "Amina": "2026-12-01",
        "Priya": "2026-11-30",
        "Lucía": "2026-12-04",
        "Grace": "2026-12-07",
    }
