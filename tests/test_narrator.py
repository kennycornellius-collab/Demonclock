"""Step 7 Chunk A: the Narrator agent's rumor-rewording job -- rewording an
already-decided rumor string, never inventing a fact. Step 7 Chunk B added
`narrate_combat_outcome`: a once-per-fight summary of an already-decided
combat log. Step 7 Chunk D added an optional `derived_role_hint` param to
both, for tone-only word-choice guidance. Entirely offline (MockClient
only), same posture as every other generation-role test."""
import json

from demonclock.generation.narrator import (
    NARRATE_COMBAT_SCHEMA,
    REWORD_RUMOR_SCHEMA,
    narrate_combat_outcome,
    reword_rumor,
)
from demonclock.llm.config import GenerationConfig, ProviderSpec
from demonclock.llm.providers.mock import MockClient
from demonclock.llm.registry import LLMRegistry


def make_registry(responses: list[object]) -> LLMRegistry:
    config = GenerationConfig(roles={"narrator": [ProviderSpec(provider="mock")]})
    return LLMRegistry(config, extra_clients={"mock": MockClient(responses=responses)})


class SpyClient:
    """A minimal duck-typed LLMClient that remembers the last `user` JSON
    string it was sent, so a test can assert what actually landed in the
    payload -- MockClient never records that, only the canned response."""

    def __init__(self, response: dict) -> None:
        self._response = response
        self.last_user: str | None = None

    def generate_structured(self, system: str, user: str, schema: dict) -> dict:
        self.last_user = user
        return self._response


def make_spy_registry(response: dict) -> tuple[LLMRegistry, SpyClient]:
    spy = SpyClient(response)
    config = GenerationConfig(roles={"narrator": [ProviderSpec(provider="spy")]})
    return LLMRegistry(config, extra_clients={"spy": spy}), spy


def test_reword_rumor_returns_the_original_text_when_registry_is_none():
    assert reword_rumor(None, "A falls.", 0.8) == "A falls."


def test_reword_rumor_returns_the_original_text_when_registry_is_disabled():
    registry = LLMRegistry(GenerationConfig(roles={}))
    assert reword_rumor(registry, "A falls.", 0.8) == "A falls."


def test_reword_rumor_returns_the_original_text_when_narrator_role_is_unconfigured():
    # Some other role (director) is configured, but not narrator specifically
    # -- registry.enabled is True, but generate("narrator", ...) raises
    # NoProviderConfiguredError, which must still degrade gracefully.
    config = GenerationConfig(roles={"director": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": MockClient(responses=[])})

    assert reword_rumor(registry, "A falls.", 0.8) == "A falls."


def test_reword_rumor_uses_the_ai_response_when_the_call_succeeds():
    registry = make_registry([{"text": "They say the town of A has fallen..."}])

    assert reword_rumor(registry, "A falls.", 0.8) == "They say the town of A has fallen..."


def test_reword_rumor_falls_back_to_original_text_on_a_provider_error():
    config = GenerationConfig(roles={"narrator": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": MockClient(always_error=RuntimeError("down"))})

    assert reword_rumor(registry, "A falls.", 0.8) == "A falls."


def test_reword_rumor_falls_back_to_original_text_on_malformed_output():
    registry = make_registry([{"not_text": "oops"}, {"still": "wrong"}])

    assert reword_rumor(registry, "A falls.", 0.8) == "A falls."


def test_reword_rumor_falls_back_when_the_ai_returns_an_empty_string():
    registry = make_registry([{"text": "   "}])

    assert reword_rumor(registry, "A falls.", 0.8) == "A falls."


def test_reword_rumor_schema_requires_text():
    assert REWORD_RUMOR_SCHEMA["required"] == ["text"]


# -- narrate_combat_outcome (Chunk B) ---------------------------------------

SAMPLE_LOG = ["You hit the Goblin with Basic Attack for 5 damage.", "You defeated the Goblin!"]


def test_narrate_combat_outcome_returns_none_when_registry_is_none():
    assert narrate_combat_outcome(None, "Goblin", "victory", SAMPLE_LOG) is None


def test_narrate_combat_outcome_returns_none_when_registry_is_disabled():
    registry = LLMRegistry(GenerationConfig(roles={}))
    assert narrate_combat_outcome(registry, "Goblin", "victory", SAMPLE_LOG) is None


def test_narrate_combat_outcome_returns_none_when_narrator_role_is_unconfigured():
    config = GenerationConfig(roles={"director": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": MockClient(responses=[])})

    assert narrate_combat_outcome(registry, "Goblin", "victory", SAMPLE_LOG) is None


def test_narrate_combat_outcome_uses_the_ai_response_when_the_call_succeeds():
    registry = make_registry([{"text": "You cut the Goblin down with a single, decisive blow."}])

    result = narrate_combat_outcome(registry, "Goblin", "victory", SAMPLE_LOG)

    assert result == "You cut the Goblin down with a single, decisive blow."


def test_narrate_combat_outcome_returns_none_on_a_provider_error():
    config = GenerationConfig(roles={"narrator": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={"mock": MockClient(always_error=RuntimeError("down"))})

    assert narrate_combat_outcome(registry, "Goblin", "victory", SAMPLE_LOG) is None


def test_narrate_combat_outcome_returns_none_on_malformed_output():
    registry = make_registry([{"not_text": "oops"}, {"still": "wrong"}])

    assert narrate_combat_outcome(registry, "Goblin", "victory", SAMPLE_LOG) is None


def test_narrate_combat_outcome_returns_none_when_the_ai_returns_an_empty_string():
    registry = make_registry([{"text": "   "}])

    assert narrate_combat_outcome(registry, "Goblin", "victory", SAMPLE_LOG) is None


def test_narrate_combat_schema_requires_text():
    assert NARRATE_COMBAT_SCHEMA["required"] == ["text"]


# -- derived_role_hint tone biasing (Step 7 Chunk D) ------------------------

def test_reword_rumor_includes_the_role_hint_in_its_payload_when_given():
    registry, spy = make_spy_registry({"text": "reworded"})

    reword_rumor(registry, "A falls.", 0.8, "trade-focused, combat-averse")

    sent = json.loads(spy.last_user)
    assert sent["player_role_hint"] == "trade-focused, combat-averse"


def test_reword_rumor_omits_the_role_hint_key_when_not_given():
    registry, spy = make_spy_registry({"text": "reworded"})

    reword_rumor(registry, "A falls.", 0.8)

    sent = json.loads(spy.last_user)
    assert "player_role_hint" not in sent


def test_narrate_combat_outcome_includes_the_role_hint_in_its_payload_when_given():
    registry, spy = make_spy_registry({"text": "summary"})

    narrate_combat_outcome(registry, "Goblin", "victory", SAMPLE_LOG, "combat-focused")

    sent = json.loads(spy.last_user)
    assert sent["player_role_hint"] == "combat-focused"


def test_narrate_combat_outcome_omits_the_role_hint_key_when_not_given():
    registry, spy = make_spy_registry({"text": "summary"})

    narrate_combat_outcome(registry, "Goblin", "victory", SAMPLE_LOG)

    sent = json.loads(spy.last_user)
    assert "player_role_hint" not in sent
