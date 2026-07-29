"""Step 12 Chunk B: the free-text LLM parser fallback -- live, per-turn,
same "owns its own try/except, never raises" posture as narrator.py's/
dialogue.py's presentation-layer calls. Entirely offline (MockClient only).
"""
import json

from demonclock.generation.free_text import ParsedAction, run_free_text_fallback
from demonclock.llm.config import GenerationConfig, ProviderSpec
from demonclock.llm.providers.mock import MockClient
from demonclock.llm.registry import LLMRegistry
from demonclock.parser import ActionType


def make_registry(responses: list[object]) -> LLMRegistry:
    config = GenerationConfig(roles={"parser": [ProviderSpec(provider="mock")]})
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
    config = GenerationConfig(roles={"parser": [ProviderSpec(provider="spy")]})
    return LLMRegistry(config, extra_clients={"spy": spy}), spy


AVAILABLE = [ActionType.MOVE, ActionType.LOOK, ActionType.TALK]


def test_returns_none_when_registry_is_none():
    assert run_free_text_fallback(None, "wander toward the market", AVAILABLE) is None


def test_returns_none_when_registry_is_disabled():
    registry = LLMRegistry(GenerationConfig(roles={}))
    assert run_free_text_fallback(registry, "wander toward the market", AVAILABLE) is None


def test_returns_none_when_parser_role_is_unconfigured():
    config = GenerationConfig(roles={"director": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": MockClient(responses=[])})
    assert run_free_text_fallback(registry, "wander toward the market", AVAILABLE) is None


def test_returns_none_when_no_actions_are_available():
    registry = make_registry([{"action": ActionType.MOVE.value}])
    assert run_free_text_fallback(registry, "wander toward the market", []) is None


def test_resolves_a_well_formed_response_with_a_target():
    registry = make_registry([{"action": ActionType.MOVE.value, "target": "the market"}])

    result = run_free_text_fallback(registry, "wander toward the market", AVAILABLE)

    assert result == ParsedAction(action=ActionType.MOVE, target="the market")


def test_resolves_a_well_formed_response_with_no_target():
    registry = make_registry([{"action": ActionType.LOOK.value}])

    result = run_free_text_fallback(registry, "what's around here", AVAILABLE)

    assert result == ParsedAction(action=ActionType.LOOK, target=None)


def test_returns_none_when_the_model_answers_unrecognized():
    registry = make_registry([{"action": ActionType.UNRECOGNIZED.value}])
    assert run_free_text_fallback(registry, "shovel the snow", AVAILABLE) is None


def test_returns_none_when_target_is_blank():
    registry = make_registry([{"action": ActionType.LOOK.value, "target": "   "}])
    result = run_free_text_fallback(registry, "look around", AVAILABLE)
    assert result.target is None


def test_returns_none_on_a_provider_error():
    config = GenerationConfig(roles={"parser": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": MockClient(always_error=RuntimeError("down"))})
    assert run_free_text_fallback(registry, "wander toward the market", AVAILABLE) is None


def test_returns_none_on_malformed_output():
    registry = make_registry([{"bad": "shape"}, {"still": "wrong"}])
    assert run_free_text_fallback(registry, "wander toward the market", AVAILABLE) is None


def test_an_action_outside_the_available_list_is_rejected_as_malformed():
    # The schema enum is built ONLY from `available_actions` (+ the
    # UNRECOGNIZED sentinel) -- FIGHT isn't in AVAILABLE, so a response
    # naming it can't pass MockClient's own schema check, structurally
    # confirming the "cannot fabricate an unavailable action" guarantee.
    registry = make_registry([{"action": ActionType.FIGHT.value}, {"action": ActionType.FIGHT.value}])
    assert run_free_text_fallback(registry, "attack it", AVAILABLE) is None


def test_payload_includes_the_raw_text_and_available_actions():
    registry, spy = make_spy_registry({"action": ActionType.MOVE.value})

    run_free_text_fallback(registry, "wander toward the market", AVAILABLE)

    sent = json.loads(spy.last_user)
    assert sent["text"] == "wander toward the market"
    assert sent["available_actions"] == ["move", "look", "talk"]
