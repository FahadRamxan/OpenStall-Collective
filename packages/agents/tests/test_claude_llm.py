"""ClaudeLLM, the real model in sandbox mode, against a fake transport: the requests it builds and every failure the
agents can act on. Nothing here reaches Anthropic's API."""

import json

import anthropic
import httpx2
import pytest

from openstall_agents.adapters import LLM, LLMError, Media
from openstall_agents.adapters.claude import FALLBACK_BETA, ClaudeLLM

SCHEMA = {
    "type": "object",
    "properties": {"unit_price_usd": {"type": "number"}, "message": {"type": "string"}},
    "required": ["unit_price_usd", "message"],
    "additionalProperties": False,
}
PHOTO = Media(b"\x89PNG made-up photo", "image/png")


def message(text: str, stop_reason: str = "end_turn") -> dict:
    """A Messages API answer with one text block."""
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-5-5",
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 9},
    }


class FakeAnthropic:
    """Answers every request with the next queued response and keeps the requests it was sent."""

    def __init__(self, *responses: httpx2.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def body(self, index: int = 0) -> dict:
        return json.loads(self.requests[index].content)


def llm(fake: FakeAnthropic, model: str = "claude-sonnet-5-5") -> ClaudeLLM:
    client = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(fake))
    return ClaudeLLM("sk-ant-made-up", model, max_retries=0, http_client=client)


def test_it_follows_the_llm_protocol():
    assert isinstance(llm(FakeAnthropic()), LLM)


def test_a_json_answer_uses_structured_outputs_low_effort_and_server_side_fallbacks():
    fake = FakeAnthropic(httpx2.Response(200, json=message('{"unit_price_usd": 29, "message": "Done."}')))

    answer = llm(fake).generate_json("Propose a price.", schema=SCHEMA, system="You sell cushions.")

    assert answer == {"unit_price_usd": 29, "message": "Done."}
    request = fake.requests[0]
    assert (request.method, request.url.path) == ("POST", "/v1/messages")
    assert FALLBACK_BETA in request.headers["anthropic-beta"]
    assert request.headers["authorization"] == "Bearer sk-ant-made-up"
    body = fake.body()
    assert body["model"] == "claude-sonnet-5-5"
    assert body["system"] == "You sell cushions."
    assert body["messages"] == [{"role": "user", "content": [{"type": "text", "text": "Propose a price."}]}]
    assert body["output_config"] == {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}}
    assert body["fallbacks"] == "default"
    # Thinking stays the model's default (adaptive), and no sampling settings are sent: newer API versions refuse them.
    assert not {"thinking", "temperature", "top_p", "top_k"} & set(body)


def test_a_model_without_server_side_fallbacks_gets_a_plain_request():
    fake = FakeAnthropic(httpx2.Response(200, json=message("Hello.")))

    assert llm(fake, model="claude-haiku-5-5").generate_text("Say hello.") == "Hello."

    assert "anthropic-beta" not in fake.requests[0].headers
    body = fake.body()
    assert "fallbacks" not in body and "system" not in body
    assert body["output_config"] == {"effort": "low"}


def test_photos_go_first_as_base64_image_blocks():
    fake = FakeAnthropic(httpx2.Response(200, json=message("A blue cushion.")))

    llm(fake).generate_text("Describe it.", images=[PHOTO])

    content = fake.body()["messages"][0]["content"]
    assert content == [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORyBtYWRlLXVwIHBob3Rv"}},
        {"type": "text", "text": "Describe it."},
    ]


def test_a_file_the_model_cannot_read_is_refused_before_any_request():
    fake = FakeAnthropic()

    with pytest.raises(LLMError, match="cannot read audio/ogg files"):
        llm(fake).generate_text("Transcribe it.", images=[Media(b"OggS", "audio/ogg")])
    assert fake.requests == []


@pytest.mark.parametrize(
    ("response", "words"),
    [
        (httpx2.Response(200, json=message("", "refusal")), "the model declined to answer"),
        (httpx2.Response(200, json=message('{"unit_price_usd": 2', "max_tokens")), "the model's answer was cut off"),
        (httpx2.Response(200, json=message("Sure! Here it is.")), "the model's answer was not JSON"),
        (httpx2.Response(200, json=message("[1, 2]")), "the model's answer was not a JSON object"),
        (httpx2.Response(429, json={"type": "error", "error": {"type": "rate_limit_error", "message": "Slow"}}), "rate limited"),
        (httpx2.Response(500, json={"type": "error", "error": {"type": "api_error", "message": "Oops"}}), "refused the request (500)"),
        (httpx2.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "Bad"}}), "refused the request (400)"),
        (httpx2.ConnectError("no route"), "the model could not be reached"),
        (httpx2.ReadTimeout("slow"), "the model took too long to answer"),
    ],
)
def test_every_failure_the_agents_can_act_on_is_an_llm_error_in_words(response, words):
    with pytest.raises(LLMError, match=words.replace("(", r"\(").replace(")", r"\)")):
        llm(FakeAnthropic(response)).generate_json("Propose a price.", schema=SCHEMA)
