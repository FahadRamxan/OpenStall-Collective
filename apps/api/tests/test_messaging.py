"""FakeMessenger: records WhatsApp messages instead of sending them, with ids that are the same on every run."""

from openstall_api.messaging import FakeMessenger, Messenger, SentMessage

# Fictional numbers (555-01xx), never real phones.
AMINA = "whatsapp:+15550100001"
PRIYA = "whatsapp:+15550100002"


def test_follows_the_messenger_interface():
    assert isinstance(FakeMessenger(), Messenger)


def test_records_each_message_with_ids_that_count_up():
    messenger = FakeMessenger()

    first = messenger.send(AMINA, "New order: 12 cushion covers")
    second = messenger.send(PRIYA, "New order: 11 cushion covers", ["https://openstall.example/media/receipt.jpg"])

    assert messenger.calls == [
        SentMessage("fake-msg-0001", AMINA, "New order: 12 cushion covers"),
        SentMessage(
            "fake-msg-0002",
            PRIYA,
            "New order: 11 cushion covers",
            ("https://openstall.example/media/receipt.jpg",),
        ),
    ]
    assert [first, second] == messenger.calls


def test_ids_are_the_same_on_every_run():
    first, second = FakeMessenger().send(AMINA, "Hi"), FakeMessenger().send(AMINA, "Hi")
    assert first.message_id == second.message_id == "fake-msg-0001"


def test_lists_the_messages_sent_to_one_number():
    messenger = FakeMessenger()
    messenger.send(AMINA, "one")
    messenger.send(PRIYA, "two")
    messenger.send(AMINA, "three")

    assert [message.text for message in messenger.sent_to(AMINA)] == ["one", "three"]
