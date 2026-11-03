"""What the model says in fake mode: each agent's stand-in answer, worked out from the request it was sent, the same
on every run, so offline demos and UI tests behave like the real thing.

The adapter registry gives fake mode's FakeLLM this responder. Each agent adds its own answer here as it is built.
"""

from openstall_agents.adapters.llm import LLMCall, Reply
from openstall_agents.seller_agent import fake_seller_reply

ANSWERS = (fake_seller_reply,)


def fake_answer(call: LLMCall) -> Reply:
    """The first agent's answer that recognises the request, else FakeLLM's own default."""
    for answer in ANSWERS:
        reply = answer(call)
        if reply is not None:
            return reply
    return {} if call.kind == "json" else f"Fake reply to: {call.prompt[:80]}"
