"""Step 10 Stage 3: live, per-conversation NPC dialogue -- NOT batch-
generated/pooled, same "owns its own try/except, never raises" posture as
generation/narrator.py's presentation-layer calls. Entirely offline
(MockClient only)."""
import json

from demonclock.generation.dialogue import (
    OPENING_SCHEMA,
    REPLY_SCHEMA,
    DialogueOpening,
    DialogueOption,
    run_dialogue_opening,
    run_dialogue_reply,
)
from demonclock.llm.config import GenerationConfig, ProviderSpec
from demonclock.llm.providers.mock import MockClient
from demonclock.llm.registry import LLMRegistry
from demonclock.models import NPC

NPC_FIXTURE = NPC(
    id="hana", name="Hana the Miller", location_id="village",
    description="Runs the grain mill.", tags=["villager", "merchant"],
)


def make_registry(responses: list[object]) -> LLMRegistry:
    config = GenerationConfig(roles={"dialogue": [ProviderSpec(provider="mock")]})
    return LLMRegistry(config, extra_clients={"mock": MockClient(responses=responses)})


class SpyClient:
    def __init__(self, response: dict) -> None:
        self._response = response
        self.last_user: str | None = None

    def generate_structured(self, system: str, user: str, schema: dict) -> dict:
        self.last_user = user
        return self._response


def make_spy_registry(response: dict) -> tuple[LLMRegistry, SpyClient]:
    spy = SpyClient(response)
    config = GenerationConfig(roles={"dialogue": [ProviderSpec(provider="spy")]})
    return LLMRegistry(config, extra_clients={"spy": spy}), spy


OPENING_RESPONSE = {
    "greeting": "Welcome to the mill!",
    "options": [
        {"label": "Ask about the harvest", "response": "Grain's coming in slow this year."},
        {"label": "Ask about the road north", "response": "Wouldn't go that way if I were you."},
    ],
}


# -- run_dialogue_opening ----------------------------------------------------

def test_run_dialogue_opening_returns_none_when_registry_is_none():
    assert run_dialogue_opening(None, NPC_FIXTURE) is None


def test_run_dialogue_opening_returns_none_when_registry_is_disabled():
    registry = LLMRegistry(GenerationConfig(roles={}))
    assert run_dialogue_opening(registry, NPC_FIXTURE) is None


def test_run_dialogue_opening_returns_none_when_dialogue_role_is_unconfigured():
    config = GenerationConfig(roles={"director": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": MockClient(responses=[])})
    assert run_dialogue_opening(registry, NPC_FIXTURE) is None


def test_run_dialogue_opening_parses_a_well_formed_response():
    registry = make_registry([OPENING_RESPONSE])

    opening = run_dialogue_opening(registry, NPC_FIXTURE)

    assert opening == DialogueOpening(
        greeting="Welcome to the mill!",
        options=[
            DialogueOption("Ask about the harvest", "Grain's coming in slow this year."),
            DialogueOption("Ask about the road north", "Wouldn't go that way if I were you."),
        ],
    )


def test_run_dialogue_opening_returns_none_on_a_provider_error():
    config = GenerationConfig(roles={"dialogue": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": MockClient(always_error=RuntimeError("down"))})
    assert run_dialogue_opening(registry, NPC_FIXTURE) is None


def test_run_dialogue_opening_returns_none_on_malformed_output():
    registry = make_registry([{"bad": "shape"}, {"still": "wrong"}])
    assert run_dialogue_opening(registry, NPC_FIXTURE) is None


def test_run_dialogue_opening_returns_none_when_options_come_back_empty():
    registry = make_registry([{"greeting": "Hi.", "options": []}])
    assert run_dialogue_opening(registry, NPC_FIXTURE) is None


def test_run_dialogue_opening_includes_the_role_hint_when_given():
    registry, spy = make_spy_registry(OPENING_RESPONSE)

    run_dialogue_opening(registry, NPC_FIXTURE, "trade-focused, combat-averse")

    sent = json.loads(spy.last_user)
    assert sent["player_role_hint"] == "trade-focused, combat-averse"


def test_run_dialogue_opening_omits_the_role_hint_key_when_not_given():
    registry, spy = make_spy_registry(OPENING_RESPONSE)

    run_dialogue_opening(registry, NPC_FIXTURE)

    sent = json.loads(spy.last_user)
    assert "player_role_hint" not in sent


def test_run_dialogue_opening_sends_the_npcs_own_fields():
    registry, spy = make_spy_registry(OPENING_RESPONSE)

    run_dialogue_opening(registry, NPC_FIXTURE)

    sent = json.loads(spy.last_user)
    assert sent["npc"] == {
        "name": "Hana the Miller", "description": "Runs the grain mill.", "tags": ["villager", "merchant"],
    }


def test_opening_schema_requires_greeting_and_options():
    assert set(OPENING_SCHEMA["required"]) == {"greeting", "options"}


# -- run_dialogue_reply -------------------------------------------------

def test_run_dialogue_reply_returns_none_when_registry_is_none():
    assert run_dialogue_reply(None, NPC_FIXTURE, "Any rumors?") is None


def test_run_dialogue_reply_returns_none_when_registry_is_disabled():
    registry = LLMRegistry(GenerationConfig(roles={}))
    assert run_dialogue_reply(registry, NPC_FIXTURE, "Any rumors?") is None


def test_run_dialogue_reply_uses_the_ai_response_when_the_call_succeeds():
    registry = make_registry([{"text": "Not since the blizzard cleared."}])

    reply = run_dialogue_reply(registry, NPC_FIXTURE, "Any rumors?")

    assert reply == "Not since the blizzard cleared."


def test_run_dialogue_reply_returns_none_on_a_provider_error():
    config = GenerationConfig(roles={"dialogue": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": MockClient(always_error=RuntimeError("down"))})
    assert run_dialogue_reply(registry, NPC_FIXTURE, "Any rumors?") is None


def test_run_dialogue_reply_returns_none_on_malformed_output():
    registry = make_registry([{"not_text": "oops"}, {"still": "wrong"}])
    assert run_dialogue_reply(registry, NPC_FIXTURE, "Any rumors?") is None


def test_run_dialogue_reply_returns_none_when_the_ai_returns_an_empty_string():
    registry = make_registry([{"text": "   "}])
    assert run_dialogue_reply(registry, NPC_FIXTURE, "Any rumors?") is None


def test_run_dialogue_reply_includes_the_player_message_in_its_payload():
    registry, spy = make_spy_registry({"text": "reply"})

    run_dialogue_reply(registry, NPC_FIXTURE, "What's beyond the wilds?")

    sent = json.loads(spy.last_user)
    assert sent["player_message"] == "What's beyond the wilds?"


def test_run_dialogue_reply_includes_the_role_hint_when_given():
    registry, spy = make_spy_registry({"text": "reply"})

    run_dialogue_reply(registry, NPC_FIXTURE, "hi", "socially active")

    sent = json.loads(spy.last_user)
    assert sent["player_role_hint"] == "socially active"


def test_run_dialogue_reply_omits_the_role_hint_key_when_not_given():
    registry, spy = make_spy_registry({"text": "reply"})

    run_dialogue_reply(registry, NPC_FIXTURE, "hi")

    sent = json.loads(spy.last_user)
    assert "player_role_hint" not in sent


def test_reply_schema_requires_text():
    assert REPLY_SCHEMA["required"] == ["text"]
